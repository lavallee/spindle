"""Tests for `spindle dist list` and `spindle dist show` CLI subcommands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from spindle.cli import main
from spindle.models import DistributionMetadata


def _fake_dists():
    return [
        DistributionMetadata(
            name="alpha-dist",
            version="1.0.0",
            display_name="Alpha Distribution",
            description="First test distribution.",
            source_dir=Path("/fake/alpha"),
            preempt_snippet=Path("/fake/alpha/preempt.md"),
            home_url="https://alpha.example.com",
            packages=["sample-one", "sample-two", "sample-three"],
        ),
        DistributionMetadata(
            name="beta-dist",
            version="2.3.0",
            display_name="Beta Distribution",
            description="Second test distribution.",
            source_dir=Path("/fake/beta"),
            preempt_snippet=None,
            home_url=None,
            packages=["sample-x"],
        ),
    ]


class TestDistList:
    def test_list_exit_zero(self, capsys):
        with patch("spindle.distributions.list_installed_distributions", return_value=_fake_dists()):
            rc = main(["dist", "list"])
        assert rc == 0

    def test_list_shows_names(self, capsys):
        with patch("spindle.distributions.list_installed_distributions", return_value=_fake_dists()):
            main(["dist", "list"])
        out = capsys.readouterr().out
        assert "alpha-dist" in out
        assert "beta-dist" in out

    def test_list_shows_versions(self, capsys):
        with patch("spindle.distributions.list_installed_distributions", return_value=_fake_dists()):
            main(["dist", "list"])
        out = capsys.readouterr().out
        assert "1.0.0" in out
        assert "2.3.0" in out

    def test_list_shows_package_count(self, capsys):
        with patch("spindle.distributions.list_installed_distributions", return_value=_fake_dists()):
            main(["dist", "list"])
        out = capsys.readouterr().out
        assert "3 packages" in out
        assert "1 package" in out

    def test_list_empty(self, capsys):
        with patch("spindle.distributions.list_installed_distributions", return_value=[]):
            rc = main(["dist", "list"])
        assert rc == 0
        assert "no spindle distributions" in capsys.readouterr().out

    def test_list_spindle_sample_live(self, capsys):
        """Integration: spindle-sample distribution is visible via real discovery."""
        rc = main(["dist", "list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "spindle-sample" in out


class TestDistShow:
    def test_show_known_exits_zero(self, capsys):
        dist = _fake_dists()[0]
        with patch("spindle.distributions.read_distribution_metadata", return_value=dist):
            rc = main(["dist", "show", "alpha-dist"])
        assert rc == 0

    def test_show_prints_metadata(self, capsys):
        dist = _fake_dists()[0]
        with patch("spindle.distributions.read_distribution_metadata", return_value=dist):
            main(["dist", "show", "alpha-dist"])
        out = capsys.readouterr().out
        assert "alpha-dist" in out
        assert "1.0.0" in out
        assert "Alpha Distribution" in out
        assert "First test distribution." in out
        assert "https://alpha.example.com" in out
        assert "/fake/alpha" in out

    def test_show_prints_pinned_packages(self, capsys):
        dist = _fake_dists()[0]
        with patch("spindle.distributions.read_distribution_metadata", return_value=dist):
            main(["dist", "show", "alpha-dist"])
        out = capsys.readouterr().out
        assert "sample-one" in out
        assert "sample-two" in out
        assert "sample-three" in out

    def test_show_none_fields_handled(self, capsys):
        dist = _fake_dists()[1]
        with patch("spindle.distributions.read_distribution_metadata", return_value=dist):
            rc = main(["dist", "show", "beta-dist"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "(none)" in out

    def test_show_unknown_exits_nonzero(self, capsys):
        with patch("spindle.distributions.read_distribution_metadata", return_value=None):
            rc = main(["dist", "show", "nonexistent"])
        assert rc != 0
        assert "nonexistent" in capsys.readouterr().err

    def test_show_spindle_sample_live(self, capsys):
        """Integration: `spindle dist show spindle-sample` works against real install."""
        rc = main(["dist", "show", "spindle-sample"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "spindle-sample" in out
