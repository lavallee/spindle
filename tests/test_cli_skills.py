"""Tests for `spindle skill list` and `spindle skill show` CLI subcommands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from spindle.cli import main
from spindle.models import SkillSpec


def _fake_skills():
    return [
        SkillSpec(
            name="sample-grill",
            package="sample-grill",
            skill_dir=Path("/fake/sample-grill"),
        ),
        SkillSpec(
            name="sample-architect",
            package="sample-planning",
            skill_dir=Path("/fake/sample-planning/architect"),
        ),
        SkillSpec(
            name="sample-itemize",
            package="sample-planning",
            skill_dir=Path("/fake/sample-planning/itemize"),
        ),
    ]


class TestSkillList:
    def test_list_exit_zero(self, capsys):
        with patch("spindle.skills.discover_skills", return_value=_fake_skills()):
            rc = main(["skill", "list"])
        assert rc == 0

    def test_list_shows_names(self, capsys):
        with patch("spindle.skills.discover_skills", return_value=_fake_skills()):
            main(["skill", "list"])
        out = capsys.readouterr().out
        assert "sample-grill" in out
        assert "sample-architect" in out
        assert "sample-itemize" in out

    def test_list_shows_packages(self, capsys):
        with patch("spindle.skills.discover_skills", return_value=_fake_skills()):
            main(["skill", "list"])
        out = capsys.readouterr().out
        assert "sample-grill" in out
        assert "sample-planning" in out

    def test_list_shows_skill_dirs(self, capsys):
        with patch("spindle.skills.discover_skills", return_value=_fake_skills()):
            main(["skill", "list"])
        out = capsys.readouterr().out
        assert "/fake/sample-grill" in out
        assert "/fake/sample-planning" in out

    def test_list_empty(self, capsys):
        with patch("spindle.skills.discover_skills", return_value=[]):
            rc = main(["skill", "list"])
        assert rc == 0
        assert "no spindle skills" in capsys.readouterr().out

    def test_list_live(self, capsys):
        """Integration: skill list works against real discovery."""
        rc = main(["skill", "list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "clarify" in out
        assert "sample-planning" in out


class TestSkillShow:
    def test_show_known_exits_zero(self, capsys):
        skill = _fake_skills()[0]
        with patch("spindle.skills.read_skill_metadata", return_value=({}, skill)):
            rc = main(["skill", "show", "sample-grill"])
        assert rc == 0

    def test_show_prints_name(self, capsys):
        skill = _fake_skills()[0]
        with patch("spindle.skills.read_skill_metadata", return_value=({}, skill)):
            main(["skill", "show", "sample-grill"])
        out = capsys.readouterr().out
        assert "sample-grill" in out

    def test_show_prints_package(self, capsys):
        skill = _fake_skills()[0]
        with patch("spindle.skills.read_skill_metadata", return_value=({}, skill)):
            main(["skill", "show", "sample-grill"])
        out = capsys.readouterr().out
        assert "sample-grill" in out

    def test_show_prints_skill_dir(self, capsys):
        skill = _fake_skills()[0]
        with patch("spindle.skills.read_skill_metadata", return_value=({}, skill)):
            main(["skill", "show", "sample-grill"])
        out = capsys.readouterr().out
        assert "/fake/sample-grill" in out

    def test_show_with_frontmatter(self, capsys):
        skill = _fake_skills()[0]
        fm = {"version": "0.1.0", "description": "Test skill"}
        with patch("spindle.skills.read_skill_metadata", return_value=(fm, skill)):
            main(["skill", "show", "sample-grill"])
        out = capsys.readouterr().out
        assert "version" in out
        assert "0.1.0" in out
        assert "description" in out
        assert "Test skill" in out

    def test_show_unknown_exits_nonzero(self, capsys):
        with patch("spindle.skills.read_skill_metadata", return_value=None):
            rc = main(["skill", "show", "nonexistent"])
        assert rc != 0
        assert "nonexistent" in capsys.readouterr().err

    def test_show_live(self, capsys):
        """Integration: `spindle skill show clarify` works against real discovery."""
        rc = main(["skill", "show", "clarify"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "clarify" in out
        assert "sample-planning" in out
