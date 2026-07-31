"""Complete lifecycle acceptance journey for both reference harnesses."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from spindle import cli as cli_mod
from spindle.cli import main
from spindle.lifecycle import read_surface_lock, surface_id
from spindle.maintenance import AdoptionStore, current_status


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _skill(path: Path, name: str, body: str) -> Path:
    path.mkdir(parents=True)
    path.joinpath("SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Acceptance skill.\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def _json(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


@pytest.mark.parametrize("harness", ["claude", "codex"])
@pytest.mark.parametrize("polluted", [False, True], ids=["clean", "polluted"])
def test_complete_reference_harness_lifecycle(
    tmp_path, monkeypatch, capsys, harness, polluted
):
    state = tmp_path / "state"
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SPINDLE_HOME", str(state))
    monkeypatch.setenv("HOME", str(home))
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    target_root = project / (".claude/skills" if harness == "claude" else ".agents/skills")
    ambient = _skill(target_root / "ambient", "ambient", "Unrelated user-managed skill.")
    ambient_before = ambient.joinpath("SKILL.md").read_bytes()

    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.email", "spindle@example.test")
    _git(source, "config", "user.name", "Spindle Test")
    candidate = _skill(
        source / "skills" / "journey", "journey", "Version one: check rollback."
    )
    source.joinpath("LICENSE").write_text("MIT fixture\n", encoding="utf-8")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "version one")
    first_commit = _git(source, "rev-parse", "HEAD")
    reference = f"git:{source}@main#journey"
    task = tmp_path / "task.md"
    task.write_text("Review the migration and return a verdict.\n", encoding="utf-8")

    assert (
        main(
            [
                "inspect",
                reference,
                "--repo",
                str(project),
                "--harness",
                harness,
                "--json",
            ]
        )
        == 0
    )
    inspected = _json(capsys)
    assert inspected["source_receipt"]["resolved_commit"] == first_commit
    projection = target_root / "journey"
    assert not projection.exists()

    real_run = subprocess.run
    next_exit = [0]

    def fake_run(command, **kwargs):
        if command[0] not in {"claude", "codex"}:
            return real_run(command, **kwargs)
        return SimpleNamespace(
            returncode=next_exit.pop(0), stdout="journey verdict\n", stderr=""
        )

    monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)
    assert (
        main(
            [
                "try",
                reference,
                "--task-file",
                str(task),
                "--repo",
                str(project),
                "--harness",
                harness,
                "--model",
                "model-v1",
                "--json",
            ]
        )
        == 0
    )
    first_trial = _json(capsys)
    assert first_trial["run_receipt"]["exit_code"] == 0
    assert first_trial["cleanup"]["action"] == "released"
    assert not projection.exists()

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
                harness,
                "--json",
            ]
        )
        == 0
    )
    borrowed = _json(capsys)
    borrow_id = borrowed["lease"]["lease_id"]
    assert projection.is_symlink()
    assert (
        main(
            [
                "bootstrap",
                "--harness",
                harness,
                "--repo",
                str(project),
                "--check",
                "--json",
            ]
        )
        == 0
    )
    restarted = _json(capsys)
    assert restarted["receipt"]["lease_status"]["active"] == [borrow_id]

    # Missing, rather than user-retargeted, is the ownership-safe repair case.
    projection.unlink()
    foreign = None
    foreign_before = None
    if polluted:
        user_root = home / (".claude/skills" if harness == "claude" else ".agents/skills")
        foreign = _skill(
            user_root / "journey", "journey", "Intentional user-scoped alternate."
        )
        foreign_before = foreign.joinpath("SKILL.md").read_bytes()
        assert (
            main(
                [
                    "bootstrap",
                    "--harness",
                    harness,
                    "--repo",
                    str(project),
                    "--reconcile-owned",
                    "--json",
                ]
            )
            == 2
        )
        blocked = _json(capsys)
        assert blocked["receipt"]["decision"] == "blocked"
        assert (
            main(
                [
                    "conflict",
                    "allow",
                    "journey",
                    "--path",
                    str(foreign),
                    "--reason",
                    "intentional test alternate",
                    "--repo",
                    str(project),
                    "--harness",
                    harness,
                    "--json",
                ]
            )
            == 0
        )
        _json(capsys)
    assert (
        main(
            [
                "bootstrap",
                "--harness",
                harness,
                "--repo",
                str(project),
                "--reconcile-owned",
                "--json",
            ]
        )
        == 0
    )
    repaired = _json(capsys)
    assert projection.is_symlink()
    assert any(
        action["kind"] == "link" for action in repaired["receipt"]["applied_actions"]
    )

    assert (
        main(
            [
                "release",
                borrow_id,
                "--repo",
                str(project),
                "--harness",
                harness,
                "--json",
            ]
        )
        == 0
    )
    _json(capsys)
    assert not projection.exists()

    assert (
        main(
            [
                "adopt",
                first_trial["lease"]["lease_id"],
                "--repo",
                str(project),
                "--evaluation-claim",
                "acceptance:v1",
                "--json",
            ]
        )
        == 0
    )
    first_adoption = _json(capsys)
    first_lock_id = first_adoption["plan"]["proposed_lock"]["lock_id"]
    assert projection.is_symlink()

    candidate.joinpath("SKILL.md").write_text(
        "---\nname: journey\ndescription: Acceptance skill.\n---\n\n"
        "Version two: flawed update.\n",
        encoding="utf-8",
    )
    _git(source, "add", ".")
    _git(source, "commit", "-m", "failing version two")
    next_exit.append(9)
    assert (
        main(
            [
                "update",
                "try",
                "journey",
                "--task-file",
                str(task),
                "--repo",
                str(project),
                "--harness",
                harness,
                "--model",
                "model-v1",
                "--json",
            ]
        )
        == 9
    )
    failed_update = _json(capsys)
    assert (
        main(
            [
                "adopt",
                failed_update["lease"]["lease_id"],
                "--repo",
                str(project),
                "--json",
            ]
        )
        == 2
    )
    assert "zero-exit trial" in capsys.readouterr().err

    candidate.joinpath("SKILL.md").write_text(
        "---\nname: journey\ndescription: Acceptance skill.\n---\n\n"
        "Version three: check rollback and concurrent locks.\n",
        encoding="utf-8",
    )
    _git(source, "add", ".")
    _git(source, "commit", "-m", "passing version three")
    next_exit.append(0)
    assert (
        main(
            [
                "update",
                "try",
                "journey",
                "--task-file",
                str(task),
                "--repo",
                str(project),
                "--harness",
                harness,
                "--model",
                "model-v1",
                "--json",
            ]
        )
        == 0
    )
    passing_update = _json(capsys)
    assert (
        main(
            [
                "adopt",
                passing_update["lease"]["lease_id"],
                "--repo",
                str(project),
                "--json",
            ]
        )
        == 0
    )
    promoted = _json(capsys)
    assert promoted["adoption"]["evaluation_claim_ids"] == []

    assert (
        main(
            [
                "health",
                "--repo",
                str(project),
                "--harness",
                harness,
                "--model",
                "model-v2",
                "--json",
            ]
        )
        == 0
    )
    health = _json(capsys)
    assert health["skills"][0]["evidence_drift"] == ["model"]
    assert (
        main(
            [
                "distill",
                "journey",
                "--repo",
                str(project),
                "--harness",
                harness,
                "--json",
            ]
        )
        == 0
    )
    assert _json(capsys)["mutation"] == "none"

    assert (
        main(
            [
                "rollback",
                "journey",
                "--repo",
                str(project),
                "--harness",
                harness,
                "--reason",
                "acceptance rollback",
                "--json",
            ]
        )
        == 0
    )
    rollback = _json(capsys)
    assert rollback["plan"]["proposed_lock"]["lock_id"] == first_lock_id

    for action in ("disable", "enable", "deprecate", "retire"):
        assert (
            main(
                [
                    action,
                    "journey",
                    "--repo",
                    str(project),
                    "--harness",
                    harness,
                    "--reason",
                    f"acceptance {action}",
                    "--json",
                ]
            )
            == 0
        )
        _json(capsys)

    final_lock = read_surface_lock(surface_id(project, harness))
    assert final_lock is not None and final_lock.adoption_ids == ()
    assert current_status(final_lock.surface_id, "journey")["status"] == "retired"
    assert len(AdoptionStore().list()) == 2
    assert not projection.exists()
    assert ambient.joinpath("SKILL.md").read_bytes() == ambient_before
    if foreign is not None:
        assert foreign.joinpath("SKILL.md").read_bytes() == foreign_before
