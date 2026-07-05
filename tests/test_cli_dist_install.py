"""Tests for `spindle dist install` and `spindle dist uninstall` CLI subcommands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from spindle.cli import main
from spindle.models import DistributionMetadata
from spindle.resolver import ResolverError


def _fake_dist(name="alpha-dist", version="1.0.0", packages=None):
    return DistributionMetadata(
        name=name,
        version=version,
        display_name="Alpha Distribution",
        description="Test distribution.",
        source_dir=Path("/fake/alpha"),
        preempt_snippet=None,
        home_url=None,
        packages=packages or ["sample-one==1.0.0", "sample-two==1.0.0"],
    )


# ---- dist install -------------------------------------------------------


class TestDistInstall:
    def test_install_exits_zero(self, capsys):
        dist = _fake_dist()
        with (
            patch("spindle.distributions.list_installed_distributions", side_effect=[[], [dist]]),
            patch("spindle.resolver.uv_install", return_value=("", "")),
            patch("spindle.skills.install_skills", return_value=[("sample-one", "installed")]),
            patch("spindle.ledger.log_event"),
        ):
            rc = main(["dist", "install", "alpha-dist==1.0.0"])
        assert rc == 0

    def test_install_calls_uv_install(self, capsys):
        dist = _fake_dist()
        with (
            patch("spindle.distributions.list_installed_distributions", side_effect=[[], [dist]]),
            patch("spindle.resolver.uv_install", return_value=("", "")) as mock_uv,
            patch("spindle.skills.install_skills", return_value=[]),
            patch("spindle.ledger.log_event"),
        ):
            main(["dist", "install", "alpha-dist==1.0.0"])
        mock_uv.assert_called_once_with("alpha-dist==1.0.0")

    def test_install_calls_install_skills_with_new_dist(self, capsys):
        dist = _fake_dist()
        with (
            patch("spindle.distributions.list_installed_distributions", side_effect=[[], [dist]]),
            patch("spindle.resolver.uv_install", return_value=("", "")),
            patch("spindle.skills.install_skills", return_value=[]) as mock_skills,
            patch("spindle.ledger.log_event"),
        ):
            main(["dist", "install", "alpha-dist==1.0.0"])
        mock_skills.assert_called_once_with(distribution="alpha-dist", dry_run=False)

    def test_install_prints_skill_actions(self, capsys):
        dist = _fake_dist()
        with (
            patch("spindle.distributions.list_installed_distributions", side_effect=[[], [dist]]),
            patch("spindle.resolver.uv_install", return_value=("", "")),
            patch("spindle.skills.install_skills", return_value=[("sample-one", "installed"), ("sample-two", "skipped:already-current")]),
            patch("spindle.ledger.log_event"),
        ):
            main(["dist", "install", "alpha-dist"])
        out = capsys.readouterr().out
        assert "sample-one" in out
        assert "installed" in out
        assert "sample-two" in out

    def test_install_writes_ledger_event(self, capsys):
        dist = _fake_dist()
        with (
            patch("spindle.distributions.list_installed_distributions", side_effect=[[], [dist]]),
            patch("spindle.resolver.uv_install", return_value=("", "")),
            patch("spindle.skills.install_skills", return_value=[]),
            patch("spindle.ledger.log_event") as mock_event,
            patch("importlib.metadata.distribution"),
        ):
            main(["dist", "install", "alpha-dist"])
        mock_event.assert_called_once()
        args, kwargs = mock_event.call_args
        assert args[0] == "dist_install"
        assert kwargs["distribution"] == "alpha-dist"
        assert kwargs["version"] == "1.0.0"

    def test_install_idempotent_no_new_dist(self, capsys):
        """When already installed, no new dist → install_skills called without filter."""
        dist = _fake_dist()
        with (
            patch("spindle.distributions.list_installed_distributions", return_value=[dist]),
            patch("spindle.resolver.uv_install", return_value=("", "")),
            patch("spindle.skills.install_skills", return_value=[("sample-one", "skipped:already-current")]) as mock_skills,
            patch("spindle.ledger.log_event") as mock_event,
        ):
            rc = main(["dist", "install", "alpha-dist"])
        assert rc == 0
        mock_skills.assert_called_once_with(distribution=None, dry_run=False)
        mock_event.assert_not_called()

    def test_install_dry_run_skips_uv(self, capsys):
        dist = _fake_dist()
        with (
            patch("spindle.distributions.list_installed_distributions", return_value=[dist]),
            patch("spindle.resolver.uv_install") as mock_uv,
            patch("spindle.skills.install_skills", return_value=[("sample-one", "skipped:already-current")]),
            patch("spindle.ledger.log_event"),
        ):
            rc = main(["dist", "install", "--dry-run", "alpha-dist"])
        assert rc == 0
        mock_uv.assert_not_called()

    def test_install_dry_run_skips_ledger(self, capsys):
        dist = _fake_dist()
        with (
            patch("spindle.distributions.list_installed_distributions", side_effect=[[], [dist]]),
            patch("spindle.resolver.uv_install", return_value=("", "")),
            patch("spindle.skills.install_skills", return_value=[]),
            patch("spindle.ledger.log_event") as mock_event,
        ):
            main(["dist", "install", "--dry-run", "alpha-dist"])
        mock_event.assert_not_called()

    def test_install_uv_error_exits_nonzero(self, capsys):
        with (
            patch("spindle.distributions.list_installed_distributions", return_value=[]),
            patch("spindle.resolver.uv_install", side_effect=ResolverError("uv failed", "some stderr")),
        ):
            rc = main(["dist", "install", "bad-pkg"])
        assert rc != 0
        err = capsys.readouterr().err
        assert "install error" in err

    def test_install_uv_stderr_printed(self, capsys):
        with (
            patch("spindle.distributions.list_installed_distributions", return_value=[]),
            patch("spindle.resolver.uv_install", side_effect=ResolverError("fail", "uv stderr output")),
        ):
            main(["dist", "install", "bad-pkg"])
        assert "uv stderr output" in capsys.readouterr().err


# ---- dist uninstall -----------------------------------------------------


class TestDistUninstall:
    def test_uninstall_exits_zero(self, capsys):
        dist = _fake_dist()
        with (
            patch("spindle.distributions.read_distribution_metadata", return_value=dist),
            patch("spindle.skills.uninstall_skills", return_value=[("sample-one", "removed")]),
            patch("spindle.ledger.log_event"),
        ):
            rc = main(["dist", "uninstall", "alpha-dist"])
        assert rc == 0

    def test_uninstall_unknown_dist_exits_nonzero(self, capsys):
        with patch("spindle.distributions.read_distribution_metadata", return_value=None):
            rc = main(["dist", "uninstall", "nonexistent"])
        assert rc != 0
        assert "nonexistent" in capsys.readouterr().err

    def test_uninstall_calls_uninstall_skills(self, capsys):
        dist = _fake_dist()
        with (
            patch("spindle.distributions.read_distribution_metadata", return_value=dist),
            patch("spindle.skills.uninstall_skills", return_value=[]) as mock_skills,
            patch("spindle.ledger.log_event"),
        ):
            main(["dist", "uninstall", "alpha-dist"])
        mock_skills.assert_called_once_with(distribution="alpha-dist", dry_run=False)

    def test_uninstall_prints_skill_actions(self, capsys):
        dist = _fake_dist()
        with (
            patch("spindle.distributions.read_distribution_metadata", return_value=dist),
            patch("spindle.skills.uninstall_skills", return_value=[("sample-one", "removed"), ("sample-two", "skipped:not-installed")]),
            patch("spindle.ledger.log_event"),
        ):
            main(["dist", "uninstall", "alpha-dist"])
        out = capsys.readouterr().out
        assert "sample-one" in out
        assert "removed" in out

    def test_uninstall_writes_ledger_event(self, capsys):
        dist = _fake_dist()
        with (
            patch("spindle.distributions.read_distribution_metadata", return_value=dist),
            patch("spindle.skills.uninstall_skills", return_value=[]),
            patch("spindle.ledger.log_event") as mock_event,
        ):
            main(["dist", "uninstall", "alpha-dist"])
        mock_event.assert_called_once()
        args, kwargs = mock_event.call_args
        assert args[0] == "dist_uninstall"
        assert kwargs["distribution"] == "alpha-dist"
        assert kwargs["version"] == "1.0.0"

    def test_uninstall_dry_run_skips_ledger(self, capsys):
        dist = _fake_dist()
        with (
            patch("spindle.distributions.read_distribution_metadata", return_value=dist),
            patch("spindle.skills.uninstall_skills", return_value=[]),
            patch("spindle.ledger.log_event") as mock_event,
        ):
            main(["dist", "uninstall", "--dry-run", "alpha-dist"])
        mock_event.assert_not_called()

    def test_uninstall_dry_run_passes_to_skills(self, capsys):
        dist = _fake_dist()
        with (
            patch("spindle.distributions.read_distribution_metadata", return_value=dist),
            patch("spindle.skills.uninstall_skills", return_value=[]) as mock_skills,
            patch("spindle.ledger.log_event"),
        ):
            main(["dist", "uninstall", "--dry-run", "alpha-dist"])
        mock_skills.assert_called_once_with(distribution="alpha-dist", dry_run=True)

    def test_uninstall_remove_packages_calls_uv_uninstall(self, capsys):
        dist = _fake_dist(packages=["sample-one==1.0.0", "sample-two==1.0.0"])
        with (
            patch("spindle.distributions.read_distribution_metadata", return_value=dist),
            patch("spindle.skills.uninstall_skills", return_value=[]),
            patch("spindle.resolver.uv_uninstall", return_value=("", "")) as mock_uv,
            patch("spindle.ledger.log_event"),
        ):
            main(["dist", "uninstall", "--remove-packages", "alpha-dist"])
        calls = [c.args[0] for c in mock_uv.call_args_list]
        assert "sample-one" in calls
        assert "sample-two" in calls
        assert "alpha-dist" in calls

    def test_uninstall_remove_packages_strips_version_spec(self, capsys):
        dist = _fake_dist(packages=["sample-one==1.2.3"])
        with (
            patch("spindle.distributions.read_distribution_metadata", return_value=dist),
            patch("spindle.skills.uninstall_skills", return_value=[]),
            patch("spindle.resolver.uv_uninstall", return_value=("", "")) as mock_uv,
            patch("spindle.ledger.log_event"),
        ):
            main(["dist", "uninstall", "--remove-packages", "alpha-dist"])
        calls = [c.args[0] for c in mock_uv.call_args_list]
        assert "sample-one" in calls
        assert "sample-one==1.2.3" not in calls

    def test_uninstall_no_remove_packages_skips_uv(self, capsys):
        dist = _fake_dist()
        with (
            patch("spindle.distributions.read_distribution_metadata", return_value=dist),
            patch("spindle.skills.uninstall_skills", return_value=[]),
            patch("spindle.resolver.uv_uninstall", return_value=("", "")) as mock_uv,
            patch("spindle.ledger.log_event"),
        ):
            main(["dist", "uninstall", "alpha-dist"])
        mock_uv.assert_not_called()

    def test_uninstall_remove_packages_prints_removed(self, capsys):
        dist = _fake_dist(packages=["sample-one==1.0.0"])
        with (
            patch("spindle.distributions.read_distribution_metadata", return_value=dist),
            patch("spindle.skills.uninstall_skills", return_value=[]),
            patch("spindle.resolver.uv_uninstall", return_value=("", "")),
            patch("spindle.ledger.log_event"),
        ):
            main(["dist", "uninstall", "--remove-packages", "alpha-dist"])
        out = capsys.readouterr().out
        assert "removed-package" in out

    def test_uninstall_remove_packages_dry_run_skips_uv(self, capsys):
        dist = _fake_dist()
        with (
            patch("spindle.distributions.read_distribution_metadata", return_value=dist),
            patch("spindle.skills.uninstall_skills", return_value=[]),
            patch("spindle.resolver.uv_uninstall", return_value=("", "")) as mock_uv,
            patch("spindle.ledger.log_event"),
        ):
            main(["dist", "uninstall", "--dry-run", "--remove-packages", "alpha-dist"])
        mock_uv.assert_not_called()
