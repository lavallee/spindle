"""Tests for the skill installer: install, uninstall, status, idempotency, prune.

Fixture overrides CLAUDE_SKILLS_DIR so no test touches ~/.claude/skills/.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from spindle.models import SkillSpec
from spindle.skills import install_skills, uninstall_skills, status_skills, prune_legacy_symlinks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skill(base: Path, name: str, pkg: str = "test-pkg") -> SkillSpec:
    """Create a skill source directory with SKILL.md and return a SkillSpec."""
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\n---\n# {name}\n")
    return SkillSpec(name=name, package=pkg, skill_dir=skill_dir)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_spindle_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "spindle-state"))


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    """Isolated target skills dir; overrides CLAUDE_SKILLS_DIR for each test."""
    sd = tmp_path / "skills"
    sd.mkdir()
    monkeypatch.setenv("CLAUDE_SKILLS_DIR", str(sd))
    return sd


@pytest.fixture
def src(tmp_path):
    """Temp directory to hold fake skill source trees."""
    d = tmp_path / "src"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# Install round-trip
# ---------------------------------------------------------------------------


class TestInstallRoundTrip:

    def test_creates_symlink(self, skills_dir, src):
        spec = _make_skill(src, "sample-grill")
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            with mock.patch("spindle.active.source_dir", return_value=src):
                results = install_skills()
        link = skills_dir / "sample-grill"
        assert link.is_symlink()
        assert os.readlink(link) == str(spec.skill_dir)
        assert ("sample-grill", "installed") in results

    def test_creates_skills_dir_if_missing(self, tmp_path, monkeypatch, src):
        sd = tmp_path / "new-skills"
        # Do NOT pre-create sd — install_skills should mkdir it
        monkeypatch.setenv("CLAUDE_SKILLS_DIR", str(sd))
        spec = _make_skill(src, "sample-plan")
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            with mock.patch("spindle.active.source_dir", return_value=src):
                install_skills()
        assert (sd / "sample-plan").is_symlink()

    def test_multiple_skills_all_linked(self, skills_dir, src):
        specs = [_make_skill(src, n) for n in ["sample-grill", "sample-orient", "sample-review"]]
        with mock.patch("spindle.skills.discover_skills", return_value=specs):
            with mock.patch("spindle.active.source_dir", return_value=src):
                results = install_skills()
        actions = dict(results)
        for name in ["sample-grill", "sample-orient", "sample-review"]:
            assert (skills_dir / name).is_symlink()
            assert actions[name] == "installed"

    def test_dry_run_does_not_create_link(self, skills_dir, src):
        spec = _make_skill(src, "sample-grill")
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            with mock.patch("spindle.active.source_dir", return_value=src):
                results = install_skills(dry_run=True)
        assert not (skills_dir / "sample-grill").exists()
        assert ("sample-grill", "installed") in results


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:

    def test_second_install_skips(self, skills_dir, src):
        spec = _make_skill(src, "sample-grill")
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            with mock.patch("spindle.active.source_dir", return_value=src):
                install_skills()
                results = install_skills()
        assert ("sample-grill", "skipped:already-current") in results

    def test_updated_when_link_points_elsewhere(self, skills_dir, src):
        spec = _make_skill(src, "sample-grill")
        old_target = src / "old-sample-grill"
        old_target.mkdir()
        link = skills_dir / "sample-grill"
        link.symlink_to(old_target)
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            with mock.patch("spindle.active.source_dir", return_value=src):
                results = install_skills()
        assert ("sample-grill", "updated") in results
        assert os.readlink(link) == str(spec.skill_dir)

    def test_skips_non_ivy_real_file(self, skills_dir, src):
        spec = _make_skill(src, "sample-grill")
        (skills_dir / "sample-grill").mkdir()
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            with mock.patch("spindle.active.source_dir", return_value=src):
                results = install_skills()
        assert ("sample-grill", "skipped:exists-not-spindle") in results


# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------


class TestUninstall:

    def test_removes_installed_symlink(self, skills_dir, src):
        spec = _make_skill(src, "sample-grill")
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            with mock.patch("spindle.active.source_dir", return_value=src):
                install_skills()
            results = uninstall_skills()
        assert not (skills_dir / "sample-grill").exists()
        assert ("sample-grill", "removed") in results

    def test_uninstall_not_installed_reports_skipped(self, skills_dir, src):
        spec = _make_skill(src, "sample-grill")
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            results = uninstall_skills()
        assert ("sample-grill", "skipped:not-installed") in results
        assert not (skills_dir / "sample-grill").exists()

    def test_uninstall_skips_foreign_symlink(self, skills_dir, src):
        spec = _make_skill(src, "sample-grill")
        elsewhere = src / "elsewhere"
        elsewhere.mkdir()
        link = skills_dir / "sample-grill"
        link.symlink_to(elsewhere)
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            results = uninstall_skills()
        assert link.is_symlink()
        assert ("sample-grill", "skipped:not-spindle-owned") in results

    def test_dry_run_does_not_remove(self, skills_dir, src):
        spec = _make_skill(src, "sample-grill")
        link = skills_dir / "sample-grill"
        link.symlink_to(spec.skill_dir)
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            results = uninstall_skills(dry_run=True)
        assert link.is_symlink()
        assert ("sample-grill", "removed") in results

    def test_uninstall_removes_legacy_alias_too(self, skills_dir, src, monkeypatch):
        monkeypatch.setenv("SPINDLE_LEGACY_ALIAS_FROM", "sample-")
        monkeypatch.setenv("SPINDLE_LEGACY_ALIAS_TO", "spindle-")
        spec = _make_skill(src, "sample-grill")
        main_link = skills_dir / "sample-grill"
        main_link.symlink_to(spec.skill_dir)
        alias_link = skills_dir / "spindle-grill"
        alias_link.symlink_to(main_link)
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            results = uninstall_skills()
        assert not alias_link.is_symlink()
        assert ("spindle-grill (alias)", "removed") in results

    def test_missing_skills_dir_returns_empty(self, tmp_path, monkeypatch, src):
        monkeypatch.setenv("CLAUDE_SKILLS_DIR", str(tmp_path / "no-such-dir"))
        spec = _make_skill(src, "sample-grill")
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            results = uninstall_skills()
        assert results == []


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


class TestStatus:

    def test_installed(self, skills_dir, src):
        spec = _make_skill(src, "sample-grill")
        (skills_dir / "sample-grill").symlink_to(spec.skill_dir)
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            results = status_skills()
        assert ("sample-grill", "installed") in results

    def test_not_installed(self, skills_dir, src):
        spec = _make_skill(src, "sample-grill")
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            results = status_skills()
        assert ("sample-grill", "not-installed") in results

    def test_conflict_real_file(self, skills_dir, src):
        spec = _make_skill(src, "sample-grill")
        (skills_dir / "sample-grill").mkdir()
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            results = status_skills()
        assert ("sample-grill", "conflict:real-file") in results

    def test_conflict_other_symlink(self, skills_dir, src):
        spec = _make_skill(src, "sample-grill")
        elsewhere = src / "elsewhere"
        elsewhere.mkdir()
        (skills_dir / "sample-grill").symlink_to(elsewhere)
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            results = status_skills()
        assert ("sample-grill", "conflict:other-symlink") in results

    def test_stale_link(self, skills_dir, src):
        spec_a = _make_skill(src, "sample-grill")
        spec_b = _make_skill(src, "sample-orient")
        # sample-grill's link points at spec_b's dir (a different owned target)
        (skills_dir / "sample-grill").symlink_to(spec_b.skill_dir)
        with mock.patch("spindle.skills.discover_skills", return_value=[spec_a, spec_b]):
            results = status_skills()
        assert ("sample-grill", "installed:stale-link") in results

    def test_alias_installed(self, skills_dir, src, monkeypatch):
        monkeypatch.setenv("SPINDLE_LEGACY_ALIAS_FROM", "sample-")
        monkeypatch.setenv("SPINDLE_LEGACY_ALIAS_TO", "spindle-")
        spec = _make_skill(src, "sample-grill")
        main_link = skills_dir / "sample-grill"
        main_link.symlink_to(spec.skill_dir)
        alias_link = skills_dir / "spindle-grill"
        alias_link.symlink_to(main_link)
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            results = status_skills()
        assert ("spindle-grill (alias)", "installed") in results

    def test_status_after_install(self, skills_dir, src):
        spec = _make_skill(src, "sample-grill")
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            with mock.patch("spindle.active.source_dir", return_value=src):
                install_skills()
            results = status_skills()
        assert ("sample-grill", "installed") in results

    def test_status_after_uninstall(self, skills_dir, src):
        spec = _make_skill(src, "sample-grill")
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            with mock.patch("spindle.active.source_dir", return_value=src):
                install_skills()
            uninstall_skills()
            results = status_skills()
        assert ("sample-grill", "not-installed") in results


# ---------------------------------------------------------------------------
# Legacy prune (via install_skills and directly)
# ---------------------------------------------------------------------------


class TestLegacyPrune:

    def test_install_prunes_dead_legacy_link(self, skills_dir, src):
        dist_root = src / "dist"
        dead_link = skills_dir / "spindle-dead"
        dead_link.symlink_to(dist_root / "skills" / "spindle-dead")
        spec = _make_skill(src, "sample-grill")
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            with mock.patch("spindle.active.source_dir", return_value=dist_root):
                results = install_skills()
        assert not dead_link.is_symlink()
        assert ("spindle-dead", "pruned") in results

    def test_install_dry_run_does_not_prune(self, skills_dir, src):
        dist_root = src / "dist"
        dead_link = skills_dir / "spindle-dead"
        dead_link.symlink_to(dist_root / "skills" / "spindle-dead")
        spec = _make_skill(src, "sample-grill")
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            with mock.patch("spindle.active.source_dir", return_value=dist_root):
                results = install_skills(dry_run=True)
        assert dead_link.is_symlink()
        assert ("spindle-dead", "pruned") in results

    def test_prune_alone_removes_dead_link(self, skills_dir, src):
        dist_root = src / "dist"
        dead_link = skills_dir / "spindle-plan"
        dead_link.symlink_to(dist_root / "skills" / "spindle-plan")
        with mock.patch("spindle.skills.claude_skills_dir", return_value=skills_dir):
            with mock.patch("spindle.active.source_dir", return_value=dist_root):
                results = prune_legacy_symlinks()
        assert not dead_link.is_symlink()
        assert ("spindle-plan", "pruned") in results

    def test_prune_skips_alive_link(self, skills_dir, src):
        dist_root = src / "dist"
        target = dist_root / "skills" / "spindle-plan"
        target.mkdir(parents=True)
        link = skills_dir / "spindle-plan"
        link.symlink_to(target)
        with mock.patch("spindle.skills.claude_skills_dir", return_value=skills_dir):
            with mock.patch("spindle.active.source_dir", return_value=dist_root):
                results = prune_legacy_symlinks()
        assert link.is_symlink()
        assert ("spindle-plan", "skipped:alive") in results

    def test_legacy_shim_creates_alias(self, skills_dir, src, monkeypatch):
        monkeypatch.setenv("SPINDLE_LEGACY_ALIAS_FROM", "sample-")
        monkeypatch.setenv("SPINDLE_LEGACY_ALIAS_TO", "spindle-")
        spec = _make_skill(src, "sample-grill")
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            with mock.patch("spindle.active.source_dir", return_value=src):
                results = install_skills(legacy_shim=True)
        alias = skills_dir / "spindle-grill"
        assert alias.is_symlink()
        assert ("spindle-grill (alias)", "installed") in results

    def test_legacy_shim_idempotent(self, skills_dir, src, monkeypatch):
        monkeypatch.setenv("SPINDLE_LEGACY_ALIAS_FROM", "sample-")
        monkeypatch.setenv("SPINDLE_LEGACY_ALIAS_TO", "spindle-")
        spec = _make_skill(src, "sample-grill")
        with mock.patch("spindle.skills.discover_skills", return_value=[spec]):
            with mock.patch("spindle.active.source_dir", return_value=src):
                install_skills(legacy_shim=True)
                results = install_skills(legacy_shim=True)
        assert ("spindle-grill (alias)", "skipped:already-current") in results
