"""Static chippability scorer — does this skill hide a chip-shaped behaviour?

A *chip* is a tight bundle of prose guidance and deterministic code that an
agent banks to disk and delegates to: a deterministic envelope around exactly
one irreducible judgment, with durable cross-run state and a refusing gate.
The clearest tell is **a refusing gate over durable cross-run state**. This
module scores a skill for that signature from static text only — regex and
line scans over ``SKILL.md`` (frontmatter + body) and bundled files. No LLM,
no chip import, no chip host required: spindle only ever names strings and
emits files.

The placement discipline this feeds — the distillation ladder and the
falsifiability triage that decide whether a behaviour settles at a chip rung
or stays a prose skill — is documented publicly at
https://github.com/lavallee/chip (``docs/skill-to-chip.md``). The candidate
records this scorer emits follow the convention at
https://github.com/lavallee/chip (``docs/candidates.md``).

Scoring is ``score = f(positive signals) - g(negative signals)`` with tunable
weights (``POSITIVE_WEIGHTS`` / ``NEGATIVE_WEIGHTS``). Positive signals are
*presence* booleans so a longer skill cannot inflate its own score; negative
signals are *densities* (capped counts) because being dialogic is genuinely a
matter of how thickly the taste-and-ask verbs are laid on.

NOISE-GUARDS — deliberately NOT scored, in either direction (see the study's
§11.2 negative/noise list): SKILL.md length and step count (a chip can be long
or short); presence of bundled scripts (a TOOL tell, not a chip tell — the
stateless-but-script-heavy control skill proves it); persistent daemons
(infrastructure, not attention state); report/receipt writing (receipts do not
confer chip status). There is intentionally no regex for any of these; the
control fixture in the test-suite is a long, script-heavy, stateless skill and
it must score LOW.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import packages as packages_mod


# --- signal detectors ----------------------------------------------------
#
# Each detector is a callable ``str -> str | None``: given the scanned text it
# returns the first evidence line that fired, or None. Positive detectors are
# presence tests; negative detectors are handled separately as capped counts.

# Named durable-state nouns only. Bare data-file extensions (``.jsonl``) are
# deliberately excluded: an appended telemetry/analytics line is report/receipt
# writing (a noise-guard), not the read-back registry the signal is about.
_STATE_NOUN = re.compile(
    r"\b(ledger|registr(?:y|ies)|baseline|histor(?:y|ies)|dedupe set|"
    r"state file|[a-z0-9_-]*-log\b|[a-z0-9_-]*-history\b)\b",
    re.IGNORECASE,
)
_READBACK = re.compile(
    r"\b(read|reads|load|loads|append|appends|compare|compares|check|checks|"
    r"look up|recorded|stored|prior|previous|last run|across runs|"
    r"since last|persist|written|read back|seen before)\b",
    re.IGNORECASE,
)
_PERSIST_PATH = re.compile(r"(~/\.[\w./-]+|\.\w[\w-]*/[\w./-]+)")


def _sig_persistent_state(text: str) -> str | None:
    """A registry/ledger/state file written in one run and read back in a later
    one — the single best predictor of chip-hood. Fires only when a state noun
    co-occurs with a read-back verb or a persistent (home/project) path, which
    is what separates a durable registry from one-shot report/receipt writing
    (the noise-guard)."""
    for line in text.splitlines():
        if _STATE_NOUN.search(line) and (_READBACK.search(line) or _PERSIST_PATH.search(line)):
            return line.strip()
    return None


# "block" is constrained to verb usage — "blocks the merge", "blocked until" —
# so the noun in "frontmatter block" / "code block" does not read as a gate.
_REFUSING_GATE = re.compile(
    r"(exit(?:s|ed)?[- ]1|non-zero exit|refuses?|refusing|refuse to|"
    r"blocks?\s+(?:the\s+\w+|it|this|progress|merge|ship\w*|until|unless)|"
    r"blocked\s+(?:until|unless|by|from)|revert(?:s|ed)?|must pass|"
    r"fails? closed|won't (?:let|allow)|will not (?:allow|let)|"
    r"gate(?:s|d)? (?:the|it|before)|doctor exits|"
    r"before .{0,30}(?:ship|publish|merge|proceed))",
    re.IGNORECASE,
)


def _sig_refusing_gate(text: str) -> str | None:
    """A command or step that refuses / blocks / reverts rather than advising —
    the deterministic ``exit 1`` half of a chip's envelope."""
    m = _REFUSING_GATE.search(text)
    return _line_of(text, m) if m else None


_SHA = re.compile(r"\b(sha|commit|rev-list|head|revision|fingerprint)\b", re.IGNORECASE)
_FRESHNESS = re.compile(
    r"\b(chang(?:e|ed|es)\s+since|changed|stale|since last|recompute[sd]?|"
    r"invalidat\w*|out of date|no longer current|re-?derive)\b",
    re.IGNORECASE,
)


def _sig_sha_freshness(text: str) -> str | None:
    """A stored SHA/commit that is recomputed when the underlying thing changes —
    the sign-off-with-freshness-invalidation tell (a findings registry that goes
    stale on head/evidence change)."""
    for line in text.splitlines():
        if _SHA.search(line) and _FRESHNESS.search(line):
            return line.strip()
    # "changed since" / "stale" strong enough to fire alone
    m = re.search(r"\b(changed since|rev-list|goes? stale|marked stale)\b", text, re.IGNORECASE)
    return _line_of(text, m) if m else None


_BASELINE = re.compile(r"\b(baseline|benchmark|canary|reference (?:run|value))\b", re.IGNORECASE)
_THRESHOLD = re.compile(
    r"\b(threshold|regress\w*|anomal\w*|exceed\w*|delta|drift|"
    r"compare[ds]? against|over budget|below .{0,20}bar)\b",
    re.IGNORECASE,
)


def _sig_baseline_threshold(text: str) -> str | None:
    """Baseline + threshold → categorical regression verdict vocabulary."""
    if _BASELINE.search(text) and _THRESHOLD.search(text):
        m = _BASELINE.search(text)
        return _line_of(text, m)
    return None


# Enumerated verdict tokens: an explicit categorical schema, not a rubric.
_VERDICT_ENUM = re.compile(
    r"\b(cleared|not[- ]cleared|ready|concerns|abstain|verified|needs-2nd|"
    r"unconfirmed|retracted|issues_found|done_with_concerns|pass/fail|"
    r"approved|rejected|blocked|escalate|suppress)\b",
    re.IGNORECASE,
)
_VERDICT_WORD = re.compile(r"\bverdicts?\b", re.IGNORECASE)


def _sig_verdict_schema(text: str) -> str | None:
    """An explicit, enumerated categorical verdict schema (as opposed to a
    rubric table, which merely organises taste — that is a noise/negative).

    Fires on the literal word "verdict", or on >=2 *distinct* verdict tokens
    from the curated set (a single incidental "approved" is not enough, and a
    generic slash-list like "done/published/archived" no longer counts — it was
    too loose a proxy for a real verdict schema)."""
    m = _VERDICT_WORD.search(text)
    if m:
        return _line_of(text, m)
    tokens = {t.lower() for t in _VERDICT_ENUM.findall(text)}
    if len(tokens) >= 2:
        return _line_of(text, _VERDICT_ENUM.search(text))
    return None


_EVENT_TRIGGER = re.compile(
    r"(\bwhen\b[^.\n]{0,60}\b(happens|changes|reaches|occurs|arrives|lands|"
    r"is (?:done|created|opened|merged))\b|after every|after each|"
    r"post-(?:ship|deploy|merge|completion|effect|commit)|on inbound|"
    r"on every|invoke before|before .{0,30}(?:ships|publishes|is declared)|"
    r"end-of-life|each run)",
    re.IGNORECASE,
)


def _sig_event_trigger(text: str) -> str | None:
    """An event/signal trigger phrase — the "runs when X happens" activation
    shape rather than "run this when you feel like it"."""
    m = _EVENT_TRIGGER.search(text)
    return _line_of(text, m) if m else None


_DEDUPE = re.compile(
    r"\b(dedupe|deduplicat\w*|suppress\w*|already (?:seen|reported|flagged|"
    r"filed|noted)|seen before|skip\w* .{0,30}already|fingerprint\w*|"
    r"suppression (?:set|list)|do not (?:re-?litigate|re-?report))\b",
    re.IGNORECASE,
)


def _sig_cross_run_dedupe(text: str) -> str | None:
    """Cross-run dedupe / suppression language — a persisted set of things
    already handled so the same finding is not re-emitted every run."""
    m = _DEDUPE.search(text)
    return _line_of(text, m) if m else None


POSITIVE_SIGNALS: list[tuple[str, Callable[[str], "str | None"]]] = [
    ("persistent_state", _sig_persistent_state),
    ("refusing_gate", _sig_refusing_gate),
    ("sha_freshness", _sig_sha_freshness),
    ("baseline_threshold", _sig_baseline_threshold),
    ("verdict_schema", _sig_verdict_schema),
    ("event_trigger", _sig_event_trigger),
    ("cross_run_dedupe", _sig_cross_run_dedupe),
]

# Negative signals are counted (density), then capped. Each entry is
# (name, pattern, per_hit_weight, cap).
_INTERACTIVE = re.compile(
    r"(AskUserQuestion|ask the user|ask (?:whether|if|once)|confirm with|"
    r"prompt the user|ask them)",
    re.IGNORECASE,
)
_TASTE = re.compile(
    r"\b(push ?back|challenge|judgment|judge|opinionated|taste|critique|"
    r"your call|second-guess|argue|persuade)\b",
    re.IGNORECASE,
)
_TEACHING = re.compile(
    r"\b(guide|coach|brainstorm|teach|walk you through|"
    r"help you (?:think|explore|decide)|interview)\b",
    re.IGNORECASE,
)
NEGATIVE_SIGNALS = [
    ("interactive_density", _INTERACTIVE),
    ("taste_verb_density", _TASTE),
    ("teaching_framing", _TEACHING),
]

# A rubric/scoring table (or "decision principles") *without* a refusing gate is
# a negative: it organises taste, it does not enforce a decision. Conditional on
# refusing_gate being absent.
_RUBRIC = re.compile(
    r"(\brubric\b|scoring table|decision principles|\|\s*(?:score|confidence|"
    r"weight)\s*\|)",
    re.IGNORECASE,
)


# --- tunable weights -----------------------------------------------------
#
# Calibrated against a known-ordering set of real skills (see the calibration
# note in the PR): a sign-off/review skill and a post-deploy canary must land
# HIGH; a stateless document-processing skill must land LOW. Tune here.

POSITIVE_WEIGHTS = {
    "persistent_state": 3,   # best single predictor (study §11.2)
    "refusing_gate": 3,      # the deterministic exit-1 envelope
    "sha_freshness": 2,      # sign-off + freshness invalidation
    "baseline_threshold": 2,
    "verdict_schema": 2,
    "cross_run_dedupe": 2,
    "event_trigger": 1,      # weakest on its own; corroborates the others
}
NEGATIVE_WEIGHTS = {
    "interactive_density": 1,   # per hit, capped
    "taste_verb_density": 1,    # per hit, capped
    "teaching_framing": 1,      # per hit, capped
    "rubric_without_gate": 2,   # boolean
}
_DENSITY_CAP = 4  # no single density signal may contribute more than this many hits

# Classification thresholds (interpretable, bounded).
_CHIP_MIN_F = 3      # need at least one strong signal (or two mediums) of chip-shape
_CHIP_MIN_SCORE = 3  # …and the positives must clear the dialogic drag
_DIALOGIC_MIN_G = 3  # taste/ask density that marks a keep-as-dialogic skill


@dataclass(frozen=True)
class Signal:
    name: str
    polarity: str        # "positive" | "negative"
    evidence_line: str


@dataclass
class ChippabilityReport:
    skill: str
    package: str
    score: int
    classification_hint: str        # chip-candidate | tool | dialogic | mixed
    signals: list[Signal] = field(default_factory=list)
    draft_shape: str = ""           # one-sentence promise draft, only when candidate
    f: int = 0
    g: int = 0


# --- helpers -------------------------------------------------------------

def _line_of(text: str, match: re.Match | None) -> str | None:
    if match is None:
        return None
    start = text.rfind("\n", 0, match.start()) + 1
    end = text.find("\n", match.start())
    if end < 0:
        end = len(text)
    return text[start:end].strip()[:200]


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return (frontmatter dict, body). Mirrors the lenient parse used across
    spindle (``skills._read_frontmatter``) but also hands back the body."""
    fm: dict[str, str] = {}
    if not text.startswith("---"):
        return fm, text
    end = text.find("\n---", 3)
    if end < 0:
        return fm, text
    for line in text[3:end].splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            fm[key.strip()] = val.strip().strip('"').strip("'")
    body_start = text.find("\n", end + 1)
    body = text[body_start + 1:] if body_start >= 0 else ""
    return fm, body


_SCAN_BUDGET = 512 * 1024  # cap total bytes scanned so a giant bundle stays bounded


def _gather_text(skill_dir: Path) -> tuple[dict[str, str], str]:
    """Read SKILL.md (returning its frontmatter + body) and concatenate the
    bodies of sibling markdown/text files as extra scan material.

    Bundled scripts are *not* read as signal material (their presence is a
    noise-guard, and their content is a tool tell). Only ``.md`` / ``.txt``
    bundled files join the scan."""
    skill_md = skill_dir / "SKILL.md"
    try:
        raw = skill_md.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}, ""
    fm, body = split_frontmatter(raw)
    chunks = [body]
    budget = _SCAN_BUDGET - len(body)
    for path in sorted(skill_dir.rglob("*")):
        if budget <= 0:
            break
        if not path.is_file() or path.name == "SKILL.md":
            continue
        if path.suffix.lower() not in {".md", ".txt", ".mdx"}:
            continue
        try:
            extra = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        extra = extra[:budget]
        budget -= len(extra)
        chunks.append(extra)
    return fm, "\n".join(chunks)


def _draft_shape(signals: list[Signal], skill_name: str) -> str:
    """A one-line, falsifiable promise draft in the candidates.md convention:
    "when X happens, emit Y or a quiet receipt." Assembled from whichever
    signals fired — this is a lead for a human, never an authored contract."""
    fired = {s.name for s in signals if s.polarity == "positive"}
    trigger = "on each run"
    for s in signals:
        if s.name == "event_trigger":
            trigger = s.evidence_line[:60].rstrip(" :.-") or trigger
            break
    if "sha_freshness" in fired or "persistent_state" in fired:
        state = "the durable registry it keeps across runs"
    elif "baseline_threshold" in fired:
        state = "the stored baseline"
    else:
        state = "its cross-run state"
    verb = "gate the result" if "refusing_gate" in fired else "emit a verdict"
    return (
        f"when {trigger}, consult {state} and {verb} — "
        f"emit a categorical finding or a quiet receipt ({skill_name})"
    )


def _classify(f: int, g: int, positive_names: set[str]) -> str:
    score = f - g
    if f >= _CHIP_MIN_F and score >= _CHIP_MIN_SCORE:
        return "chip-candidate"
    if g >= _DIALOGIC_MIN_G and g > f:
        return "dialogic"
    if f == 0:
        return "tool"
    return "mixed"


def assess_text(text_body: str, *, skill: str = "", package: str = "") -> ChippabilityReport:
    """Score already-gathered scan text. Split out from :func:`assess_skill` so
    the scorer is testable without a filesystem skill dir."""
    signals: list[Signal] = []
    f = 0
    positive_names: set[str] = set()
    for name, detector in POSITIVE_SIGNALS:
        evidence = detector(text_body)
        if evidence:
            f += POSITIVE_WEIGHTS[name]
            positive_names.add(name)
            signals.append(Signal(name=name, polarity="positive", evidence_line=evidence))

    g = 0
    for name, pattern in NEGATIVE_SIGNALS:
        matches = pattern.findall(text_body)
        if matches:
            hits = min(len(matches), _DENSITY_CAP)
            g += hits * NEGATIVE_WEIGHTS[name]
            first = _line_of(text_body, pattern.search(text_body))
            signals.append(Signal(
                name=name, polarity="negative",
                evidence_line=f"{first}  (x{len(matches)})" if first else f"(x{len(matches)})",
            ))
    # rubric-without-gate: a rubric table only counts against when nothing gates.
    if "refusing_gate" not in positive_names:
        m = _RUBRIC.search(text_body)
        if m:
            g += NEGATIVE_WEIGHTS["rubric_without_gate"]
            signals.append(Signal(
                name="rubric_without_gate", polarity="negative",
                evidence_line=_line_of(text_body, m) or "rubric table without a gate",
            ))

    score = f - g
    hint = _classify(f, g, positive_names)
    draft = _draft_shape(signals, skill) if hint == "chip-candidate" else ""
    return ChippabilityReport(
        skill=skill, package=package, score=score, classification_hint=hint,
        signals=signals, draft_shape=draft, f=f, g=g,
    )


def assess_skill(skill_dir: str | Path, *, package: str = "") -> ChippabilityReport:
    """Assess a single skill directory (one containing ``SKILL.md``).

    Reads the skill's frontmatter + body and its bundled markdown, scans for the
    positive/negative signals, and returns a bounded, interpretable report. Pure
    static analysis — no subprocess, no network, no chip import."""
    skill_dir = Path(skill_dir)
    fm, text_body = _gather_text(skill_dir)
    name = fm.get("name") or skill_dir.name
    return assess_text(text_body, skill=name, package=package)


# --- discovery -----------------------------------------------------------

def discover_skill_dirs(root: str | Path) -> list[Path]:
    """Skill directories under ``root``.

    ``root`` may be a single skill dir (has ``SKILL.md``) or a package dir. For
    a package dir this reuses ``packages`` metadata when a spindle
    ``pyproject.toml`` is present (the declared skills list + the standard
    candidate layouts), and otherwise falls back to any ``SKILL.md`` found by
    walking the tree."""
    root = Path(root)
    if (root / "SKILL.md").is_file():
        return [root]

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        meta = packages_mod._parse_package_metadata(pyproject)
        if meta is not None and meta.skills:
            module = meta.name.replace("-", "_")
            dirs: list[Path] = []
            for skill in meta.skills:
                for candidate in (
                    root / module / "skills" / skill,
                    root / "src" / module / "skills" / skill,
                    root / skill,
                    root / "skills" / skill,
                ):
                    if (candidate / "SKILL.md").is_file():
                        dirs.append(candidate)
                        break
            if dirs:
                return sorted(dirs, key=lambda p: p.name)

    found = {p.parent for p in root.rglob("SKILL.md")}
    return sorted(found, key=lambda p: p.name)


def package_name_for(root: str | Path) -> str:
    """Best-effort package label for ledger/candidate records."""
    root = Path(root)
    base = root if root.is_dir() else root.parent
    pyproject = base / "pyproject.toml"
    if pyproject.is_file():
        meta = packages_mod._parse_package_metadata(pyproject)
        if meta is not None:
            return meta.name
    return base.name


# --- touchpoint A advisory ----------------------------------------------
#
# Compose-time: a chip-annotated skill (ComposedSkill.chip set) whose body
# carries no guardrail/gate line is advisory-worthy — it claims a chip alias but
# shows none of the refusing-gate shape a chip needs. This is an ADVISORY note,
# never a bind failure (spindle stays advisory about chips end to end). It lives
# here, in the chip-aware module, so composition.py stays pure I/O-free logic.

def advise_composition(comp) -> list[str]:
    """Advisory notes for chip-annotated skills in a resolved composition.

    For each skill carrying a ``chip:`` alias, read its SKILL.md and note it if
    the body shows no guardrail/gate line — the one shape a chip most needs.
    Returns a (possibly empty) list of human-readable advisory strings."""
    notes: list[str] = []
    for s in getattr(comp, "skills", []):
        chip = getattr(s, "chip", "") or ""
        if not chip:
            continue
        src = getattr(s, "source_dir", "") or ""
        if not src:
            continue
        _, body = _gather_text(Path(src))
        if not body:
            continue
        if _sig_refusing_gate(body) is None:
            notes.append(
                f"skill {s.name!r} is chip-annotated ({chip!r}) but its body has no "
                f"guardrail/gate line — a chip wants a refusing gate; treat the "
                f"annotation as advisory only"
            )
    return notes
