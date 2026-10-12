from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from spindle import cli as cli_mod
from spindle.cli import main
from spindle.lifecycle import read_surface_lock, surface_id


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _fixture(tmp_path: Path, monkeypatch) -> tuple[Path, Path, str]:
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.email", "spindle@example.test")
    _git(source, "config", "user.name", "Spindle Test")
    skill = source / "skills" / "remote-demo"
    skill.mkdir(parents=True)
    skill.joinpath("SKILL.md").write_text(
        "---\nname: remote-demo\ndescription: Review migrations.\n---\n\n"
        "Check correctness and rollback.\n",
        encoding="utf-8",
    )
    source.joinpath("LICENSE").write_text("MIT fixture\n", encoding="utf-8")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "fixture")
    return project, source, _git(source, "rev-parse", "HEAD")


def test_remote_inspect_pins_source_and_does_not_activate(
    tmp_path, monkeypatch, capsys
):
    project, source, commit = _fixture(tmp_path, monkeypatch)
    reference = f"git:{source}@main#remote-demo"

    assert (
        main(
            [
                "inspect",
                reference,
                "--repo",
                str(project),
                "--harness",
                "codex",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["source_receipt"]["requested_revision"] == "main"
    assert payload["source_receipt"]["resolved_commit"] == commit
    assert payload["package_facts"]["provenance"]["source"]["revision"] == commit
    assert payload["preflight"]["execution"] == "none"
    assert payload["preflight"]["blockers"] == []
    assert not (project / ".agents" / "skills" / "remote-demo").exists()
    assert not (tmp_path / "state" / "cache" / "packages").exists()
    assert list((tmp_path / "state" / "source-receipts").glob("*.json"))
    assert list((tmp_path / "state" / "preflight-receipts").glob("*.json"))


def test_remote_try_uses_offline_pin_then_releases_without_adoption(
    tmp_path, monkeypatch, capsys
):
    project, source, commit = _fixture(tmp_path, monkeypatch)
    branch_ref = f"git:{source}@main#remote-demo"
    assert main(["inspect", branch_ref, "--repo", str(project), "--json"]) == 0
    capsys.readouterr()
    source.rename(tmp_path / "source-unavailable")
    task = tmp_path / "task.md"
    task.write_text("Review this migration.\n", encoding="utf-8")

    def fake_run(command, *, cwd, check, capture_output, text):
        assert command[0] == "codex"
        assert cwd == project.resolve()
        assert check is False and capture_output is True and text is True
        return SimpleNamespace(returncode=0, stdout="reviewed\n", stderr="")

    monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)
    result = main(
        [
            "try",
            f"git:{source}@{commit}#remote-demo",
            "--offline",
            "--task-file",
            str(task),
            "--repo",
            str(project),
            "--harness",
            "codex",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    lock = read_surface_lock(surface_id(project, "codex"))

    assert result == 0
    assert payload["lease"]["source"]["revision"] == commit
    assert payload["plan"]["source_receipt_id"]
    assert payload["plan"]["preflight_report_id"]
    assert payload["cleanup"]["action"] == "released"
    assert lock is not None and lock.lease_ids == () and lock.adoption_ids == ()
    assert not (project / ".agents" / "skills" / "remote-demo").exists()


def test_remote_executable_fails_closed_until_explicitly_approved(
    tmp_path, monkeypatch, capsys
):
    project, source, _commit = _fixture(tmp_path, monkeypatch)
    script = source / "skills" / "remote-demo" / "scripts" / "check.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    script.chmod(0o755)
    _git(source, "add", ".")
    _git(source, "commit", "-m", "script")
    reference = f"git:{source}@main#remote-demo"

    blocked = main(
        [
            "borrow",
            reference,
            "--until",
            "2h",
            "--repo",
            str(project),
            "--harness",
            "codex",
            "--json",
        ]
    )
    assert blocked == 2
    assert "explicit authority approval required" in capsys.readouterr().err
    assert read_surface_lock(surface_id(project, "codex")) is None
    assert not (project / ".agents" / "skills" / "remote-demo").exists()

    assert (
        main(
            [
                "borrow",
                reference,
                "--until",
                "2h",
                "--repo",
                str(project),
                "--harness",
                "codex",
                "--allow-executable",
                "--dry-run",
                "--json",
            ]
        )
        == 0
    )
    allowed = json.loads(capsys.readouterr().out)
    assert allowed["preflight"]["blockers"] == []


def test_quarantine_blocks_future_lease_and_preserves_prior_receipts(
    tmp_path, monkeypatch, capsys
):
    project, source, _commit = _fixture(tmp_path, monkeypatch)
    reference = f"git:{source}@main#remote-demo"
    assert main(["inspect", reference, "--repo", str(project), "--json"]) == 0
    inspected = json.loads(capsys.readouterr().out)
    package_digest = inspected["package_facts"]["provenance"]["package_digest"]
    source_receipt = Path(inspected["preflight_receipt_path"])
    before = source_receipt.read_bytes()

    assert (
        main(
            [
                "source",
                "quarantine",
                package_digest,
                "--reason",
                "revoked upstream",
                "--actor",
                "security",
                "--json",
            ]
        )
        == 0
    )
    policy = json.loads(capsys.readouterr().out)
    assert policy["event"]["action"] == "quarantine"

    assert (
        main(
            [
                "borrow",
                reference,
                "--until",
                "2h",
                "--repo",
                str(project),
                "--harness",
                "codex",
                "--json",
            ]
        )
        == 2
    )
    assert "is quarantined" in capsys.readouterr().err
    assert source_receipt.read_bytes() == before
    assert read_surface_lock(surface_id(project, "codex")) is None
