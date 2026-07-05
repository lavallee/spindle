"""Tests for legacy shim flag in skill installation.

The legacy shim flag can create private-layer transition aliases by mapping
one configured skill-name prefix to another.
"""

import os
from pathlib import Path
from unittest import mock

import pytest

from spindle.models import SkillSpec
from spindle.skills import (
    _create_or_update_alias,
    _get_legacy_alias_name,
    install_skills,
    uninstall_skills,
)


class TestLegacyAliasNameMapping:
    """Test configured prefix alias mapping."""

    def test_configured_mapping(self, monkeypatch):
        """sample-* names should map to spindle-* aliases when configured."""
        monkeypatch.setenv("SPINDLE_LEGACY_ALIAS_FROM", "sample-")
        monkeypatch.setenv("SPINDLE_LEGACY_ALIAS_TO", "spindle-")
        assert _get_legacy_alias_name("sample-grill") == "spindle-grill"
        assert _get_legacy_alias_name("sample-planning") == "spindle-planning"
        assert _get_legacy_alias_name("sample-review-eng") == "spindle-review-eng"

    def test_unconfigured_names_no_mapping(self):
        """Without configured prefixes, names should return None."""
        assert _get_legacy_alias_name("sample-grill") is None
        assert _get_legacy_alias_name("spindle-grill") is None
        assert _get_legacy_alias_name("some-skill") is None
        assert _get_legacy_alias_name("custom-tool") is None

    def test_prefix_only_replaces_first_occurrence(self, monkeypatch):
        """Only the first 'sample-' prefix should be replaced."""
        monkeypatch.setenv("SPINDLE_LEGACY_ALIAS_FROM", "sample-")
        monkeypatch.setenv("SPINDLE_LEGACY_ALIAS_TO", "spindle-")
        # If a skill were named "sample-sample-something" (unlikely but defensive)
        assert _get_legacy_alias_name("sample-sample-test") == "spindle-sample-test"


class TestCreateOrUpdateAlias:
    """Test the alias symlink creation and update logic."""

    def test_create_new_alias_symlink(self, tmp_path):
        """Should create a new alias symlink."""
        target_link = tmp_path / "target_skill"
        target_link.mkdir()

        alias_link = tmp_path / "alias_skill"
        results: list[tuple[str, str]] = []

        _create_or_update_alias(alias_link, target_link, "alias_skill", False, results)

        assert alias_link.is_symlink()
        assert os.readlink(alias_link) == str(target_link)
        assert ("alias_skill (alias)", "installed") in results

    def test_update_existing_alias_symlink(self, tmp_path):
        """Should update an existing alias symlink if it points elsewhere."""
        target_link = tmp_path / "target_skill"
        target_link.mkdir()
        old_target = tmp_path / "old_target"
        old_target.mkdir()

        alias_link = tmp_path / "alias_skill"
        alias_link.symlink_to(old_target)

        results: list[tuple[str, str]] = []
        _create_or_update_alias(alias_link, target_link, "alias_skill", False, results)

        assert alias_link.is_symlink()
        assert os.readlink(alias_link) == str(target_link)
        assert ("alias_skill (alias)", "updated") in results

    def test_skip_alias_already_current(self, tmp_path):
        """Should skip updating an alias that's already correct."""
        target_link = tmp_path / "target_skill"
        target_link.mkdir()

        alias_link = tmp_path / "alias_skill"
        alias_link.symlink_to(target_link)

        results: list[tuple[str, str]] = []
        _create_or_update_alias(alias_link, target_link, "alias_skill", False, results)

        assert ("alias_skill (alias)", "skipped:already-current") in results

    def test_skip_existing_non_symlink(self, tmp_path):
        """Should skip if alias path contains a real file."""
        target_link = tmp_path / "target_skill"
        target_link.mkdir()

        alias_link = tmp_path / "alias_skill"
        alias_link.write_text("real file")

        results: list[tuple[str, str]] = []
        _create_or_update_alias(alias_link, target_link, "alias_skill", False, results)

        assert not alias_link.is_symlink()
        assert ("alias_skill (alias)", "skipped:exists-not-spindle") in results

    def test_dry_run_no_actual_creation(self, tmp_path):
        """Dry run should not create actual symlinks."""
        target_link = tmp_path / "target_skill"
        target_link.mkdir()

        alias_link = tmp_path / "alias_skill"
        results: list[tuple[str, str]] = []

        _create_or_update_alias(alias_link, target_link, "alias_skill", True, results)

        assert not alias_link.exists()
        assert ("alias_skill (alias)", "installed") in results


def _spec(name: str, skill_dir: Path) -> SkillSpec:
    return SkillSpec(name=name, package="sample-test", skill_dir=skill_dir)


class TestInstallWithLegacyShim:
    """Test the install_skills function with legacy_shim flag."""

    @mock.patch("spindle.skills.discover_skills")
    def test_install_without_legacy_shim(self, mock_discover, tmp_path):
        """Without legacy_shim, no aliases should be created."""
        skill_dir = tmp_path / "skills" / "spindle-grill"
        skill_dir.mkdir(parents=True)
        mock_discover.return_value = [_spec("spindle-grill", skill_dir)]

        with mock.patch("spindle.skills.claude_skills_dir", return_value=tmp_path / "installed"):
            install_skills(legacy_shim=False)

        installed_skills = list((tmp_path / "installed").glob("*"))
        assert len(installed_skills) == 1
        assert installed_skills[0].name == "spindle-grill"

    @mock.patch("spindle.skills.discover_skills")
    def test_install_with_legacy_shim_mapped_skills(self, mock_discover, tmp_path, monkeypatch):
        """With legacy_shim and sample-* skills, aliases should be created."""
        monkeypatch.setenv("SPINDLE_LEGACY_ALIAS_FROM", "sample-")
        monkeypatch.setenv("SPINDLE_LEGACY_ALIAS_TO", "spindle-")
        skill_dir = tmp_path / "skills" / "sample-grill"
        skill_dir.mkdir(parents=True)
        mock_discover.return_value = [_spec("sample-grill", skill_dir)]

        with mock.patch("spindle.skills.claude_skills_dir", return_value=tmp_path / "installed"):
            install_skills(legacy_shim=True)

        installed_dir = tmp_path / "installed"

        assert (installed_dir / "sample-grill").exists()
        assert (installed_dir / "spindle-grill").exists()

        assert os.readlink(installed_dir / "spindle-grill") == str(installed_dir / "sample-grill")

    @mock.patch("spindle.skills.discover_skills")
    def test_install_with_legacy_shim_unmapped_skills(self, mock_discover, tmp_path, monkeypatch):
        """With legacy_shim but spindle-* skills, no aliases needed (current behavior)."""
        monkeypatch.setenv("SPINDLE_LEGACY_ALIAS_FROM", "sample-")
        monkeypatch.setenv("SPINDLE_LEGACY_ALIAS_TO", "spindle-")
        skill_dir = tmp_path / "skills" / "spindle-grill"
        skill_dir.mkdir(parents=True)
        mock_discover.return_value = [_spec("spindle-grill", skill_dir)]

        with mock.patch("spindle.skills.claude_skills_dir", return_value=tmp_path / "installed"):
            install_skills(legacy_shim=True)

        installed_dir = tmp_path / "installed"

        assert (installed_dir / "spindle-grill").exists()
        assert not (installed_dir / "spindle-spindle-grill").exists()


class TestUninstallWithLegacyShim:
    """Test that uninstall_skills properly removes legacy alias symlinks."""

    @mock.patch("spindle.skills.discover_skills")
    def test_uninstall_removes_aliases(self, mock_discover, tmp_path, monkeypatch):
        """Uninstall should remove both main skill and alias symlinks."""
        monkeypatch.setenv("SPINDLE_LEGACY_ALIAS_FROM", "sample-")
        monkeypatch.setenv("SPINDLE_LEGACY_ALIAS_TO", "spindle-")
        skills_dir = tmp_path / "skills"
        skill_dir = skills_dir / "sample-grill"
        skill_dir.mkdir(parents=True)
        mock_discover.return_value = [_spec("sample-grill", skill_dir)]

        installed_dir = tmp_path / "installed"
        installed_dir.mkdir()

        main_link = installed_dir / "sample-grill"
        main_link.symlink_to(skill_dir)

        alias_link = installed_dir / "spindle-grill"
        alias_link.symlink_to(main_link)

        with mock.patch("spindle.skills.claude_skills_dir", return_value=installed_dir):
            results = uninstall_skills()

        assert not main_link.exists()
        assert not alias_link.exists()

        result_dict = {name: action for name, action in results}
        assert result_dict.get("sample-grill") == "removed"
        assert result_dict.get("spindle-grill (alias)") == "removed"
