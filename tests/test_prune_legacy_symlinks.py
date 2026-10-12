"""Tests for prune_legacy_symlinks."""

from pathlib import Path
from unittest import mock

import pytest

from spindle.models import SkillSpec
from spindle.skills import install_skills, prune_legacy_symlinks


@pytest.fixture(autouse=True)
def isolated_spindle_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "spindle-state"))


def _owned_dead_link(skills_dir: Path, dist_root: Path, name: str) -> Path:
    skill_dir = dist_root / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\n---\n")
    spec = SkillSpec(name=name, package="test", skill_dir=skill_dir)
    with (
        mock.patch("spindle.skills.claude_skills_dir", return_value=skills_dir),
        mock.patch("spindle.active.source_dir", return_value=dist_root),
        mock.patch("spindle.skills.discover_skills", return_value=[spec]),
    ):
        install_skills()
    (skill_dir / "SKILL.md").unlink()
    skill_dir.rmdir()
    return skills_dir / name


class TestPruneLegacySymlinks:
    def test_preserves_unowned_dead_legacy_link(self, tmp_path):
        skills_dir = tmp_path / "claude" / "skills"
        skills_dir.mkdir(parents=True)
        dist_root = tmp_path / "repo"
        # Dead link points to the old skills layout: dist_root/skills/spindle-*
        link = skills_dir / "spindle-grill"
        link.symlink_to(dist_root / "skills" / "spindle-grill")

        with (
            mock.patch("spindle.skills.claude_skills_dir", return_value=skills_dir),
            mock.patch("spindle.active.source_dir", return_value=dist_root),
        ):
            results = prune_legacy_symlinks()

        assert link.is_symlink()
        assert ("spindle-grill", "skipped:unverified-ownership") in results

    def test_prunes_dead_owned_legacy_link(self, tmp_path):
        skills_dir = tmp_path / "claude" / "skills"
        skills_dir.mkdir(parents=True)
        dist_root = tmp_path / "repo"
        link = _owned_dead_link(skills_dir, dist_root, "spindle-grill")

        with (
            mock.patch("spindle.skills.claude_skills_dir", return_value=skills_dir),
            mock.patch("spindle.active.source_dir", return_value=dist_root),
        ):
            results = prune_legacy_symlinks()

        assert not link.exists() and not link.is_symlink()
        assert ("spindle-grill", "pruned") in results

    def test_skips_alive_link(self, tmp_path):
        skills_dir = tmp_path / "claude" / "skills"
        skills_dir.mkdir(parents=True)
        dist_root = tmp_path / "repo"
        target = dist_root / "skills" / "spindle-grill"
        target.mkdir(parents=True)
        link = skills_dir / "spindle-grill"
        link.symlink_to(target)

        with (
            mock.patch("spindle.skills.claude_skills_dir", return_value=skills_dir),
            mock.patch("spindle.active.source_dir", return_value=dist_root),
        ):
            results = prune_legacy_symlinks()

        assert link.is_symlink()
        assert ("spindle-grill", "skipped:alive") in results

    def test_skips_dead_link_not_pointing_to_legacy_path(self, tmp_path):
        skills_dir = tmp_path / "claude" / "skills"
        skills_dir.mkdir(parents=True)
        dist_root = tmp_path / "repo"
        # Target under a completely different path
        link = skills_dir / "spindle-other"
        link.symlink_to(tmp_path / "elsewhere" / "spindle-other")

        with (
            mock.patch("spindle.skills.claude_skills_dir", return_value=skills_dir),
            mock.patch("spindle.active.source_dir", return_value=dist_root),
        ):
            results = prune_legacy_symlinks()

        assert link.is_symlink()
        assert ("spindle-other", "skipped:not-legacy") in results

    def test_dry_run_does_not_remove_link(self, tmp_path):
        skills_dir = tmp_path / "claude" / "skills"
        skills_dir.mkdir(parents=True)
        dist_root = tmp_path / "repo"
        link = _owned_dead_link(skills_dir, dist_root, "spindle-plan")

        with (
            mock.patch("spindle.skills.claude_skills_dir", return_value=skills_dir),
            mock.patch("spindle.active.source_dir", return_value=dist_root),
        ):
            results = prune_legacy_symlinks(dry_run=True)

        assert link.is_symlink()
        assert ("spindle-plan", "pruned") in results

    def test_ignores_real_directories(self, tmp_path):
        skills_dir = tmp_path / "claude" / "skills"
        skills_dir.mkdir(parents=True)
        dist_root = tmp_path / "repo"
        (skills_dir / "spindle-real").mkdir()

        with (
            mock.patch("spindle.skills.claude_skills_dir", return_value=skills_dir),
            mock.patch("spindle.active.source_dir", return_value=dist_root),
        ):
            results = prune_legacy_symlinks()

        assert (skills_dir / "spindle-real").exists()
        assert not any(name == "spindle-real" for name, _ in results)

    def test_returns_empty_when_skills_dir_missing(self, tmp_path):
        missing = tmp_path / "no-such-dir"
        dist_root = tmp_path / "repo"

        with (
            mock.patch("spindle.skills.claude_skills_dir", return_value=missing),
            mock.patch("spindle.active.source_dir", return_value=dist_root),
        ):
            results = prune_legacy_symlinks()

        assert results == []

    def test_prunes_multiple_dead_links(self, tmp_path):
        skills_dir = tmp_path / "claude" / "skills"
        skills_dir.mkdir(parents=True)
        dist_root = tmp_path / "repo"
        names = ["spindle-architect", "spindle-compound", "spindle-orient"]
        for name in names:
            (skills_dir / name).symlink_to(dist_root / "skills" / name)

        with (
            mock.patch("spindle.skills.claude_skills_dir", return_value=skills_dir),
            mock.patch("spindle.active.source_dir", return_value=dist_root),
        ):
            results = prune_legacy_symlinks()

        preserved = [
            name for name, action in results if action == "skipped:unverified-ownership"
        ]
        assert set(preserved) == set(names)
        for name in names:
            assert (skills_dir / name).is_symlink()


class TestInstallCallsPrune:
    """install_skills should automatically call prune_legacy_symlinks."""

    @mock.patch("spindle.skills.discover_skills")
    def test_install_preserves_unowned_dead_links(self, mock_discover, tmp_path):
        skills_dir = tmp_path / "claude" / "skills"
        skills_dir.mkdir(parents=True)
        dist_root = tmp_path / "repo"

        dead_link = skills_dir / "spindle-old"
        dead_link.symlink_to(dist_root / "skills" / "spindle-old")

        mock_discover.return_value = []

        with (
            mock.patch("spindle.skills.claude_skills_dir", return_value=skills_dir),
            mock.patch("spindle.active.source_dir", return_value=dist_root),
        ):
            results = install_skills()

        assert dead_link.is_symlink()
        assert ("spindle-old", "skipped:unverified-ownership") in results

    @mock.patch("spindle.skills.discover_skills")
    def test_install_dry_run_does_not_prune(self, mock_discover, tmp_path):
        skills_dir = tmp_path / "claude" / "skills"
        skills_dir.mkdir(parents=True)
        dist_root = tmp_path / "repo"

        dead_link = skills_dir / "spindle-old"
        dead_link.symlink_to(dist_root / "skills" / "spindle-old")

        mock_discover.return_value = []

        with (
            mock.patch("spindle.skills.claude_skills_dir", return_value=skills_dir),
            mock.patch("spindle.active.source_dir", return_value=dist_root),
        ):
            results = install_skills(dry_run=True)

        assert dead_link.is_symlink()
        assert ("spindle-old", "skipped:unverified-ownership") in results
