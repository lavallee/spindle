"""Tests that install/uninstall/preempt/unpreempt emit the right ledger events."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from spindle.paths import events_file
from spindle.models import SkillSpec


@pytest.fixture(autouse=True)
def isolated_spindle_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "spindle-state"))


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    sd = tmp_path / "skills"
    sd.mkdir()
    monkeypatch.setenv("CLAUDE_SKILLS_DIR", str(sd))
    return sd


@pytest.fixture
def src(tmp_path):
    d = tmp_path / "src"
    d.mkdir()
    return d


def _make_skill(base: Path, name: str) -> SkillSpec:
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\n---\n")
    return SkillSpec(name=name, package="test-pkg", skill_dir=skill_dir)


def _read_events() -> list[dict]:
    ef = events_file()
    if not ef.exists():
        return []
    return [json.loads(line) for line in ef.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# skills.install_skills
# ---------------------------------------------------------------------------


class TestInstallSkillsLedger:

    def test_install_logs_skill_link(self, skills_dir, src):
        from spindle.skills import install_skills
        spec = _make_skill(src, "sample-grill")
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            with mock.patch("spindle.active.source_dir", return_value=src):
                install_skills()
        events = _read_events()
        assert len(events) == 1
        ev = events[0]
        assert ev["kind"] == "skill_link"
        assert "sample-grill" in ev["skills_linked"]

    def test_install_includes_distribution(self, skills_dir, src):
        from spindle.skills import install_skills
        spec = _make_skill(src, "sample-grill")
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            with mock.patch("spindle.active.source_dir", return_value=src):
                install_skills(distribution="spindle-sample")
        events = _read_events()
        assert events[0]["distribution"] == "spindle-sample"

    def test_install_dry_run_does_not_log(self, skills_dir, src):
        from spindle.skills import install_skills
        spec = _make_skill(src, "sample-grill")
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            with mock.patch("spindle.active.source_dir", return_value=src):
                install_skills(dry_run=True)
        assert _read_events() == []

    def test_install_skipped_does_not_log(self, skills_dir, src):
        from spindle.skills import install_skills
        spec = _make_skill(src, "sample-grill")
        (skills_dir / "sample-grill").symlink_to(spec.skill_dir)
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            with mock.patch("spindle.active.source_dir", return_value=src):
                install_skills()  # all skipped:already-current
        assert _read_events() == []

    def test_update_also_logs(self, skills_dir, src):
        from spindle.skills import install_skills
        spec = _make_skill(src, "sample-grill")
        old_target = src / "old"
        old_target.mkdir()
        (skills_dir / "sample-grill").symlink_to(old_target)
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            with mock.patch("spindle.active.source_dir", return_value=src):
                install_skills()
        events = _read_events()
        assert events[0]["kind"] == "skill_link"
        assert "sample-grill" in events[0]["skills_linked"]


# ---------------------------------------------------------------------------
# skills.uninstall_skills
# ---------------------------------------------------------------------------


class TestUninstallSkillsLedger:

    def test_uninstall_logs_skill_unlink(self, skills_dir, src):
        from spindle.skills import uninstall_skills
        spec = _make_skill(src, "sample-grill")
        (skills_dir / "sample-grill").symlink_to(spec.skill_dir)
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            uninstall_skills()
        events = _read_events()
        assert len(events) == 1
        ev = events[0]
        assert ev["kind"] == "skill_unlink"
        assert "sample-grill" in ev["skills_removed"]

    def test_uninstall_dry_run_does_not_log(self, skills_dir, src):
        from spindle.skills import uninstall_skills
        spec = _make_skill(src, "sample-grill")
        (skills_dir / "sample-grill").symlink_to(spec.skill_dir)
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            uninstall_skills(dry_run=True)
        assert _read_events() == []

    def test_uninstall_not_installed_does_not_log(self, skills_dir, src):
        from spindle.skills import uninstall_skills
        spec = _make_skill(src, "sample-grill")
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            uninstall_skills()  # skill not installed → skipped
        assert _read_events() == []


# ---------------------------------------------------------------------------
# preempt / unpreempt
# ---------------------------------------------------------------------------


_TEST_SNIPPET = "<!-- spindle:preempt:begin -->\ntest body\n<!-- spindle:preempt:end -->\n"


class TestPreemptLedger:

    @pytest.fixture
    def claude_md(self, tmp_path, monkeypatch):
        md = tmp_path / "CLAUDE.md"
        monkeypatch.setattr("spindle.preempt.claude_md_path", lambda: md)
        monkeypatch.setattr("spindle.preempt._load_snippet", lambda: _TEST_SNIPPET)
        return md

    def test_preempt_logs_add(self, claude_md):
        from spindle.preempt import preempt
        preempt()
        events = _read_events()
        assert len(events) == 1
        assert events[0]["kind"] == "preempt"
        assert events[0]["action"] == "add"

    def test_preempt_already_present_does_not_log(self, claude_md):
        from spindle.preempt import preempt
        preempt()
        preempt()  # second call → already-present
        events = _read_events()
        assert len(events) == 1  # only one event from the first call

    def test_unpreempt_logs_remove(self, claude_md):
        from spindle.preempt import preempt, unpreempt
        preempt()
        unpreempt()
        events = _read_events()
        assert events[-1]["kind"] == "preempt"
        assert events[-1]["action"] == "remove"

    def test_unpreempt_not_present_does_not_log(self, claude_md):
        from spindle.preempt import unpreempt
        unpreempt()  # → not-present
        assert _read_events() == []
