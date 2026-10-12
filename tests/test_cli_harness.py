"""CLI coverage for the harness-native Spindle operator."""

from __future__ import annotations

import json
from pathlib import Path

from spindle.cli import main


def _isolate(monkeypatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(home))
    return home


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


def test_harness_setup_context_status_and_remove_json(
    tmp_path, monkeypatch, capsys
):
    _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    common = ["--harness", "codex", "--repo", str(repo), "--json"]

    assert main(["harness", "setup", *common, "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "would-install"

    assert main(["harness", "setup", *common]) == 0
    installed = json.loads(capsys.readouterr().out)
    assert installed["action"] == "install"
    assert "Start a new Codex session" in installed["next"]

    monkeypatch.setenv("CODEX_THREAD_ID", "thread")
    assert (
        main(["harness", "context", "--repo", str(repo), "--json"])
        == 0
    )
    context = json.loads(capsys.readouterr().out)
    assert context["surface"]["harness"] == "codex"
    assert context["surface"]["harness_detected_by"] == "environment"
    assert context["operator"]["invocation"] == "$spindle"

    assert main(["harness", "status", *common]) == 1
    status = json.loads(capsys.readouterr().out)
    assert status["operator"]["state"] == "current"
    assert status["operator"]["hooks"]["state"] == "configured-unverified"

    assert main(["harness", "remove", *common, "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "would-remove"
    assert main(["harness", "remove", *common]) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "removed"


def test_harness_context_reports_auto_detection_error(
    tmp_path, monkeypatch, capsys
):
    _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CODEX_CI", raising=False)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)

    assert main(["harness", "context", "--repo", str(repo), "--json"]) == 2
    assert "cannot determine the active harness" in capsys.readouterr().err
