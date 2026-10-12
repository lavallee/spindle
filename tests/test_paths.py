"""Tests for spindle.paths — platform-only path functions."""

from __future__ import annotations

import spindle.paths as paths_mod


def test_feedback_dir_under_spindle_home(monkeypatch, tmp_path):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path))
    assert paths_mod.feedback_dir() == tmp_path / "feedback"


def test_ledger_path_under_spindle_home(monkeypatch, tmp_path):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path))
    assert paths_mod.ledger_path() == tmp_path / "ledger.jsonl"


def test_candidates_dir_under_spindle_home(monkeypatch, tmp_path):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path))
    assert paths_mod.candidates_dir() == tmp_path / "verdicts" / "_candidates"


def test_adapter_receipts_default_under_spindle_home(monkeypatch, tmp_path):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path))
    assert paths_mod.activation_receipts_dir() == tmp_path / "activation-receipts"
    assert paths_mod.delegation_receipts_dir() == tmp_path / "delegation-receipts"


def test_lifecycle_state_defaults_under_spindle_home(monkeypatch, tmp_path):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path))
    assert paths_mod.package_cache_dir() == tmp_path / "cache" / "packages"
    assert paths_mod.surface_locks_dir() == tmp_path / "surface-locks"
    assert paths_mod.ownership_receipts_dir() == tmp_path / "ownership-receipts"
    assert paths_mod.ownership_index_dir() == tmp_path / "ownership"
    assert paths_mod.conflict_receipts_dir() == tmp_path / "conflict-receipts"


def test_startup_and_hook_state_defaults_under_spindle_home(monkeypatch, tmp_path):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path))
    assert paths_mod.startup_plans_dir() == tmp_path / "startup-plans"
    assert paths_mod.startup_receipts_dir() == tmp_path / "startup-receipts"
    assert (
        paths_mod.startup_observations_file() == tmp_path / "startup-observations.jsonl"
    )
    assert paths_mod.startup_locks_dir() == tmp_path / "startup-locks"
    assert (
        paths_mod.inventory_digest_cache_dir()
        == tmp_path / "cache" / "inventory-digests"
    )
    assert paths_mod.hook_receipts_dir() == tmp_path / "hook-receipts"
    assert paths_mod.hook_index_file() == tmp_path / "hooks.json"


def test_spindle_home_default():
    import os
    from pathlib import Path

    env_val = os.environ.get("SPINDLE_HOME")
    if env_val is None:
        expected = Path.home() / ".spindle"
        assert paths_mod.spindle_home() == expected


def test_claude_skills_dir_default():
    import os
    from pathlib import Path

    env_val = os.environ.get("CLAUDE_SKILLS_DIR")
    if env_val is None:
        expected = Path.home() / ".claude" / "skills"
        assert paths_mod.claude_skills_dir() == expected
