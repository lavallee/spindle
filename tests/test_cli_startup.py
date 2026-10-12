"""CLI coverage for bootstrap, native hook output, and pre-launch gating."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from spindle import cli as cli_mod
from spindle.cli import main
from spindle.lifecycle import (
    ExpectedProjection,
    SurfaceLock,
    digest_path,
    surface_id,
    write_surface_lock,
)


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def _skill(root: Path, name: str) -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Exercise {name}.\n---\n\nUse evidence.\n"
    )
    return skill


def _missing_lock(repo: Path, source: Path, name: str = "review") -> SurfaceLock:
    digest = digest_path(source)
    projection = repo / ".agents" / "skills" / name
    lock = SurfaceLock(
        surface_id=surface_id(repo, "codex"),
        surface_name=repo.name,
        repo_path=str(repo.resolve()),
        harness="codex",
        binding_coordinate="binding:test",
        projections=(
            ExpectedProjection(
                skill=name,
                projection_path=str(projection.absolute()),
                source_path=str(source.resolve()),
                source_digest=digest,
                package_digest=digest,
            ),
        ),
    )
    write_surface_lock(lock)
    return lock


def test_bootstrap_check_writes_plan_and_receipt(tmp_path, monkeypatch, capsys):
    _isolate(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    result = main(
        [
            "bootstrap",
            "--harness",
            "codex",
            "--repo",
            str(repo),
            "--check",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["receipt"]["decision"] == "warn"  # opaque adapter scopes
    assert Path(payload["plan_path"]).is_file()
    assert Path(payload["receipt_path"]).is_file()


def test_bootstrap_reconcile_repairs_missing_locked_projection(
    tmp_path, monkeypatch, capsys
):
    _isolate(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    source = _skill(tmp_path / "sources", "review")
    _missing_lock(repo, source)
    projection = repo / ".agents" / "skills" / "review"

    checked = main(
        [
            "bootstrap",
            "--harness",
            "codex",
            "--repo",
            str(repo),
            "--check",
            "--json",
        ]
    )
    check_payload = json.loads(capsys.readouterr().out)
    repaired = main(
        [
            "bootstrap",
            "--harness",
            "codex",
            "--repo",
            str(repo),
            "--reconcile-owned",
            "--json",
        ]
    )
    repair_payload = json.loads(capsys.readouterr().out)

    assert checked == 2
    assert check_payload["receipt"]["decision"] == "blocked"
    assert repaired == 0
    assert repair_payload["receipt"]["decision"] == "warn"
    assert repair_payload["receipt"]["applied_actions"][0]["kind"] == "link"
    assert projection.resolve() == source.resolve()


@pytest.mark.parametrize("source", ["resume", "clear", "compact"])
def test_hook_emits_bounded_native_json_and_records_session_source(
    tmp_path, monkeypatch, capsys, source
):
    _isolate(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    monkeypatch.setattr(
        cli_mod.sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "cwd": str(repo),
                    "hook_event_name": "SessionStart",
                    "source": source,
                    "model": "gpt-test",
                    "version": "codex-test",
                }
            )
        ),
    )

    result = main(["bootstrap", "--hook", "codex", "--event", "SessionStart"])
    hook_output = json.loads(capsys.readouterr().out)

    assert result == 0
    specific = hook_output["hookSpecificOutput"]
    assert specific["hookEventName"] == "SessionStart"
    assert specific["additionalContext"].startswith("Spindle: warn;")
    receipts = list((tmp_path / "state" / "startup-receipts").glob("*.json"))
    receipt = json.loads(receipts[0].read_text())
    assert receipt["event_source"] == source
    assert receipt["adapter_build"] == "codex-test"
    assert receipt["runtime_facts"] == {
        "hook_event_name": "SessionStart",
        "model": "gpt-test",
        "source": source,
    }


def test_hook_reports_restart_required_for_post_discovery_repair(
    tmp_path, monkeypatch, capsys
):
    _isolate(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    source = _skill(tmp_path / "sources", "review")
    _missing_lock(repo, source)
    monkeypatch.setattr(
        cli_mod.sys,
        "stdin",
        io.StringIO(json.dumps({"cwd": str(repo), "hook_event_name": "SessionStart"})),
    )

    result = main(["bootstrap", "--hook", "codex", "--event", "SessionStart"])
    hook_output = json.loads(capsys.readouterr().out)

    assert result == 0
    assert "restart-required" in hook_output["hookSpecificOutput"]["additionalContext"]
    assert not (repo / ".agents" / "skills" / "review").exists()


def test_launch_runs_harness_only_after_acceptable_preflight(
    tmp_path, monkeypatch, capsys
):
    _isolate(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    observed = []

    def fake_run(command, *, cwd, check):
        observed.append((command, cwd, check))
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)

    result = main(["launch", "codex", "--repo", str(repo), "--", "--model", "gpt-test"])
    capsys.readouterr()

    assert result == 7
    assert observed == [(["codex", "--model", "gpt-test"], repo.resolve(), False)]
