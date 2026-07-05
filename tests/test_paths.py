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
