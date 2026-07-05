"""Tests for `spindle capability list` and `spindle capability show` CLI subcommands."""

from __future__ import annotations

import datetime
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
            capabilities=["cap-a", "cap-b"],
            sources=[
                Source(
                    peer="peer-one",
                    url="https://example.com",
                    transposed_at=datetime.date(2026, 1, 15),
                    notes="note on alpha",
                )
            ],
            package_dir="/fake/sample-alpha",
        ),
        PackageMetadata(
            name="sample-beta",
            version="2.0.0",
            distribution="spindle-sample",
            skills=["beta"],
            capabilities=["cap-b", "cap-c"],
            sources=[
                Source(
                    peer="peer-two",
                    url="https://example.org",
                    transposed_at=datetime.date(2026, 2, 20),
                    notes="",
                )
            ],
            package_dir="/fake/sample-beta",
        ),
    ]


class TestCapabilityList:
    def test_list_exit_zero(self, capsys):
        with patch("spindle.capabilities.list_installed_packages", return_value=_fake_packages()):
            rc = main(["capability", "list"])
        assert rc == 0

    def test_list_shows_capability_names(self, capsys):
        with patch("spindle.capabilities.list_installed_packages", return_value=_fake_packages()):
            main(["capability", "list"])
        out = capsys.readouterr().out
        assert "cap-a" in out
        assert "cap-b" in out
        assert "cap-c" in out

    def test_list_shows_packages(self, capsys):
        with patch("spindle.capabilities.list_installed_packages", return_value=_fake_packages()):
            main(["capability", "list"])
        out = capsys.readouterr().out
        assert "sample-alpha" in out
        assert "sample-beta" in out

    def test_list_shows_capability_to_packages_mapping(self, capsys):
        with patch("spindle.capabilities.list_installed_packages", return_value=_fake_packages()):
            main(["capability", "list"])
        out = capsys.readouterr().out
        lines = out.strip().split("\n")
        cap_b_line = [l for l in lines if "cap-b" in l][0]
        assert "sample-alpha" in cap_b_line
        assert "sample-beta" in cap_b_line

    def test_list_empty(self, capsys):
        with patch("spindle.capabilities.list_installed_packages", return_value=[]):
            rc = main(["capability", "list"])
        assert rc == 0
        assert "no capabilities" in capsys.readouterr().out

    def test_list_sample_package_capabilities_live(self, capsys):
        """Integration: the real sample-* packages have capabilities."""
        rc = main(["capability", "list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "requirements-clarification" in out
        assert "sample-planning" in out


class TestCapabilityShow:
    def test_show_known_exits_zero(self, capsys):
        with patch("spindle.capabilities.list_installed_packages", return_value=_fake_packages()):
            rc = main(["capability", "show", "cap-a"])
        assert rc == 0

    def test_show_prints_capability_name(self, capsys):
        with patch("spindle.capabilities.list_installed_packages", return_value=_fake_packages()):
            main(["capability", "show", "cap-a"])
        out = capsys.readouterr().out
        assert "cap-a" in out

    def test_show_prints_packages(self, capsys):
        with patch("spindle.capabilities.list_installed_packages", return_value=_fake_packages()):
            main(["capability", "show", "cap-b"])
        out = capsys.readouterr().out
        assert "sample-alpha" in out
        assert "sample-beta" in out

    def test_show_prints_source_fields(self, capsys):
        with patch("spindle.capabilities.list_installed_packages", return_value=_fake_packages()):
            main(["capability", "show", "cap-a"])
        out = capsys.readouterr().out
        assert "peer-one" in out
        assert "https://example.com" in out
        assert "2026-01-15" in out
        assert "note on alpha" in out

    def test_show_multiple_sources(self, capsys):
        with patch("spindle.capabilities.list_installed_packages", return_value=_fake_packages()):
            main(["capability", "show", "cap-b"])
        out = capsys.readouterr().out
        assert "peer-one" in out
        assert "peer-two" in out
        assert "example.com" in out
        assert "example.org" in out

    def test_show_source_with_empty_notes(self, capsys):
        with patch("spindle.capabilities.list_installed_packages", return_value=_fake_packages()):
            main(["capability", "show", "cap-c"])
        out = capsys.readouterr().out
        assert "peer-two" in out
        assert "example.org" in out
        assert "2026-02-20" in out

    def test_show_unknown_exits_nonzero(self, capsys):
        with patch("spindle.capabilities.list_installed_packages", return_value=_fake_packages()):
            rc = main(["capability", "show", "nonexistent"])
        assert rc != 0
        assert "nonexistent" in capsys.readouterr().err

    def test_show_sample_capability_live(self, capsys):
        """Integration: can show details for a real sample capability."""
        rc = main(["capability", "show", "requirements-clarification"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "requirements-clarification" in out
        assert "sample-planning" in out
