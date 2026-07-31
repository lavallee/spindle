"""CLI coverage for stable native hook-kit lifecycle and doctor gates."""

from __future__ import annotations

import io
import json
from pathlib import Path

from spindle import cli as cli_mod
from spindle.cli import main


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


def test_hooks_plan_install_status_heartbeat_and_remove(tmp_path, monkeypatch, capsys):
    _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    common = ["--harness", "codex", "--repo", str(repo), "--json"]

    assert main(["hooks", "plan", *common]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert len(plan["additions"]) == 2
    assert not (repo / ".codex" / "hooks.json").exists()

    assert main(["hooks", "install", *common, "--dry-run"]) == 0
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["action"] == "would-install"
    assert not (repo / ".codex" / "hooks.json").exists()

    assert main(["hooks", "install", *common]) == 0
    installed = json.loads(capsys.readouterr().out)
    assert installed["action"] == "installed"
    assert installed["ownership"]["receipt_id"].startswith("sha256:")

    assert main(["hooks", "status", *common, "--effective"]) == 1
    configured = json.loads(capsys.readouterr().out)
    assert configured["state"] == "configured-unverified"

    monkeypatch.setattr(
        cli_mod.sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "cwd": str(repo),
                    "hook_event_name": "SessionStart",
                    "source": "startup",
                    "version": "codex-test",
                }
            )
        ),
    )
    assert main(["bootstrap", "--hook", "codex", "--event", "SessionStart"]) == 0
    json.loads(capsys.readouterr().out)

    assert main(["hooks", "status", *common, "--effective"]) == 1
    observed = json.loads(capsys.readouterr().out)
    assert observed["state"] == "observed-warn"
    assert observed["heartbeat"]["event_source"] == "startup"

    assert main(["hooks", "remove", *common]) == 0
    removed = json.loads(capsys.readouterr().out)
    assert removed["action"] == "removed"
    assert not (repo / ".codex" / "hooks.json").exists()


def test_hook_install_and_remove_preserve_foreign_configuration(
    tmp_path, monkeypatch, capsys
):
    _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    target = repo / ".claude" / "settings.json"
    target.parent.mkdir()
    target.write_text(
        json.dumps(
            {
                "model": "sonnet",
                "hooks": {
                    "Stop": [{"hooks": [{"type": "command", "command": "keep-me"}]}]
                },
            }
        ),
        encoding="utf-8",
    )
    common = ["--harness", "claude", "--repo", str(repo), "--json"]

    assert main(["hooks", "install", *common]) == 0
    capsys.readouterr()
    assert main(["hooks", "remove", *common]) == 0
    capsys.readouterr()

    assert json.loads(target.read_text(encoding="utf-8")) == {
        "model": "sonnet",
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "keep-me"}]}]},
    }


def test_doctor_blocks_statically_disabled_hooks(tmp_path, monkeypatch, capsys):
    _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    config = repo / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text("[features]\nhooks = false\n", encoding="utf-8")

    result = main(
        [
            "doctor",
            "--startup",
            "--harness",
            "codex",
            "--repo",
            str(repo),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 2
    assert payload["decision"] == "blocked"
    assert payload["hooks"]["state"] == "blocked"
    assert any("disabled" in item for item in payload["hooks"]["blockers"])


def test_user_scope_resolves_against_home(tmp_path, monkeypatch, capsys):
    _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)

    assert (
        main(
            [
                "hooks",
                "plan",
                "--harness",
                "claude",
                "--scope",
                "user",
                "--repo",
                str(repo),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["target_path"] == str(
        (tmp_path / "home" / ".claude" / "settings.json").absolute()
    )
