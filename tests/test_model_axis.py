"""Tests for the model axis — render-density tuning per model (project × harness ×
model). Covers the subtractive ``trim_scaffold`` transform, the model-profile loader,
the harness+model render composition, the cache key, and the fail-closed guarantee
that a guardrail can never be trimmed away."""

from __future__ import annotations

from pathlib import Path

import spindle.profiles as profiles
import spindle.render as render
from spindle.channels import Surface
from spindle.composition import ComposedSkill, Composition

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_ROOT = REPO_ROOT / "examples" / "spindle-sample"

# A skill with a scaffold fence (optional teaching material) plus guardrails that live
# OUTSIDE the fence — the correct authoring shape.
SOURCE = """\
# sample-grill

Interrogate the premise before planning.

<!-- scaffold:examples -->
For example, if the user asks for a cache, ask whether eviction matters,
whether staleness is acceptable, and what the read/write ratio is.
<!-- /scaffold -->

ALWAYS interrogate the premise before planning.
NEVER fabricate findings.
"""


def _skill_dir(tmp_path, name, text=SOURCE):
    d = tmp_path / name
    d.mkdir()
    (d / "SKILL.md").write_text(text)
    return d


# ---- trim_scaffold (the subtractive transform) --------------------------

def test_trim_scaffold_strips_fenced_block():
    out = profiles.trim_scaffold(SOURCE)
    assert "For example" not in out          # the scaffold body is gone
    assert "<!-- scaffold" not in out         # fences gone
    assert "<!-- /scaffold" not in out


def test_trim_scaffold_keeps_guardrails_outside_fence():
    out = profiles.trim_scaffold(SOURCE)
    assert "ALWAYS interrogate the premise before planning." in out
    assert "NEVER fabricate findings." in out
    # surrounding prose survives
    assert "Interrogate the premise before planning." in out


def test_trim_scaffold_noop_without_fences():
    plain = "# s\n\nALWAYS do the thing.\n"
    assert "ALWAYS do the thing." in profiles.trim_scaffold(plain)


# ---- fail-closed: a guardrail inside a fence cannot be trimmed away ------

def test_trim_inside_fence_fails_closed(tmp_path):
    # An author MISTAKE: a NEVER guardrail buried in a scaffold block. Trimming it
    # would silently drop the floor — verify_preserved must catch it and the render
    # must fail closed.
    bad_source = (
        "# s\n\n<!-- scaffold:note -->\nNEVER deploy without approval.\n"
        "<!-- /scaffold -->\n\nALWAYS plan first.\n"
    )
    src = _skill_dir(tmp_path, "bad", bad_source)
    hp = render.Profile("identity", "0", render.identity_transform)
    mp = render.Profile("frontier", "1", profiles.trim_scaffold)
    try:
        render.render_skill(src, hp, "d", model_profile=mp, store_root=tmp_path / "store")
        assert False, "expected RenderError — a guardrail was trimmed"
    except render.RenderError as e:
        assert any("NEVER deploy" in p for p in e.problems)


# ---- load_model_profiles ------------------------------------------------

def test_load_model_profiles_reads_frontier():
    mps = profiles.load_model_profiles(source_dir=SAMPLE_ROOT)
    assert "frontier" in mps
    assert mps["frontier"].transform is profiles.trim_scaffold


def test_load_profiles_skips_models_dir():
    # the models/ dir must not be mistaken for a harness profile
    hs = profiles.load_profiles(source_dir=SAMPLE_ROOT)
    assert "models" not in hs
    assert "claude" in hs  # the real harness profiles still load


# ---- cache key folds in the model axis ----------------------------------

def test_cache_key_changes_with_model_profile():
    hp = render.Profile("claude", "1", render.identity_transform)
    mp = render.Profile("frontier", "1", render.identity_transform)
    base = render.cache_key("d1", hp, "x")
    assert base != render.cache_key("d1", hp, "x", mp)          # model present
    mp2 = render.Profile("frontier", "2", render.identity_transform)
    assert render.cache_key("d1", hp, "x", mp) != render.cache_key("d1", hp, "x", mp2)


# ---- render_skill composes harness then model ---------------------------

def test_render_skill_applies_both_axes(tmp_path):
    src = _skill_dir(tmp_path, "grill")
    hp = render.Profile("claude", "1", render.identity_transform)
    mp = render.Profile("frontier", "1", profiles.trim_scaffold)
    out = render.render_skill(src, hp, "0.1.0+abc", model_profile=mp,
                              store_root=tmp_path / "store")
    text = (out / "SKILL.md").read_text()
    assert "For example" not in text                 # model axis trimmed scaffold
    assert "NEVER fabricate findings." in text        # guardrail survives


# ---- make_render_fn with the model axis ---------------------------------

def test_make_render_fn_applies_model_profile(tmp_path):
    src = _skill_dir(tmp_path, "grill")
    comp = Composition(surface="r", autonomy_mode="deterministic",
                       skills=[ComposedSkill("grill", "/grill", "system", source_dir=str(src))])
    hp = render.Profile("claude", "1", render.identity_transform)
    mp = render.Profile("frontier", "1", profiles.trim_scaffold)
    fn = render.make_render_fn({"claude": hp}, "0.1.0+abc",
                               model_profiles={"frontier": mp}, store_root=tmp_path / "s")
    out = fn(comp, Surface(name="r", harness="claude", autonomy_mode="deterministic",
                           model="frontier"))
    text = Path(out.skills[0].source_dir, "SKILL.md").read_text()
    assert "For example" not in text


def test_make_render_fn_model_only_no_harness_profile(tmp_path):
    # a harness with no dialect profile still gets model-density tuning
    src = _skill_dir(tmp_path, "grill")
    comp = Composition(surface="r", autonomy_mode="deterministic",
                       skills=[ComposedSkill("grill", "/grill", "system", source_dir=str(src))])
    mp = render.Profile("frontier", "1", profiles.trim_scaffold)
    fn = render.make_render_fn({}, "d", model_profiles={"frontier": mp},
                               store_root=tmp_path / "s")
    out = fn(comp, Surface(name="r", harness="pi", autonomy_mode="deterministic",
                           model="frontier"))
    assert out.skills[0].source_dir != str(src)       # rendered, not pass-through
    text = Path(out.skills[0].source_dir, "SKILL.md").read_text()
    assert "For example" not in text


def test_make_render_fn_passthrough_when_no_model_and_no_harness(tmp_path):
    src = _skill_dir(tmp_path, "grill")
    comp = Composition(surface="r", autonomy_mode="deterministic",
                       skills=[ComposedSkill("grill", "/grill", "system", source_dir=str(src))])
    mp = render.Profile("frontier", "1", profiles.trim_scaffold)
    fn = render.make_render_fn({}, "d", model_profiles={"frontier": mp},
                               store_root=tmp_path / "s")
    # harness has no profile AND surface.model is None → verbatim
    out = fn(comp, Surface(name="r", harness="pi", autonomy_mode="deterministic"))
    assert out.skills[0].source_dir == str(src)


def test_surface_model_defaults_none():
    s = Surface(name="r", harness="claude", autonomy_mode="deterministic")
    assert s.model is None
