"""Tests for src/spindle/ledger.py.

All tests use SPINDLE_HOME pointing at a tmp dir so the real ~/.claude/spindle-state/
is never touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import spindle.ledger as ledger_mod
from spindle.ledger import log_event, machine_id, materialize, show_state
from spindle.paths import events_file, machine_id_file, state_file


@pytest.fixture(autouse=True)
def isolated_spindle_home(tmp_path, monkeypatch):
    """Redirect SPINDLE_HOME to a fresh tmp dir for every test."""
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "spindle-state"))


# ---------------------------------------------------------------------------
# machine_id
# ---------------------------------------------------------------------------


def test_machine_id_stable():
    mid1 = machine_id()
    mid2 = machine_id()
    assert mid1 == mid2
    assert len(mid1) == 36  # UUID format


def test_machine_id_creates_file():
    mid = machine_id()
    assert machine_id_file().exists()
    assert machine_id_file().read_text().strip() == mid


def test_machine_id_reads_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "custom-home"))
    mid_path = machine_id_file()
    mid_path.parent.mkdir(parents=True, exist_ok=True)
    mid_path.write_text("fixed-uuid-value\n")
    assert machine_id() == "fixed-uuid-value"


# ---------------------------------------------------------------------------
# log_event
# ---------------------------------------------------------------------------


def test_log_event_appends():
    log_event("dist_install", distribution="spindle-sample", version="0.2.0")
    lines = events_file().read_text().splitlines()
    assert len(lines) == 1
    ev = json.loads(lines[0])
    assert ev["kind"] == "dist_install"
    assert ev["distribution"] == "spindle-sample"
    assert ev["version"] == "0.2.0"
    assert "ts" in ev
    assert "machine" in ev


def test_log_event_multiple_appends():
    log_event("dist_install", distribution="spindle-sample", version="0.2.0")
    log_event("dist_uninstall", distribution="spindle-sample")
    lines = events_file().read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["kind"] == "dist_uninstall"


def test_log_event_machine_matches_machine_id():
    mid = machine_id()
    log_event("test_kind")
    ev = json.loads(events_file().read_text().strip())
    assert ev["machine"] == mid


# ---------------------------------------------------------------------------
# materialize
# ---------------------------------------------------------------------------


def test_materialize_empty():
    state = materialize()
    assert state.distributions == {}
    assert state.preempted_by is None
    assert state.machine_id == machine_id()


def test_materialize_install_then_uninstall():
    log_event(
        "dist_install",
        distribution="spindle-sample",
        version="0.2.0",
        packages={"sample-grill": "0.2.0"},
        skills_linked=["sample-grill"],
    )
    state = materialize()
    assert "spindle-sample" in state.distributions
    assert state.distributions["spindle-sample"].version == "0.2.0"

    log_event("dist_uninstall", distribution="spindle-sample")
    state = materialize()
    assert "spindle-sample" not in state.distributions


def test_materialize_persists_state_json():
    log_event("dist_install", distribution="spindle-sample", version="0.2.0")
    materialize()
    assert state_file().exists()
    data = json.loads(state_file().read_text())
    assert "spindle-sample" in data["distributions"]


def test_materialize_preempt_events():
    log_event("preempt", action="add", distribution="spindle-sample")
    state = materialize()
    assert state.preempted_by == "spindle-sample"

    log_event("preempt", action="remove", distribution="spindle-sample")
    state = materialize()
    assert state.preempted_by is None


def test_materialize_skips_corrupt_line():
    ef = events_file()
    ef.parent.mkdir(parents=True, exist_ok=True)
    ef.write_text('{"kind":"dist_install","distribution":"a","version":"1.0","ts":"t","machine":"m"}\nnot-json\n')
    state = materialize()
    assert "a" in state.distributions


# ---------------------------------------------------------------------------
# show_state
# ---------------------------------------------------------------------------


def test_show_state_returns_cached_when_fresh():
    log_event("dist_install", distribution="spindle-sample", version="0.2.0")
    materialize()  # writes state.json

    # show_state should read the cached version without re-folding
    state = show_state()
    assert "spindle-sample" in state.distributions


def test_show_state_rebuilds_when_no_cache():
    log_event("dist_install", distribution="spindle-sample", version="0.2.0")
    state = show_state()  # no state.json yet → must materialize
    assert "spindle-sample" in state.distributions
