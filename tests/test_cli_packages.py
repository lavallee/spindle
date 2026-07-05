"""Tests for `spindle package list` and `spindle package show` CLI subcommands."""

from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from spindle.cli import main
from spindle.models import PackageMetadata, Source


def _fake_packages():
    return [
        PackageMetadata(
            name="sample-alpha",
            version="1.0.0",
            distribution="spindle-sample",
            skills=["alpha"],
            capabilities=["cap-a"],
            sources=[
                Source(
                    peer="someone/repo",
                    url="https://example.com",
                    transposed_at=datetime.date(2026, 1, 15),
                    notes="borrowed",
                )
            ],
            package_dir=Path("/fake/sample-alpha"),
        ),
        PackageMetadata(
            name="sample-beta",
            version="2.0.0",
            distribution="spindle-sample",
            skills=["beta-one", "beta-two"],
            capabilities=[],
            sources=[],
            package_dir=Path("/fake/sample-beta"),
        ),
    ]


class TestPackageList:
    def test_list_exit_zero(self, capsys):
        with patch("spindle.packages.list_installed_packages", return_value=_fake_packages()):
            rc = main(["package", "list"])
        assert rc == 0

    def test_list_shows_names(self, capsys):
        with patch("spindle.packages.list_installed_packages", return_value=_fake_packages()):
            main(["package", "list"])
        out = capsys.readouterr().out
        assert "sample-alpha" in out
        assert "sample-beta" in out

    def test_list_shows_version(self, capsys):
        with patch("spindle.packages.list_installed_packages", return_value=_fake_packages()):
            main(["package", "list"])
        out = capsys.readouterr().out
        assert "1.0.0" in out
        assert "2.0.0" in out

    def test_list_shows_skills(self, capsys):
        with patch("spindle.packages.list_installed_packages", return_value=_fake_packages()):
            main(["package", "list"])
        out = capsys.readouterr().out
        assert "alpha" in out
        assert "beta-one" in out

    def test_list_empty(self, capsys):
        with patch("spindle.packages.list_installed_packages", return_value=[]):
            rc = main(["package", "list"])
        assert rc == 0
        assert "no spindle packages" in capsys.readouterr().out

    def test_list_sample_package_live(self, capsys):
        """Integration: the sample package is visible via real discovery."""
        rc = main(["package", "list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "sample-planning" in out


class TestPackageShow:
    def test_show_known_exits_zero(self, capsys):
        pkg = _fake_packages()[0]
        with patch("spindle.packages.read_package_metadata", return_value=pkg):
            rc = main(["package", "show", "sample-alpha"])
        assert rc == 0

    def test_show_prints_fields(self, capsys):
        pkg = _fake_packages()[0]
        with patch("spindle.packages.read_package_metadata", return_value=pkg):
            main(["package", "show", "sample-alpha"])
        out = capsys.readouterr().out
        assert "sample-alpha" in out
        assert "1.0.0" in out
        assert "spindle-sample" in out
        assert "alpha" in out
        assert "cap-a" in out

    def test_show_prints_source(self, capsys):
        pkg = _fake_packages()[0]
        with patch("spindle.packages.read_package_metadata", return_value=pkg):
            main(["package", "show", "sample-alpha"])
        out = capsys.readouterr().out
        assert "someone/repo" in out
        assert "2026-01-15" in out

    def test_show_unknown_exits_nonzero(self, capsys):
        with patch("spindle.packages.read_package_metadata", return_value=None):
            rc = main(["package", "show", "nonexistent"])
        assert rc != 0
        assert "nonexistent" in capsys.readouterr().err

    def test_show_sample_planning_live(self, capsys):
        """Integration: `spindle package show sample-planning` works against real install."""
        rc = main(["package", "show", "sample-planning"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "sample-planning" in out
        assert "requirements-clarification" in out
