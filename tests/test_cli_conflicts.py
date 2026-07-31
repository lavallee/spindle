"""CLI lifecycle for exact foreign-conflict decisions."""

from __future__ import annotations

import json
from pathlib import Path

from spindle.cli import main
from spindle.lifecycle import surface_id


def _skill(root: Path, name: str, body: str) -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Conflict fixture.\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return skill


def test_allow_list_and_revoke_are_exact_planned_and_historical(
    tmp_path, monkeypatch, capsys
):
    state = tmp_path / "state"
    home = tmp_path / "home"
    monkeypatch.setenv("SPINDLE_HOME", str(state))
    monkeypatch.setenv("HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    project = _skill(repo / ".agents" / "skills", "review", "project")
    user = _skill(home / ".agents" / "skills", "review", "user")
    common = ["--harness", "codex", "--repo", str(repo), "--json"]

    assert (
        main(
            [
                "conflict",
                "allow",
                "review",
                "--path",
                str(project),
                "--reason",
                "Both ambient fixtures are intentional.",
                *common,
                "--dry-run",
            ]
        )
        == 0
    )
    dry = json.loads(capsys.readouterr().out)
    assert dry["action"] == "would-allow"
    lock_path = (
        state
        / "surface-locks"
        / (surface_id(repo, "codex").removeprefix("sha256:") + ".json")
    )
    assert not lock_path.exists()
    assert not (state / "conflict-receipts").exists()

    decisions = []
    for path in (project, user):
        assert (
            main(
                [
                    "conflict",
                    "allow",
                    "review",
                    "--path",
                    str(path),
                    "--reason",
                    "Both ambient fixtures are intentional.",
                    *common,
                ]
            )
            == 0
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["action"] == "allowed"
        decisions.append(payload["decision"]["decision_id"])

    assert main(["conflict", "list", *common]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert {item["decision_id"] for item in listed["decisions"]} == set(decisions)

    assert (
        main(
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
        == 0
    )
    allowed = json.loads(capsys.readouterr().out)
    assert allowed["receipt"]["decision"] == "warn"
    assert not allowed["receipt"]["foreign_conflicts"]

    assert (
        main(
            [
                "conflict",
                "revoke",
                decisions[0],
                *common,
                "--dry-run",
            ]
        )
        == 0
    )
    preview = json.loads(capsys.readouterr().out)
    assert preview["action"] == "would-revoke"

    assert main(["conflict", "revoke", decisions[0], *common]) == 0
    revoked = json.loads(capsys.readouterr().out)
    assert revoked["action"] == "revoked"
    assert (
        state / "conflict-receipts" / f"{decisions[0].removeprefix('sha256:')}.json"
    ).is_file()

    assert (
        main(
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
        == 2
    )
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["receipt"]["decision"] == "blocked"
    assert project.is_dir()
    assert user.is_dir()
