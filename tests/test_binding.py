"""Tests for spindle.binding — coordinate determinism + per-surface history store."""

from __future__ import annotations

import spindle.binding as binding
from spindle.composition import ComposedSkill, Composition


def _comp(*names, surface="repo:barn-owl"):
    return Composition(
        surface=surface,
        autonomy_mode="deterministic",
        skills=[ComposedSkill(n, f"/{n}", "repo") for n in names],
    )


def test_coordinate_is_deterministic_for_same_inputs():
    c1 = binding.compute_coordinate(
        _comp("a", "b"),
        doctrine_coordinate="0.1.0+abc",
        channel_versions={"system": "1.0"},
    )
    c2 = binding.compute_coordinate(
        _comp("b", "a"),
        doctrine_coordinate="0.1.0+abc",
        channel_versions={"system": "1.0"},
    )
    assert c1 == c2  # skill order doesn't matter


def test_coordinate_changes_with_skills():
    base = binding.compute_coordinate(
        _comp("a"), doctrine_coordinate="d", channel_versions={}
    )
    more = binding.compute_coordinate(
        _comp("a", "b"), doctrine_coordinate="d", channel_versions={}
    )
    assert base != more


def test_coordinate_changes_with_doctrine():
    a = binding.compute_coordinate(
        _comp("a"), doctrine_coordinate="d1", channel_versions={}
    )
    b = binding.compute_coordinate(
        _comp("a"), doctrine_coordinate="d2", channel_versions={}
    )
    assert a != b


def test_coordinate_changes_with_channel_version():
    a = binding.compute_coordinate(
        _comp("a"), doctrine_coordinate="d", channel_versions={"sys": "1"}
    )
    b = binding.compute_coordinate(
        _comp("a"), doctrine_coordinate="d", channel_versions={"sys": "2"}
    )
    assert a != b


def test_coordinate_changes_when_editable_skill_content_changes(tmp_path):
    source = tmp_path / "review"
    source.mkdir()
    skill_file = source / "SKILL.md"
    skill_file.write_text("old\n")
    comp = Composition(
        surface="repo:demo",
        autonomy_mode="deterministic",
        skills=[ComposedSkill("review", "/review", "repo", source_dir=str(source))],
    )
    first = binding.compute_coordinate(
        comp, doctrine_coordinate="d", channel_versions={"repo": "1.0"}
    )
    skill_file.write_text("new content, same declared version\n")
    second = binding.compute_coordinate(
        comp, doctrine_coordinate="d", channel_versions={"repo": "1.0"}
    )

    assert first != second


def test_record_and_read_current(tmp_path, monkeypatch):
    monkeypatch.setattr(binding.paths, "spindle_home", lambda: tmp_path)
    rec = binding.record_binding(
        _comp("a", "b"),
        doctrine_coordinate="0.1.0+abc",
        channel_versions={"system": "1.0"},
    )
    cur = binding.current_binding("repo:barn-owl")
    assert cur is not None
    assert cur.coordinate == rec.coordinate
    assert cur.skills == ["a", "b"]
    assert cur.doctrine_coordinate == "0.1.0+abc"


def test_history_preserved_for_rollback(tmp_path, monkeypatch):
    monkeypatch.setattr(binding.paths, "spindle_home", lambda: tmp_path)
    r1 = binding.record_binding(
        _comp("a"), doctrine_coordinate="d1", channel_versions={}
    )
    r2 = binding.record_binding(
        _comp("a", "b"), doctrine_coordinate="d2", channel_versions={}
    )
    assert binding.current_binding("repo:barn-owl").coordinate == r2.coordinate
    # the earlier coordinate is still retrievable — the rollback target
    found = binding.find_coordinate("repo:barn-owl", r1.coordinate)
    assert found is not None
    assert found.skills == ["a"]


def test_current_binding_none_when_unbound(tmp_path, monkeypatch):
    monkeypatch.setattr(binding.paths, "spindle_home", lambda: tmp_path)
    assert binding.current_binding("never-bound") is None
    assert binding.find_coordinate("never-bound", "deadbeef") is None


def test_binding_records_runtime_profiled_skills(tmp_path, monkeypatch):
    monkeypatch.setattr(binding.paths, "spindle_home", lambda: tmp_path / "state")
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "SKILL.md").write_text("# runtime\n")
    (runtime_dir / "spindle-realization.toml").write_text("schema_version = 1\n")
    plain_dir = tmp_path / "plain"
    plain_dir.mkdir()
    (plain_dir / "SKILL.md").write_text("# plain\n")
    comp = Composition(
        surface="repo:demo",
        autonomy_mode="deterministic",
        skills=[
            ComposedSkill("runtime", "/runtime", "repo", source_dir=str(runtime_dir)),
            ComposedSkill("plain", "/plain", "repo", source_dir=str(plain_dir)),
        ],
    )

    rec = binding.record_binding(comp, doctrine_coordinate="d", channel_versions={})

    assert rec.runtime_profiled_skills == ["runtime"]
    assert binding.current_binding("repo:demo").runtime_profiled_skills == ["runtime"]


def test_binding_reads_legacy_record_without_runtime_profile_field(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(binding.paths, "spindle_home", lambda: tmp_path)
    path = tmp_path / "bindings" / "legacy.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        """[
  {
    "surface": "legacy",
    "coordinate": "abc",
    "doctrine_coordinate": "d",
    "skills": ["plain"],
    "channel_versions": {},
    "bound_at": "2026-01-01T00:00:00Z"
  }
]
"""
    )

    rec = binding.current_binding("legacy")

    assert rec is not None
    assert rec.runtime_profiled_skills is None
