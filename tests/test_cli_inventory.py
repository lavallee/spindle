"""CLI coverage for effective inventory, why, diff, and startup doctor."""

from __future__ import annotations

import json
from pathlib import Path

from spindle.cli import main
from spindle.lifecycle import (
    ExpectedProjection,
    OwnershipRecord,
    OwnershipStore,
    SurfaceLock,
    digest_path,
    surface_id,
    write_surface_lock,
)


def _skill(root: Path, name: str) -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Exercise {name}.\n---\n\nUse evidence.\n",
        encoding="utf-8",
    )
    return skill


def _owned_projection(
    repo: Path,
    source: Path,
    name: str,
    *,
    expected: bool,
) -> Path:
    projection = repo / ".agents" / "skills" / name
    projection.parent.mkdir(parents=True, exist_ok=True)
    projection.symlink_to(source)
    digest = digest_path(source)
    sid = surface_id(repo, "codex")
    OwnershipStore().record(
        OwnershipRecord(
            surface_id=sid,
            surface_name=repo.name,
            harness="codex",
            skill=name,
            projection_path=str(projection.absolute()),
            source_path=str(source.resolve()),
            source_digest=digest,
            package_digest=digest,
            creation_receipt_id="binding:test",
        )
    )
    if expected:
        write_surface_lock(
            SurfaceLock(
                surface_id=sid,
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
        )
    return projection


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def test_inventory_and_why_report_exact_owned_projection(tmp_path, monkeypatch, capsys):
    _isolate(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    source = _skill(tmp_path / "sources", "review")
    _owned_projection(repo, source, "review", expected=True)

    assert (
        main(
            [
                "inventory",
                "--effective",
                "--repo",
                str(repo),
                "--harness",
                "codex",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    review = [entry for entry in payload["entries"] if entry["name"] == "review"]
    assert review[0]["state"] == "expected-owned"
    assert payload["lock_id"].startswith("sha256:")

    assert (
        main(
            [
                "why",
                "review",
                "--effective",
                "--repo",
                str(repo),
                "--harness",
                "codex",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "expected-owned" in output
    assert "ownership" in output
    assert "content" in output


def test_diff_strict_blocks_same_name_foreign_scope(tmp_path, monkeypatch, capsys):
    _isolate(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    source = _skill(tmp_path / "sources", "review")
    _owned_projection(repo, source, "review", expected=True)
    user_source = _skill(tmp_path / "foreign", "review")
    user_projection = tmp_path / "home" / ".agents" / "skills" / "review"
    user_projection.parent.mkdir(parents=True)
    user_projection.symlink_to(user_source)

    result = main(
        [
            "diff",
            "--effective",
            "--repo",
            str(repo),
            "--harness",
            "codex",
            "--strict",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 2
    assert any(
        entry["path"] == str(user_projection.absolute())
        and entry["state"] == "conflicting"
        for entry in payload["differences"]
    )
    assert user_projection.is_symlink()


def test_startup_doctor_dry_run_then_removes_only_stale_owned(
    tmp_path, monkeypatch, capsys
):
    _isolate(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    source = _skill(tmp_path / "sources", "stale")
    stale = _owned_projection(repo, source, "stale", expected=False)
    foreign_source = _skill(tmp_path / "foreign", "foreign")
    foreign = repo / ".agents" / "skills" / "foreign"
    foreign.symlink_to(foreign_source)

    dry_result = main(
        [
            "doctor",
            "--startup",
            "--repo",
            str(repo),
            "--harness",
            "codex",
            "--reconcile-owned",
            "--dry-run",
            "--json",
        ]
    )
    dry_payload = json.loads(capsys.readouterr().out)
    assert dry_result == 2
    assert dry_payload["actions"][0]["action"] == "would-remove"
    assert stale.is_symlink()
    assert foreign.is_symlink()

    result = main(
        [
            "doctor",
            "--startup",
            "--repo",
            str(repo),
            "--harness",
            "codex",
            "--reconcile-owned",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["actions"][0]["action"] == "removed"
    assert not stale.is_symlink()
    assert foreign.is_symlink()


def test_here_uses_current_directory(tmp_path, monkeypatch, capsys):
    _isolate(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    monkeypatch.chdir(repo)

    assert main(["inventory", "--here", "--harness", "codex", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["repo_path"] == str(repo.resolve())
