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
    c1 = binding.compute_coordinate(_comp("a", "b"), doctrine_coordinate="0.1.0+abc",
                                    channel_versions={"system": "1.0"})
    c2 = binding.compute_coordinate(_comp("b", "a"), doctrine_coordinate="0.1.0+abc",
                                    channel_versions={"system": "1.0"})
    assert c1 == c2  # skill order doesn't matter


def test_coordinate_changes_with_skills():
    base = binding.compute_coordinate(_comp("a"), doctrine_coordinate="d", channel_versions={})
    more = binding.compute_coordinate(_comp("a", "b"), doctrine_coordinate="d", channel_versions={})
    assert base != more


def test_coordinate_changes_with_doctrine():
    a = binding.compute_coordinate(_comp("a"), doctrine_coordinate="d1", channel_versions={})
    b = binding.compute_coordinate(_comp("a"), doctrine_coordinate="d2", channel_versions={})
    assert a != b


def test_coordinate_changes_with_channel_version():
    a = binding.compute_coordinate(_comp("a"), doctrine_coordinate="d", channel_versions={"sys": "1"})
    b = binding.compute_coordinate(_comp("a"), doctrine_coordinate="d", channel_versions={"sys": "2"})
    assert a != b


def test_record_and_read_current(tmp_path, monkeypatch):
    monkeypatch.setattr(binding.paths, "spindle_home", lambda: tmp_path)
    rec = binding.record_binding(_comp("a", "b"), doctrine_coordinate="0.1.0+abc",
                                 channel_versions={"system": "1.0"})
    cur = binding.current_binding("repo:barn-owl")
    assert cur is not None
    assert cur.coordinate == rec.coordinate
    assert cur.skills == ["a", "b"]
    assert cur.doctrine_coordinate == "0.1.0+abc"


def test_history_preserved_for_rollback(tmp_path, monkeypatch):
    monkeypatch.setattr(binding.paths, "spindle_home", lambda: tmp_path)
    r1 = binding.record_binding(_comp("a"), doctrine_coordinate="d1", channel_versions={})
    r2 = binding.record_binding(_comp("a", "b"), doctrine_coordinate="d2", channel_versions={})
    assert binding.current_binding("repo:barn-owl").coordinate == r2.coordinate
    # the earlier coordinate is still retrievable — the rollback target
    found = binding.find_coordinate("repo:barn-owl", r1.coordinate)
    assert found is not None
    assert found.skills == ["a"]


def test_current_binding_none_when_unbound(tmp_path, monkeypatch):
    monkeypatch.setattr(binding.paths, "spindle_home", lambda: tmp_path)
    assert binding.current_binding("never-bound") is None
    assert binding.find_coordinate("never-bound", "deadbeef") is None
