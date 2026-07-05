"""Tests for spindle.rate and the 'spindle rate' CLI subcommand."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import spindle.rate as rate_mod
from spindle.cli import main


# ---- unit: rate module --------------------------------------------------

def test_rate_creates_feedback_and_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(rate_mod, "feedback_dir", lambda: tmp_path / "feedback")
    monkeypatch.setattr(rate_mod, "ledger_path", lambda: tmp_path / "ledger.jsonl")

    fb, ld = rate_mod.rate("spindle-grill", "up", "works great")

    assert fb.exists()
    text = fb.read_text()
    assert "thumbs-up" in text
    assert "works great" in text

    assert ld.exists()
    event = json.loads(ld.read_text().strip())
    assert event["event"] == "rate"
    assert event["skill"] == "spindle-grill"
    assert event["thumbs"] == "up"
    assert event["note"] == "works great"


def test_rate_thumbs_down(tmp_path, monkeypatch):
    monkeypatch.setattr(rate_mod, "feedback_dir", lambda: tmp_path / "feedback")
    monkeypatch.setattr(rate_mod, "ledger_path", lambda: tmp_path / "ledger.jsonl")

    fb, ld = rate_mod.rate("spindle-plan", "down", "too slow")

    assert "thumbs-down" in fb.read_text()
    event = json.loads(ld.read_text().strip())
    assert event["thumbs"] == "down"


def test_rate_appends_multiple(tmp_path, monkeypatch):
    monkeypatch.setattr(rate_mod, "feedback_dir", lambda: tmp_path / "feedback")
    monkeypatch.setattr(rate_mod, "ledger_path", lambda: tmp_path / "ledger.jsonl")

    rate_mod.rate("spindle-grill", "up", "first")
    rate_mod.rate("spindle-grill", "down", "second")

    lines = (tmp_path / "ledger.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    fb_text = (tmp_path / "feedback" / "spindle-grill.md").read_text()
    assert "first" in fb_text
    assert "second" in fb_text


def test_rate_no_note(tmp_path, monkeypatch):
    monkeypatch.setattr(rate_mod, "feedback_dir", lambda: tmp_path / "feedback")
    monkeypatch.setattr(rate_mod, "ledger_path", lambda: tmp_path / "ledger.jsonl")

    rate_mod.rate("spindle-itemize", "up", "")

    event = json.loads((tmp_path / "ledger.jsonl").read_text().strip())
    assert event["note"] == ""


def test_rate_invalid_thumbs(tmp_path, monkeypatch):
    monkeypatch.setattr(rate_mod, "feedback_dir", lambda: tmp_path / "feedback")
    monkeypatch.setattr(rate_mod, "ledger_path", lambda: tmp_path / "ledger.jsonl")

    with pytest.raises(ValueError, match="thumbs must be"):
        rate_mod.rate("spindle-grill", "sideways", "")


# ---- integration: CLI subcommand ----------------------------------------

def test_cli_rate_thumbs_up(tmp_path, monkeypatch):
    monkeypatch.setattr(rate_mod, "feedback_dir", lambda: tmp_path / "feedback")
    monkeypatch.setattr(rate_mod, "ledger_path", lambda: tmp_path / "ledger.jsonl")

    rc = main(["rate", "spindle-grill", "--thumbs-up", "--note", "CLI smoke test"])
    assert rc == 0

    assert (tmp_path / "feedback" / "spindle-grill.md").exists()
    event = json.loads((tmp_path / "ledger.jsonl").read_text().strip())
    assert event["thumbs"] == "up"


def test_cli_rate_thumbs_down(tmp_path, monkeypatch):
    monkeypatch.setattr(rate_mod, "feedback_dir", lambda: tmp_path / "feedback")
    monkeypatch.setattr(rate_mod, "ledger_path", lambda: tmp_path / "ledger.jsonl")

    rc = main(["rate", "spindle-plan", "--thumbs-down"])
    assert rc == 0

    event = json.loads((tmp_path / "ledger.jsonl").read_text().strip())
    assert event["thumbs"] == "down"
    assert event["note"] == ""


def test_cli_rate_mutual_exclusion():
    with pytest.raises(SystemExit) as exc:
        main(["rate", "spindle-grill", "--thumbs-up", "--thumbs-down"])
    assert exc.value.code != 0
