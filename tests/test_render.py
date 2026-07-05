"""Tests for spindle.render — guardrail extraction, verification, store, render fn."""

from __future__ import annotations

import spindle.render as render
from spindle.channels import Surface
from spindle.composition import ComposedSkill, Composition

SOURCE = """\
# sample-grill

Some framing prose.

ALWAYS interrogate the premise before planning.
NEVER fabricate findings.

More prose.
"""


def _skill_dir(tmp_path, name, text=SOURCE):
    d = tmp_path / name
    d.mkdir()
    (d / "SKILL.md").write_text(text)
    (d / "extra.txt").write_text("aux\n")
    return d


# ---- guardrail extraction + verification --------------------------------

def test_extract_guardrails():
    g = render.extract_guardrails(SOURCE)
    assert any("ALWAYS interrogate" in x for x in g)
    assert any("NEVER fabricate" in x for x in g)
    assert len(g) == 2


def test_verify_preserved_identity_ok():
    assert render.verify_preserved(SOURCE, SOURCE) == []


def test_verify_preserved_catches_dropped_guardrail():
    rendered = SOURCE.replace("NEVER fabricate findings.", "")
    missing = render.verify_preserved(SOURCE, rendered)
    assert len(missing) == 1
    assert "NEVER fabricate" in missing[0]


def test_verify_preserved_tolerates_whitespace_reflow():
    # rewrapping whitespace must NOT count as dropping a guardrail
    rendered = SOURCE.replace("ALWAYS interrogate the premise before planning.",
                              "ALWAYS   interrogate the premise   before planning.")
    assert render.verify_preserved(SOURCE, rendered) == []


# ---- cache key ----------------------------------------------------------

def test_cache_key_changes_with_each_axis():
    p1 = render.Profile("claude", "1", render.identity_transform)
    p2 = render.Profile("claude", "2", render.identity_transform)
    base = render.cache_key("d1", p1, "x")
    assert base != render.cache_key("d2", p1, "x")   # doctrine
    assert base != render.cache_key("d1", p2, "x")   # profile version
    assert base != render.cache_key("d1", p1, "y")   # content


# ---- render_skill -------------------------------------------------------

def test_render_skill_writes_store_and_copies_aux(tmp_path):
    src = _skill_dir(tmp_path, "grill")
    store = tmp_path / "store"
    profile = render.Profile("claude", "1", render.identity_transform)
    out = render.render_skill(src, profile, "0.1.0+abc", store_root=store)
    assert (out / "SKILL.md").exists()
    assert (out / "extra.txt").read_text() == "aux\n"  # aux files copied verbatim
    assert out.parent.parent == store


def test_render_skill_raises_on_dropped_guardrail(tmp_path):
    src = _skill_dir(tmp_path, "grill")
    store = tmp_path / "store"
    # a transform that nukes a guardrail line
    bad = render.Profile("evil", "1", lambda t: t.replace("NEVER fabricate findings.", ""))
    try:
        render.render_skill(src, bad, "d", store_root=store)
        assert False, "expected RenderError"
    except render.RenderError as e:
        assert any("NEVER fabricate" in p for p in e.problems)


def test_render_skill_is_cached(tmp_path):
    src = _skill_dir(tmp_path, "grill")
    store = tmp_path / "store"
    profile = render.Profile("claude", "1", render.identity_transform)
    out1 = render.render_skill(src, profile, "d", store_root=store)
    out2 = render.render_skill(src, profile, "d", store_root=store)
    assert out1 == out2  # same cache key → same dir


# ---- make_render_fn (binder hook) ---------------------------------------

def test_make_render_fn_passes_through_when_no_profile(tmp_path):
    comp = Composition(surface="r", autonomy_mode="deterministic",
                       skills=[ComposedSkill("grill", "/grill", "system", source_dir=str(tmp_path))])
    fn = render.make_render_fn({}, "d", store_root=tmp_path / "s")
    out = fn(comp, Surface(name="r", harness="pi", autonomy_mode="deterministic"))
    assert out.skills[0].source_dir == str(tmp_path)  # unchanged


def test_make_render_fn_repoints_source_dir(tmp_path):
    src = _skill_dir(tmp_path, "grill")
    comp = Composition(surface="r", autonomy_mode="deterministic",
                       skills=[ComposedSkill("grill", "/grill", "system", source_dir=str(src))])
    profile = render.Profile("claude", "1", render.identity_transform)
    fn = render.make_render_fn({"claude": profile}, "0.1.0+abc", store_root=tmp_path / "s")
    out = fn(comp, Surface(name="r", harness="claude", autonomy_mode="deterministic"))
    assert out.skills[0].source_dir != str(src)        # repointed at rendered dir
    assert str(tmp_path / "s") in out.skills[0].source_dir  # lives under the store
    assert out.skills[0].source_dir.endswith("/grill")


def test_make_render_fn_raises_aggregated_guardrail_drops(tmp_path):
    src = _skill_dir(tmp_path, "grill")
    comp = Composition(surface="r", autonomy_mode="deterministic",
                       skills=[ComposedSkill("grill", "/grill", "system", source_dir=str(src))])
    bad = render.Profile("claude", "1", lambda t: "# stripped\n")
    fn = render.make_render_fn({"claude": bad}, "d", store_root=tmp_path / "s")
    try:
        fn(comp, Surface(name="r", harness="claude", autonomy_mode="deterministic"))
        assert False, "expected RenderError"
    except render.RenderError as e:
        assert len(e.problems) == 2  # both guardrails dropped
