"""Tests for spindle.fleet — machine-id, git-backed sync, multi-machine status."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import spindle.fleet as fleet_mod
from spindle.cli import main


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolate every test from the real ~/.claude/spindle-state/."""
    h = tmp_path / "spindle-home"
    h.mkdir()
    monkeypatch.setenv("SPINDLE_HOME", str(h))
    monkeypatch.setenv("SPINDLE_FLEET_REPO", str(h / "fleet"))
    return h


def _events(*kinds_dists):
    """Build a JSONL blob from (kind, distribution, version?) tuples."""
    out = []
    for i, item in enumerate(kinds_dists):
        kind, dist, *rest = item
        version = rest[0] if rest else "0.1.0"
        out.append(json.dumps({
            "kind": kind,
            "ts": f"2026-05-13T00:00:{i:02d}Z",
            "distribution": dist,
            "version": version,
        }))
    return "\n".join(out) + "\n"


# ---- machine_id ---------------------------------------------------------

def test_machine_id_stable(home):
    a = fleet_mod.machine_id()
    b = fleet_mod.machine_id()
    assert a == b
    assert len(a) == 36  # UUID v4 string form


def test_machine_id_persisted_to_file(home):
    mid = fleet_mod.machine_id()
    assert (home / "machine.id").read_text().strip() == mid


# ---- sync ---------------------------------------------------------------

def test_sync_initializes_repo_and_copies_events(home, tmp_path):
    local = tmp_path / "ledger.jsonl"
    local.write_text(_events(("dist_install", "spindle-sample", "0.2.0")))

    result = fleet_mod.fleet_sync(local_events=local, push=False)

    assert result.repo == home / "fleet"
    assert (home / "fleet" / ".git").is_dir()
    assert result.committed is True
    target = home / "fleet" / "events" / f"{result.machine}.jsonl"
    assert target.exists()
    assert target.read_text() == local.read_text()


def test_sync_no_local_events_creates_empty_file(home):
    result = fleet_mod.fleet_sync(local_events=Path("/does/not/exist"), push=False)
    target = home / "fleet" / "events" / f"{result.machine}.jsonl"
    assert target.exists()
    assert target.read_text() == ""


def test_sync_second_run_is_idempotent(home, tmp_path):
    local = tmp_path / "ledger.jsonl"
    local.write_text(_events(("dist_install", "spindle-sample")))

    r1 = fleet_mod.fleet_sync(local_events=local, push=False)
    r2 = fleet_mod.fleet_sync(local_events=local, push=False)

    assert r1.committed is True
    assert r2.committed is False  # nothing new to stage


def test_sync_pushes_to_configured_remote(home, tmp_path):
    """Use a bare local git repo as the 'remote' so we can verify push works."""
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)

    local = tmp_path / "ledger.jsonl"
    local.write_text(_events(("dist_install", "spindle-sample")))

    result = fleet_mod.fleet_sync(remote=str(bare), local_events=local)

    assert result.remote == str(bare)
    assert result.pushed is True

    # Confirm the bare repo has our commit
    log = subprocess.run(
        ["git", "--git-dir", str(bare), "log", "--oneline"],
        capture_output=True, text=True, check=True,
    )
    assert "sync " in log.stdout


def test_sync_remote_url_persists_across_runs(home, tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)

    local = tmp_path / "ledger.jsonl"
    local.write_text(_events(("dist_install", "spindle-sample")))
    fleet_mod.fleet_sync(remote=str(bare), local_events=local)

    # Second sync with no --remote should still find origin
    local.write_text(_events(
        ("dist_install", "spindle-sample"),
        ("dist_install", "spindle-sample", "0.1.0"),
    ))
    result = fleet_mod.fleet_sync(local_events=local)
    assert result.remote == str(bare)
    assert result.pushed is True


# ---- status -------------------------------------------------------------

def test_status_empty(home):
    assert fleet_mod.fleet_status() == []


def test_status_lists_installed_distributions_per_machine(home, tmp_path):
    fleet = home / "fleet"
    (fleet / "events").mkdir(parents=True)

    (fleet / "events" / "machine-a.jsonl").write_text(_events(
        ("dist_install", "spindle-sample", "0.2.0"),
    ))
    (fleet / "events" / "machine-b.jsonl").write_text(_events(
        ("dist_install", "spindle-sample", "0.2.0"),
        ("dist_install", "spindle-sample", "0.3.0"),
    ))

    rows = fleet_mod.fleet_status()
    by_id = {r.machine: r for r in rows}
    assert by_id["machine-a"].distributions == {"spindle-sample": "0.2.0"}
    assert by_id["machine-b"].distributions == {"spindle-sample": "0.2.0", "spindle-sample": "0.3.0"}


def test_status_dist_uninstall_removes(home):
    fleet = home / "fleet"
    (fleet / "events").mkdir(parents=True)
    (fleet / "events" / "m1.jsonl").write_text(
        _events(("dist_install", "spindle-sample"), ("dist_uninstall", "spindle-sample"))
    )
    rows = fleet_mod.fleet_status()
    assert rows[0].distributions == {}


def test_status_skips_corrupt_lines(home):
    fleet = home / "fleet"
    (fleet / "events").mkdir(parents=True)
    (fleet / "events" / "m1.jsonl").write_text(
        "not json\n" + _events(("dist_install", "spindle-sample"))
    )
    rows = fleet_mod.fleet_status()
    assert rows[0].distributions == {"spindle-sample": "0.1.0"}


# ---- concurrent-installs invariant --------------------------------------

def test_two_machines_do_not_conflict(home, tmp_path):
    """Two machines pushing different per-machine files round-trips cleanly."""
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)

    # Machine A
    repo_a = tmp_path / "a"
    ledger_a = tmp_path / "ledger_a.jsonl"
    ledger_a.write_text(_events(("dist_install", "spindle-sample")))
    ra = fleet_mod.fleet_sync(
        remote=str(bare), repo=repo_a, local_events=ledger_a, mid="machine-a",
    )
    assert ra.pushed is True

    # Machine B clones fresh and syncs its own file concurrently
    repo_b = tmp_path / "b"
    ledger_b = tmp_path / "ledger_b.jsonl"
    ledger_b.write_text(_events(("dist_install", "spindle-sample", "0.3.0")))
    rb = fleet_mod.fleet_sync(
        remote=str(bare), repo=repo_b, local_events=ledger_b, mid="machine-b",
    )
    assert rb.pushed is True, rb.detail

    # Machine A pulls — should see both files now without conflict
    ra2 = fleet_mod.fleet_sync(
        remote=str(bare), repo=repo_a, local_events=ledger_a, mid="machine-a",
    )
    assert ra2.pulled is True, ra2.detail
    assert (repo_a / "events" / "machine-a.jsonl").exists()
    assert (repo_a / "events" / "machine-b.jsonl").exists()

    rows = fleet_mod.fleet_status(repo=repo_a)
    by_id = {r.machine: r for r in rows}
    assert by_id["machine-a"].distributions == {"spindle-sample": "0.1.0"}
    assert by_id["machine-b"].distributions == {"spindle-sample": "0.3.0"}


# ---- CLI ---------------------------------------------------------------

def test_cli_fleet_status_empty(home, capsys):
    rc = main(["fleet", "status"])
    assert rc == 0
    assert "no fleet events" in capsys.readouterr().out


def test_cli_fleet_sync_no_push(home, tmp_path, monkeypatch, capsys):
    local = tmp_path / "ledger.jsonl"
    local.write_text(_events(("dist_install", "spindle-sample")))
    monkeypatch.setattr(fleet_mod, "ledger_path", lambda: local)

    rc = main(["fleet", "sync", "--no-push"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "committed: True" in out
    assert (home / "fleet" / "events" / f"{fleet_mod.machine_id()}.jsonl").exists()


def test_cli_fleet_status_shows_machines(home, tmp_path, monkeypatch, capsys):
    local = tmp_path / "ledger.jsonl"
    local.write_text(_events(("dist_install", "spindle-sample", "0.2.0")))
    monkeypatch.setattr(fleet_mod, "ledger_path", lambda: local)

    assert main(["fleet", "sync", "--no-push"]) == 0
    capsys.readouterr()  # discard

    assert main(["fleet", "status"]) == 0
    out = capsys.readouterr().out
    assert "spindle-sample@0.2.0" in out
    assert fleet_mod.machine_id() in out
