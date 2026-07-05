"""Tests for spindle.composition — the compose-time coherence linter."""

from __future__ import annotations

import spindle.composition as comp_mod
from spindle.composition import ComposedSkill, Composition
from spindle.doctrine import Absolute, Doctrine


def _doctrine(*absolute_ids_at_system):
    absolutes = [
        Absolute(id=i, scope="system", mode="NEVER", statement=f"guardrail {i}")
        for i in absolute_ids_at_system
    ]
    # one cluster-scope absolute that should NOT be required at the foundation
    absolutes.append(Absolute(id="C1", scope="cluster", mode="ALWAYS", statement="cluster rule"))
    return Doctrine(version="0.1.0", absolutes=absolutes)


def _ok_composition(**over):
    base = dict(
        surface="repo:barn-owl",
        autonomy_mode=comp_mod.SELF_EVOLVING,
        skills=[
            ComposedSkill(name="sample-grill", command="/sample-grill", scope="system"),
            ComposedSkill(name="sample-plan", command="/sample-plan", scope="cluster"),
        ],
        absolutes_in_force=["A1", "A2"],
    )
    base.update(over)
    return Composition(**base)


def test_clean_composition_passes():
    doc = _doctrine("A1", "A2")
    assert comp_mod.lint(_ok_composition(), doc) == []


def test_command_collision_flagged():
    doc = _doctrine("A1", "A2")
    comp = _ok_composition(skills=[
        ComposedSkill(name="a", command="/review", scope="system"),
        ComposedSkill(name="b", command="/review", scope="repo"),
    ])
    problems = comp_mod.lint(comp, doc)
    assert any("/review" in p and "multiple skills" in p for p in problems)


def test_duplicate_name_flagged():
    doc = _doctrine("A1", "A2")
    comp = _ok_composition(skills=[
        ComposedSkill(name="dup", command="/x", scope="system"),
        ComposedSkill(name="dup", command="/y", scope="repo"),
    ])
    assert any("duplicate skill name 'dup'" in p for p in comp_mod.lint(comp, doc))


def test_missing_system_absolute_no_longer_flagged():
    # D2: the blanket guardrail-intact check is dropped. A composition missing
    # system absolutes is NOT a lint failure (no current absolute is a genuine
    # composition guardrail; mandating them only over-constrains).
    doc = _doctrine("A1", "A2", "A3")
    comp = _ok_composition(autonomy_mode=comp_mod.SELF_EVOLVING, absolutes_in_force=["A1"])
    assert comp_mod.lint(comp, doc) == []


def test_cluster_scope_absolute_not_required_at_foundation():
    doc = _doctrine("A1")  # plus C1 at cluster scope from helper
    comp = _ok_composition(absolutes_in_force=["A1"])
    # C1 is cluster-scope, so its absence from in_force is not a foundation problem
    assert comp_mod.lint(comp, doc) == []


def test_irreversible_skill_requires_a4():
    doc = _doctrine("A1")
    comp = _ok_composition(
        absolutes_in_force=["A1"],  # no A4
        skills=[ComposedSkill(name="deployer", command="/deploy", scope="repo", irreversible=True)],
    )
    problems = comp_mod.lint(comp, doc)
    assert any("deployer" in p and "A4" in p for p in problems)


def test_irreversible_skill_ok_when_a4_in_force():
    doc = _doctrine("A1")
    comp = _ok_composition(
        absolutes_in_force=["A1", "A4"],
        skills=[ComposedSkill(name="deployer", command="/deploy", scope="repo", irreversible=True)],
    )
    assert comp_mod.lint(comp, doc) == []


def test_bad_autonomy_mode_flagged():
    doc = _doctrine("A1")
    comp = _ok_composition(autonomy_mode="freewheeling", absolutes_in_force=["A1"])
    assert any("bad autonomy_mode" in p for p in comp_mod.lint(comp, doc))


def test_deterministic_mode_is_valid():
    doc = _doctrine("A1")
    comp = _ok_composition(autonomy_mode=comp_mod.DETERMINISTIC, absolutes_in_force=["A1"])
    assert comp_mod.lint(comp, doc) == []


# ---- resolver -----------------------------------------------------------

from spindle.composition import ChannelLayer, resolve, resolve_and_lint  # noqa: E402


def test_resolve_more_specific_scope_wins_slot():
    sys_skill = ComposedSkill(name="review-sys", command="/review", scope="system")
    repo_skill = ComposedSkill(name="review-repo", command="/review", scope="repo")
    comp = resolve(
        [ChannelLayer("system", [sys_skill]), ChannelLayer("repo", [repo_skill])],
        surface="r", autonomy_mode=comp_mod.DETERMINISTIC,
    )
    cmds = {s.command: s.name for s in comp.skills}
    assert cmds["/review"] == "review-repo"  # repo overrides system
    assert len(comp.skills) == 1


def test_resolve_unions_absolutes_across_scopes():
    comp = resolve(
        [ChannelLayer("system", [], ["A1", "A2"]), ChannelLayer("repo", [], ["A4"])],
        surface="r", autonomy_mode=comp_mod.SELF_EVOLVING,
    )
    assert comp.absolutes_in_force == ["A1", "A2", "A4"]


def test_resolve_precedence_is_swappable():
    sys_skill = ComposedSkill(name="sys", command="/x", scope="system")
    repo_skill = ComposedSkill(name="repo", command="/x", scope="repo")
    layers = [ChannelLayer("system", [sys_skill]), ChannelLayer("repo", [repo_skill])]
    # Reverse precedence: system becomes most-specific, so system wins.
    comp = resolve(layers, surface="r", autonomy_mode=comp_mod.DETERMINISTIC,
                   precedence=("repo", "cluster", "system"))
    assert comp.skills[0].name == "sys"


def test_resolve_keeps_distinct_commands():
    comp = resolve(
        [ChannelLayer("system", [ComposedSkill("a", "/a", "system")]),
         ChannelLayer("cluster", [ComposedSkill("b", "/b", "cluster")])],
        surface="r", autonomy_mode=comp_mod.DETERMINISTIC,
    )
    assert {s.command for s in comp.skills} == {"/a", "/b"}


def test_resolve_output_is_deterministic():
    layers = [ChannelLayer("system", [
        ComposedSkill("zeta", "/z", "system"),
        ComposedSkill("alpha", "/a", "system"),
    ])]
    comp = resolve(layers, surface="r", autonomy_mode=comp_mod.DETERMINISTIC)
    assert [s.name for s in comp.skills] == ["alpha", "zeta"]  # sorted by name


def test_resolve_and_lint_no_longer_flags_missing_guardrail():
    # D2: missing system absolutes are no longer a lint failure.
    doc = _doctrine("A1", "A2")
    layers = [ChannelLayer("system", [ComposedSkill("g", "/g", "system")], ["A1"])]
    comp, problems = resolve_and_lint(layers, doc, surface="r",
                                      autonomy_mode=comp_mod.SELF_EVOLVING)
    assert problems == []


def test_cross_scope_shadow_recorded_as_info_not_flagged():
    # D3: a repo skill overriding a system skill for the same command is an
    # intended override — recorded on comp.shadows (info), NOT a lint problem.
    doc = _doctrine("A1")
    layers = [
        ChannelLayer("system", [ComposedSkill("sys-review", "/review", "system")]),
        ChannelLayer("repo", [ComposedSkill("repo-review", "/review", "repo")], ["A1"]),
    ]
    comp, problems = resolve_and_lint(layers, doc, surface="r",
                                      autonomy_mode=comp_mod.DETERMINISTIC)
    assert problems == []
    assert len(comp.shadows) == 1
    sh = comp.shadows[0]
    assert sh.winner == "repo-review" and sh.loser == "sys-review"
    assert sh.same_scope is False
    # repo won the slot
    assert [s.name for s in comp.skills] == ["repo-review"]


def test_same_scope_collision_recorded_and_flagged():
    # D3: two equally-specific channels claiming one command is an accidental
    # collision — recorded AND surfaced as a lint problem.
    doc = _doctrine("A1")
    layers = [
        ChannelLayer("cluster", [ComposedSkill("a", "/review", "cluster")]),
        ChannelLayer("cluster", [ComposedSkill("b", "/review", "cluster")], ["A1"]),
    ]
    comp, problems = resolve_and_lint(layers, doc, surface="r",
                                      autonomy_mode=comp_mod.DETERMINISTIC)
    assert len(comp.shadows) == 1
    assert comp.shadows[0].same_scope is True
    assert any("same-scope collision" in p for p in problems)


def test_resolve_and_lint_clean_passes():
    doc = _doctrine("A1")
    layers = [ChannelLayer("system", [ComposedSkill("g", "/g", "system")], ["A1"])]
    comp, problems = resolve_and_lint(layers, doc, surface="r",
                                      autonomy_mode=comp_mod.DETERMINISTIC)
    assert problems == []
    assert comp.absolutes_in_force == ["A1"]
