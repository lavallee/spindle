"""Tests for spindle.chippability — the static chip-shape scorer.

Each positive signal and each negative signal gets a focused fixture, the
noise-guards get a dedicated control case (a long, script-heavy, stateless
skill must score LOW), and discovery + the touchpoint-A advisory are covered.
"""

from __future__ import annotations

import spindle.chippability as chip


# --- positive signals ----------------------------------------------------

def _fired(report, name):
    return any(s.name == name and s.polarity == "positive" for s in report.signals)


def _neg(report, name):
    return any(s.name == name and s.polarity == "negative" for s in report.signals)


def test_persistent_state_signal():
    text = "Append each finding to ~/.myapp/findings-log and read it back on the next run."
    r = chip.assess_text(text)
    assert _fired(r, "persistent_state")


def test_persistent_state_not_fired_on_bare_telemetry_line():
    # a plain appended data file with no named state noun is not a registry
    text = "echo '{\"event\":\"run\"}' >> ~/.app/analytics/usage.jsonl"
    r = chip.assess_text(text)
    assert not _fired(r, "persistent_state")


def test_refusing_gate_signal():
    text = "Run the doctor. It exits 1 and refuses to proceed while errors remain."
    r = chip.assess_text(text)
    assert _fired(r, "refusing_gate")


def test_refusing_gate_ignores_block_as_noun():
    # "frontmatter block" / "code block" must not read as a gate
    text = "Keep the frontmatter block intact and edit the prose in the code block below."
    r = chip.assess_text(text)
    assert not _fired(r, "refusing_gate")


def test_sha_freshness_signal():
    text = "Store the commit SHA on each record; recompute when the file changed since last run."
    r = chip.assess_text(text)
    assert _fired(r, "sha_freshness")


def test_baseline_threshold_signal():
    text = "Compare against the pre-deploy baseline and flag any regression past the threshold."
    r = chip.assess_text(text)
    assert _fired(r, "baseline_threshold")


def test_verdict_schema_signal_word():
    text = "Emit a single verdict line at the end summarising the run."
    r = chip.assess_text(text)
    assert _fired(r, "verdict_schema")


def test_verdict_schema_signal_enum_tokens():
    text = "Move each claim to verified, needs-2nd, unconfirmed, or retracted."
    r = chip.assess_text(text)
    assert _fired(r, "verdict_schema")


def test_verdict_schema_not_fired_on_generic_slash_list():
    text = "The notebook can be active/dormant/done/published/archived over its life."
    r = chip.assess_text(text)
    assert not _fired(r, "verdict_schema")


def test_event_trigger_signal():
    text = "Invoke this after every deploy, and again when the queue reaches its cap."
    r = chip.assess_text(text)
    assert _fired(r, "event_trigger")


def test_cross_run_dedupe_signal():
    text = "Keep a suppression set so a finding already reported in a prior run is not re-emitted."
    r = chip.assess_text(text)
    assert _fired(r, "cross_run_dedupe")
    # (also fires persistent_state via 'prior run' — both are legitimate here)


# --- negative signals ----------------------------------------------------

def test_interactive_density_signal():
    text = "AskUserQuestion about scope. Then ask the user to confirm. Ask the user again if unsure."
    r = chip.assess_text(text)
    assert _neg(r, "interactive_density")


def test_taste_verb_density_signal():
    text = "Push back on weak framing, challenge the premise, and judge the result on taste."
    r = chip.assess_text(text)
    assert _neg(r, "taste_verb_density")


def test_teaching_framing_signal():
    text = "Interview the user, coach them, and brainstorm options together — guide the exploration."
    r = chip.assess_text(text)
    assert _neg(r, "teaching_framing")


def test_rubric_without_gate_is_negative_but_suppressed_by_a_gate():
    rubric = "Score each row in the rubric table: | score | weight |"
    assert _neg(chip.assess_text(rubric), "rubric_without_gate")
    # the same rubric with a refusing gate present is NOT counted against
    gated = rubric + "\nThe doctor exits 1 and refuses to proceed while any row fails."
    assert not _neg(chip.assess_text(gated), "rubric_without_gate")


# --- classification + noise-guards --------------------------------------

CHIP_CANDIDATE = """\
---
name: signoff
---
# signoff — the sign-off gate

Invoke this after every review lands. Read the findings registry at
~/.signoff/registry and compare against the stored commit SHA; a record goes
stale when the file changed since last run. The doctor exits 1 and refuses to
proceed while any load-bearing finding is unresolved. Keep a suppression set so
a finding already reported in a prior run is not re-emitted.

Emit a single verdict: cleared, concerns, or abstain.
"""

DIALOGIC = """\
---
name: office-hours
---
# office-hours

Interview the founder and coach them through the idea. Push back hard, challenge
the premise, and judge the pitch on taste. AskUserQuestion at each fork; ask the
user to confirm before moving on. Ask the user what they are most unsure about.
This is a conversation, not a gate — your call throughout.
"""

PLAIN_TOOL = """\
---
name: pdf
---
# PDF processing

Read a PDF, extract its text, merge two files, split pages, rotate, watermark.
Use pypdf and pdfplumber. This is a reference for common operations.
"""

# The control: long, script-heavy, stateless, writes reports, mentions a daemon.
# Every one of those is a NOISE-GUARD; none is a chip signal. Must score LOW.
CONTROL_NOISE = (
    """\
---
name: bulk-convert
---
# bulk-convert — a long, script-heavy, stateless converter

"""
    + "\n".join(
        f"{i}. Step {i}: run `scripts/convert_{i}.sh` to process the input and "
        f"write a report to out/report_{i}.md. The conversion daemon streams "
        f"progress; the receipt is written when the step completes."
        for i in range(1, 60)
    )
)


def test_chip_candidate_classification_and_draft_shape():
    r = chip.assess_text(CHIP_CANDIDATE, skill="signoff")
    assert r.classification_hint == "chip-candidate"
    assert r.f >= chip._CHIP_MIN_F
    assert r.score >= chip._CHIP_MIN_SCORE
    assert r.draft_shape  # a promise draft is produced for candidates
    assert "signoff" in r.draft_shape


def test_dialogic_classification():
    r = chip.assess_text(DIALOGIC, skill="office-hours")
    assert r.classification_hint == "dialogic"
    assert r.g > r.f


def test_plain_tool_classification():
    r = chip.assess_text(PLAIN_TOOL, skill="pdf")
    assert r.classification_hint in {"tool", "mixed"}
    assert r.classification_hint != "chip-candidate"


def test_control_noise_scores_low():
    """The load-bearing control: length, step count, bundled-script mentions,
    a daemon, and report/receipt writing are all noise-guards. This skill must
    NOT be a chip-candidate and must not score high."""
    r = chip.assess_text(CONTROL_NOISE, skill="bulk-convert")
    assert r.classification_hint != "chip-candidate"
    assert r.f == 0
    assert r.score <= 0


def test_length_does_not_inflate_positive_score():
    """Repeating a positive signal many times does not raise f — positives are
    presence booleans, so a long skill cannot pump its own score."""
    once = chip.assess_text("The doctor exits 1 and refuses to proceed.")
    many = chip.assess_text("The doctor exits 1 and refuses to proceed.\n" * 50)
    assert once.f == many.f


# --- assess_skill + discovery -------------------------------------------

def _write_skill(root, name, body):
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n{body}\n")
    return d


def test_assess_skill_reads_bundled_markdown(tmp_path):
    d = _write_skill(tmp_path, "gated", "# gated\n\nSee triage.md for the gate rules.")
    # the gate signal lives only in a bundled file
    (d / "triage.md").write_text("The doctor exits 1 and refuses to proceed while errors remain.")
    r = chip.assess_skill(d, package="demo")
    assert _fired(r, "refusing_gate")
    assert r.package == "demo"
    assert r.skill == "gated"


def test_discover_skill_dirs_single_skill(tmp_path):
    d = _write_skill(tmp_path, "solo", "# solo")
    assert chip.discover_skill_dirs(d) == [d]


def test_discover_skill_dirs_walks_tree(tmp_path):
    _write_skill(tmp_path / "pkg", "one", "# one")
    _write_skill(tmp_path / "pkg", "two", "# two")
    found = {p.name for p in chip.discover_skill_dirs(tmp_path)}
    assert found == {"one", "two"}


def test_discover_skill_dirs_uses_package_metadata(tmp_path):
    # reuse packages._parse_package_metadata via a spindle pyproject
    (tmp_path / "pyproject.toml").write_text(
        "[tool.spindle.package]\n"
        'name = "demo"\nversion = "0.1.0"\n'
        'skills = ["alpha"]\n'
    )
    _write_skill(tmp_path / "demo" / "skills", "alpha", "# alpha")
    # a stray SKILL.md the metadata does NOT declare should be excluded
    _write_skill(tmp_path, "undeclared", "# undeclared")
    found = [p.name for p in chip.discover_skill_dirs(tmp_path)]
    assert found == ["alpha"]
    assert chip.package_name_for(tmp_path) == "demo"


# --- touchpoint A advisory ----------------------------------------------

class _S:
    def __init__(self, name, source_dir, chip_alias):
        self.name = name
        self.source_dir = source_dir
        self.chip = chip_alias


class _Comp:
    def __init__(self, skills):
        self.skills = skills


def test_advise_composition_flags_chip_annotation_without_guardrail(tmp_path):
    d = _write_skill(tmp_path, "soft", "# soft\n\nJust some gentle guidance, no gate here.")
    comp = _Comp([_S("soft", str(d), "some-chip")])
    notes = chip.advise_composition(comp)
    assert len(notes) == 1
    assert "soft" in notes[0]


def test_advise_composition_quiet_when_guardrail_present(tmp_path):
    d = _write_skill(tmp_path, "hard", "# hard\n\nThe doctor exits 1 and refuses to proceed.")
    comp = _Comp([_S("hard", str(d), "some-chip")])
    assert chip.advise_composition(comp) == []


def test_advise_composition_ignores_unannotated_skills(tmp_path):
    d = _write_skill(tmp_path, "plain", "# plain\n\nNo gate, but also no chip alias.")
    comp = _Comp([_S("plain", str(d), "")])
    assert chip.advise_composition(comp) == []
