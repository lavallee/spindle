"""CLI lifecycle coverage for inspect, borrow, release, and disposable try."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from spindle import cli as cli_mod
from spindle.cli import main
from spindle.lifecycle import read_surface_lock, surface_id


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


def _skill(root: Path, name: str = "review") -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Review migrations.\n---\n\n"
        "Check correctness and rollback.\n",
        encoding="utf-8",
    )
    return skill


def test_inspect_and_borrow_dry_run_are_read_only(tmp_path, monkeypatch, capsys):
    _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    skill = _skill(tmp_path / "candidate")
    common = [
        str(skill),
        "--repo",
        str(repo),
        "--harness",
        "codex",
        "--json",
    ]

    assert main(["inspect", *common, "--for", "review this migration"]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["package_facts"]["skill"] == "review"
    assert inspected["fit_analysis"]["behavioral_fit"] == "unassessed"
    assert not (tmp_path / "state").exists()

    assert main(["borrow", *common, "--until", "2h", "--dry-run"]) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["action"] == "would-borrow"
    assert planned["plan"]["lease"]["posture"] == "read-only"
    assert not (tmp_path / "state").exists()
    assert not (repo / ".agents" / "skills" / "review").exists()


def test_borrow_persists_exact_lease_and_release_cleans_only_owned_projection(
    tmp_path, monkeypatch, capsys
):
    _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    skill = _skill(tmp_path / "candidate")
    ambient = _skill(repo / ".agents" / "skills", "ambient")
    ambient_before = ambient.joinpath("SKILL.md").read_bytes()

    assert (
        main(
            [
                "borrow",
                str(skill),
                "--until",
                "2h",
                "--repo",
                str(repo),
                "--harness",
                "codex",
                "--json",
            ]
        )
        == 0
    )
    borrowed = json.loads(capsys.readouterr().out)
    lease_id = borrowed["lease"]["lease_id"]
    projection = repo / ".agents" / "skills" / "review"
    lock = read_surface_lock(surface_id(repo, "codex"))

    assert borrowed["action"] == "borrowed"
    assert borrowed["startup"]["lease_status"]["active"] == [lease_id]
    assert borrowed["activation_receipt_id"]
    assert projection.is_symlink()
    assert lock is not None and lock.lease_ids == (lease_id,)
    assert lock.projections[-1].authority == f"lease:{lease_id}"

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
    next_session = json.loads(capsys.readouterr().out)
    assert next_session["receipt"]["lease_status"]["active"] == [lease_id]
    assert next_session["receipt"]["expected_inventory_id"] == (
        next_session["receipt"]["observed_inventory_id"]
    )

    assert (
        main(
            [
                "release",
                lease_id,
                "--repo",
                str(repo),
                "--harness",
                "codex",
                "--dry-run",
                "--json",
            ]
        )
        == 0
    )
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["action"] == "would-release"
    assert projection.is_symlink()

    assert (
        main(
            [
                "release",
                lease_id,
                "--repo",
                str(repo),
                "--harness",
                "codex",
                "--json",
            ]
        )
        == 0
    )
    released = json.loads(capsys.readouterr().out)
    refreshed = read_surface_lock(surface_id(repo, "codex"))

    assert released["action"] == "released"
    assert released["event"]["event"] == "released"
    assert not projection.exists()
    assert refreshed is not None and refreshed.lease_ids == ()
    assert ambient.joinpath("SKILL.md").read_bytes() == ambient_before
    assert list((tmp_path / "state" / "lease-receipts").glob("*.json"))


def test_foreign_same_name_blocks_borrow_without_writes(tmp_path, monkeypatch, capsys):
    _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    candidate = _skill(tmp_path / "candidate")
    foreign = _skill(repo / ".agents" / "skills")
    before = foreign.joinpath("SKILL.md").read_bytes()

    result = main(
        [
            "borrow",
            str(candidate),
            "--until",
            "2h",
            "--repo",
            str(repo),
            "--harness",
            "codex",
            "--json",
        ]
    )

    assert result == 2
    assert "borrow blocked" in capsys.readouterr().err
    assert foreign.joinpath("SKILL.md").read_bytes() == before
    assert not (tmp_path / "state").exists()


def test_try_runs_read_only_adapter_and_always_releases_session_lease(
    tmp_path, monkeypatch, capsys
):
    _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    skill = _skill(tmp_path / "candidate")
    task = tmp_path / "task.md"
    task.write_text("Review the migration in this repository.\n", encoding="utf-8")
    observed: list[tuple[list[str], Path, bool]] = []

    def fake_run(command, *, cwd, check, capture_output, text):
        observed.append((command, cwd, check))
        assert capture_output is True
        assert text is True
        return SimpleNamespace(returncode=7, stdout="done\n", stderr="")

    monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)

    result = main(
        [
            "try",
            str(skill),
            "--task-file",
            str(task),
            "--repo",
            str(repo),
            "--harness",
            "codex",
            "--model",
            "gpt-test",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    lease_id = payload["lease"]["lease_id"]
    lock = read_surface_lock(surface_id(repo, "codex"))

    assert result == 7
    assert observed and observed[0][0][:7] == [
        "codex",
        "-a",
        "never",
        "-s",
        "read-only",
        "-m",
        "gpt-test",
    ]
    assert "Use $review" in observed[0][0][-1]
    assert observed[0][1:] == (repo.resolve(), False)
    assert payload["cleanup"]["action"] == "released"
    assert payload["run_receipt"]["exit_code"] == 7
    assert payload["run_receipt"]["activation_receipt_id"]
    assert lock is not None and lease_id not in lock.lease_ids
    assert not (repo / ".agents" / "skills" / "review").exists()


def test_try_dry_run_does_not_cache_or_launch(tmp_path, monkeypatch, capsys):
    _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    skill = _skill(tmp_path / "candidate")
    task = tmp_path / "task.md"
    task.write_text("Review.\n", encoding="utf-8")

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("dry-run launched a harness")

    monkeypatch.setattr(cli_mod.subprocess, "run", should_not_run)

    assert (
        main(
            [
                "try",
                str(skill),
                "--task-file",
                str(task),
                "--repo",
                str(repo),
                "--harness",
                "claude",
                "--dry-run",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["action"] == "would-try"
    assert "--permission-mode" in payload["command_shape"]
    assert not (tmp_path / "state").exists()
