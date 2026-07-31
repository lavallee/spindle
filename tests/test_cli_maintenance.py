"""CLI coverage for durable adoption and maintenance transitions."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

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


def _fixture(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path, str]:
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
        "Check correctness and rollback. Version one.\n",
        encoding="utf-8",
    )
    source.joinpath("LICENSE").write_text("MIT fixture\n", encoding="utf-8")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "version one")
    task = tmp_path / "task.md"
    task.write_text("Review this migration.\n", encoding="utf-8")
    return project, source, task, _git(source, "rev-parse", "HEAD")


def _run_trial(
    project: Path,
    source: Path,
    task: Path,
    monkeypatch,
    capsys,
    *,
    exit_code: int = 0,
) -> dict:
    real_run = subprocess.run

    def fake_run(command, **kwargs):
        if command[0] != "codex":
            return real_run(command, **kwargs)
        cwd = kwargs["cwd"]
        check = kwargs["check"]
        capture_output = kwargs["capture_output"]
        text = kwargs["text"]
        assert command[0] == "codex"
        assert cwd == project.resolve()
        assert check is False and capture_output is True and text is True
        return SimpleNamespace(returncode=exit_code, stdout="reviewed\n", stderr="")

    monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)
    result = main(
        [
            "try",
            f"git:{source}@main#remote-demo",
            "--task-file",
            str(task),
            "--repo",
            str(project),
            "--harness",
            "codex",
            "--model",
            "gpt-test",
            "--json",
        ]
    )
    assert result == exit_code
    return json.loads(capsys.readouterr().out)


def test_failed_trial_cannot_be_adopted(tmp_path, monkeypatch, capsys):
    project, source, task, _commit = _fixture(tmp_path, monkeypatch)
    trial = _run_trial(
        project, source, task, monkeypatch, capsys, exit_code=5
    )

    assert (
        main(
            [
                "adopt",
                trial["lease"]["lease_id"],
                "--repo",
                str(project),
                "--json",
            ]
        )
        == 2
    )
    assert "requires a zero-exit trial" in capsys.readouterr().err
    lock = read_surface_lock(surface_id(project, "codex"))
    assert lock is not None and lock.adoption_ids == ()
    assert AdoptionStore().list() == ()


def test_adopt_update_rollback_and_retire_exact_owned_projection(
    tmp_path, monkeypatch, capsys
):
    project, source, task, first_commit = _fixture(tmp_path, monkeypatch)
    ambient = project / ".agents" / "skills" / "ambient"
    ambient.mkdir(parents=True)
    ambient.joinpath("SKILL.md").write_text(
        "---\nname: ambient\ndescription: Foreign.\n---\n\nKeep me.\n",
        encoding="utf-8",
    )
    ambient_before = ambient.joinpath("SKILL.md").read_bytes()
    trial = _run_trial(project, source, task, monkeypatch, capsys)
    lease_id = trial["lease"]["lease_id"]

    assert (
        main(
            [
                "adopt",
                lease_id,
                "--repo",
                str(project),
                "--owner",
                "maintainers",
                "--evaluation-claim",
                "eval:v1",
                "--json",
            ]
        )
        == 0
    )
    adopted = json.loads(capsys.readouterr().out)
    first_adoption = adopted["adoption"]
    first_lock_id = adopted["plan"]["proposed_lock"]["lock_id"]
    projection = project / ".agents" / "skills" / "remote-demo"
    assert adopted["action"] == "adopted"
    assert adopted["plan"]["distribution_change"] is None
    assert adopted["plan"]["channel_change"] is None
    assert first_adoption["source"]["revision"] == first_commit
    assert first_adoption["update_reference"] == f"git:{source}@main#remote-demo"
    assert projection.is_symlink()

    source.joinpath("skills/remote-demo/SKILL.md").write_text(
        "---\nname: remote-demo\ndescription: Review migrations.\n---\n\n"
        "Check correctness, rollback, and locks. Version two.\n",
        encoding="utf-8",
    )
    _git(source, "add", ".")
    _git(source, "commit", "-m", "version two")
    second_commit = _git(source, "rev-parse", "HEAD")

    assert (
        main(
            [
                "update",
                "plan",
                "--repo",
                str(project),
                "--harness",
                "codex",
                "--json",
            ]
        )
        == 0
    )
    update_plan = json.loads(capsys.readouterr().out)
    candidate = update_plan["updates"][0]
    assert candidate["changed"] is True
    assert candidate["candidate"]["source_revision"] == second_commit
    assert candidate["candidate"]["evaluation_claim_ids"] == []
    assert candidate["evaluation_inheritance"] == "none"

    real_run = subprocess.run

    def fake_update_run(command, **kwargs):
        if command[0] != "codex":
            return real_run(command, **kwargs)
        candidate_links = list(
            (project / ".agents" / "skills").glob("remote-demo--candidate-*")
        )
        assert projection.is_symlink()
        assert len(candidate_links) == 1 and candidate_links[0].is_symlink()
        assert "Use $remote-demo--candidate-" in command[-1]
        return SimpleNamespace(returncode=0, stdout="compared\n", stderr="")

    monkeypatch.setattr(cli_mod.subprocess, "run", fake_update_run)
    assert (
        main(
            [
                "update",
                "try",
                "remote-demo",
                "--task-file",
                str(task),
                "--repo",
                str(project),
                "--harness",
                "codex",
                "--model",
                "gpt-test",
                "--json",
            ]
        )
        == 0
    )
    update_trial = json.loads(capsys.readouterr().out)
    assert update_trial["lease"]["kind"] == "update"
    assert projection.is_symlink()
    assert not list((project / ".agents" / "skills").glob("*--candidate-*"))

    assert (
        main(
            [
                "adopt",
                update_trial["lease"]["lease_id"],
                "--repo",
                str(project),
                "--reason",
                "update trial passed",
                "--json",
            ]
        )
        == 0
    )
    promoted = json.loads(capsys.readouterr().out)
    second_adoption = promoted["adoption"]
    assert promoted["action"] == "updated"
    assert second_adoption["previous_adoption_id"] == first_adoption["adoption_id"]
    assert second_adoption["evaluation_claim_ids"] == []
    assert second_adoption["source"]["revision"] == second_commit

    assert (
        main(
            [
                "health",
                "--repo",
                str(project),
                "--harness",
                "codex",
                "--model",
                "gpt-changed",
                "--source-revision",
                first_commit,
                "--package-digest",
                first_adoption["package_digest"],
                "--json",
            ]
        )
        == 0
    )
    health = json.loads(capsys.readouterr().out)["skills"][0]
    assert health["source_freshness"] == "changed"
    assert health["evidence_drift"] == [
        "model",
        "package_digest",
        "source_revision",
    ]
    assert "behavioral-contribution-unassessed" in health["findings"]

    assert (
        main(
            [
                "rollback",
                "remote-demo",
                "--repo",
                str(project),
                "--harness",
                "codex",
                "--reason",
                "regression",
                "--json",
            ]
        )
        == 0
    )
    rolled_back = json.loads(capsys.readouterr().out)
    assert rolled_back["plan"]["proposed_lock"]["lock_id"] == first_lock_id

    for action in ("disable", "enable", "deprecate", "retire"):
        assert (
            main(
                [
                    action,
                    "remote-demo",
                    "--repo",
                    str(project),
                    "--harness",
                    "codex",
                    "--reason",
                    f"test {action}",
                    "--json",
                ]
            )
            == 0
        )
        json.loads(capsys.readouterr().out)

    final_lock = read_surface_lock(surface_id(project, "codex"))
    assert final_lock is not None and final_lock.adoption_ids == ()
    assert not projection.exists()
    assert ambient.joinpath("SKILL.md").read_bytes() == ambient_before
    assert current_status(final_lock.surface_id, "remote-demo")["status"] == "retired"
    assert len(AdoptionStore().list()) == 2
    assert len(list((tmp_path / "state" / "maintenance-events").glob("*.json"))) == 7
