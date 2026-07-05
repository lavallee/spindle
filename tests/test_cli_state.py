"""Tests for `spindle state show` and `spindle state rebuild` CLI subcommands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spindle.cli import main
from spindle.ledger import log_event
from spindle.paths import events_file, state_file


@pytest.fixture(autouse=True)
def isolated_spindle_home(tmp_path, monkeypatch):
    """Redirect SPINDLE_HOME to a fresh tmp dir for every test."""
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "spindle-state"))


class TestStateShow:
    def test_show_exit_zero(self, capsys):
        rc = main(["state", "show"])
        assert rc == 0

    def test_show_displays_machine_id(self, capsys):
        log_event("dist_install", distribution="test-dist", version="1.0.0")
        rc = main(["state", "show"])
        out = capsys.readouterr().out
        assert "machine_id" in out
        assert rc == 0

    def test_show_displays_rebuilt_at(self, capsys):
        log_event("dist_install", distribution="test-dist", version="1.0.0")
        rc = main(["state", "show"])
        out = capsys.readouterr().out
        assert "rebuilt_at" in out
        assert rc == 0

    def test_show_displays_distributions(self, capsys):
        log_event("dist_install", distribution="spindle-sample", version="1.0.0")
        rc = main(["state", "show"])
        out = capsys.readouterr().out
        assert "spindle-sample" in out
        assert rc == 0

    def test_show_displays_distribution_details(self, capsys):
        log_event(
            "dist_install",
            distribution="spindle-sample",
            version="1.0.0",
            packages={"sample-grill": "0.2.0"},
            skills_linked=["sample-grill"],
        )
        rc = main(["state", "show"])
        out = capsys.readouterr().out
        assert "spindle-sample" in out
        assert "1.0.0" in out
        assert "sample-grill" in out
        assert rc == 0

    def test_show_empty_distributions(self, capsys):
        rc = main(["state", "show"])
        out = capsys.readouterr().out
        assert "distributions" in out.lower() or "(none)" in out
        assert rc == 0

    def test_show_preempted_by(self, capsys):
        log_event("preempt", action="add", distribution="spindle-sample")
        rc = main(["state", "show"])
        out = capsys.readouterr().out
        assert "preempted_by" in out
        assert "spindle-sample" in out
        assert rc == 0


class TestStateRebuild:
    def test_rebuild_exit_zero(self, capsys):
        rc = main(["state", "rebuild"])
        assert rc == 0

    def test_rebuild_confirms_write(self, capsys):
        rc = main(["state", "rebuild"])
        out = capsys.readouterr().out
        assert "rebuilt state from" in out or "wrote" in out
        assert rc == 0

    def test_rebuild_creates_state_file(self, capsys):
        log_event("dist_install", distribution="test-dist", version="1.0.0")
        main(["state", "rebuild"])
        assert state_file().exists()

    def test_rebuild_persists_distributions(self, capsys):
        log_event("dist_install", distribution="spindle-sample", version="1.0.0")
        main(["state", "rebuild"])
        data = json.loads(state_file().read_text())
        assert "spindle-sample" in data["distributions"]

    def test_rebuild_recounts_distributions(self, capsys):
        log_event("dist_install", distribution="dist1", version="1.0.0")
        log_event("dist_install", distribution="dist2", version="2.0.0")
        rc = main(["state", "rebuild"])
        out = capsys.readouterr().out
        assert "distributions:    2" in out
        assert rc == 0

    def test_rebuild_reflects_uninstalls(self, capsys):
        log_event("dist_install", distribution="test-dist", version="1.0.0")
        log_event("dist_uninstall", distribution="test-dist")
        rc = main(["state", "rebuild"])
        out = capsys.readouterr().out
        assert "distributions:    0" in out
        assert rc == 0

    def test_rebuild_shows_machine_id(self, capsys):
        rc = main(["state", "rebuild"])
        out = capsys.readouterr().out
        assert "machine_id:" in out
        assert rc == 0
