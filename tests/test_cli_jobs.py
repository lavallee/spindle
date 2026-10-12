"""Job-scoped lease grants, release-by-job, and TTL crash reconciliation."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from spindle.cli import main
from spindle.leases import LeaseStore
from spindle.lifecycle import (
    Lease,
    LifecycleError,
    PackageRevision,
    read_surface_lock,
    surface_id,
)
from spindle.startup import run_startup

JOB = "20260817T010203_abc123"


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
        f"---\nname: {name}\ndescription: Do {name} work.\n---\n\n"
        f"Perform {name} carefully.\n",
        encoding="utf-8",
    )
    return skill


def test_lease_job_id_round_trips_and_absent_job_id_keeps_identity(tmp_path):
    skill = _skill(tmp_path / "source")
    revision = PackageRevision.from_path(
        "review-package", "local", skill, skills=(("review", skill),)
    )
    base = dict(
        skill="review",
        package_digest=revision.content_digest,
        skill_digest=dict(revision.skill_digests)["review"],
        source=revision.source,
        source_path=str(skill.resolve()),
        surface_id=surface_id(tmp_path / "repo", "codex"),
        harness="codex",
        kind="borrow",
        scope="repo",
        starts_at="2026-07-31T10:00:00Z",
        expires_at="2026-07-31T12:00:00Z",
        posture="read-only",
    )

    plain = Lease(**base)
    keyed = Lease(**base, job_id=JOB)

    assert "job_id" not in plain.to_dict()
    assert plain == Lease.from_dict(plain.to_dict())
    assert keyed.to_dict()["job_id"] == JOB
    assert keyed == Lease.from_dict(keyed.to_dict())
    assert keyed.lease_id != plain.lease_id
    with pytest.raises(LifecycleError, match="job_id"):
        Lease(**base, job_id="bad id with spaces")


def test_job_grant_leases_each_skill_and_release_cleans_only_job_projections(
    tmp_path, monkeypatch, capsys
):
    _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    review = _skill(tmp_path / "candidates", "review")
    migrate = _skill(tmp_path / "candidates", "migrate")
    ambient = _skill(repo / ".agents" / "skills", "ambient")
    ambient_before = ambient.joinpath("SKILL.md").read_bytes()

    assert (
        main(
            [
                "job",
                "grant",
                "--for-job",
                JOB,
                "--skill",
                str(review),
                "--skill",
                str(migrate),
                "--repo",
                str(repo),
                "--harness",
                "codex",
                "--json",
            ]
        )
        == 0
    )
    granted = json.loads(capsys.readouterr().out)
    lock = read_surface_lock(surface_id(repo, "codex"))
    store = LeaseStore()

    assert granted["for_job"] == JOB
    assert [entry["action"] for entry in granted["skills"]] == ["granted", "granted"]
    assert lock is not None and len(lock.lease_ids) == 2
    for entry in granted["skills"]:
        lease = store.get(entry["lease_id"])
        assert lease.job_id == JOB
        assert Path(entry["projection_path"]).is_symlink()
    stored = json.loads(
        next(iter((tmp_path / "state" / "lease-receipts").glob("*.json"))).read_text(
            encoding="utf-8"
        )
    )
    assert stored["job_id"] == JOB

    # A retry of the same grant is idempotent per skill.
    assert (
        main(
            [
                "job",
                "grant",
                "--for-job",
                JOB,
                "--skill",
                str(review),
                "--repo",
                str(repo),
                "--harness",
                "codex",
                "--json",
            ]
        )
        == 0
    )
    regrant = json.loads(capsys.readouterr().out)
    assert regrant["skills"][0]["action"] == "already-granted"
    refreshed = read_surface_lock(surface_id(repo, "codex"))
    assert refreshed is not None and len(refreshed.lease_ids) == 2

    assert main(["job", "status", "--for-job", JOB, "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert {entry["state"] for entry in status["leases"]} == {"active"}

    assert main(["job", "release", "--for-job", JOB, "--json"]) == 0
    released = json.loads(capsys.readouterr().out)
    final = read_surface_lock(surface_id(repo, "codex"))

    assert [entry["action"] for entry in released["leases"]] == [
        "released",
        "released",
    ]
    assert all(entry["event_id"] for entry in released["leases"])
    assert final is not None and final.lease_ids == ()
    assert not (repo / ".agents" / "skills" / "review").exists()
    assert not (repo / ".agents" / "skills" / "migrate").exists()
    assert ambient.joinpath("SKILL.md").read_bytes() == ambient_before

    # Releasing again, and releasing an unknown job, are safe no-ops.
    assert main(["job", "release", "--for-job", JOB, "--json"]) == 0
    again = json.loads(capsys.readouterr().out)
    assert {entry["action"] for entry in again["leases"]} == {"already-released"}
    assert main(["job", "release", "--for-job", "no-such-job", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["leases"] == []


def test_job_grant_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    review = _skill(tmp_path / "candidates", "review")

    assert (
        main(
            [
                "job",
                "grant",
                "--for-job",
                JOB,
                "--skill",
                str(review),
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
    planned = json.loads(capsys.readouterr().out)

    assert planned["skills"][0]["action"] == "would-grant"
    assert planned["skills"][0]["plan"]["lease"]["job_id"] == JOB
    assert not (tmp_path / "state").exists()
    assert not (repo / ".agents" / "skills" / "review").exists()


def test_job_grant_continues_past_blocked_skill_and_reports_failure(
    tmp_path, monkeypatch, capsys
):
    _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    review = _skill(tmp_path / "candidates", "review")
    migrate = _skill(tmp_path / "candidates", "migrate")
    foreign = _skill(repo / ".agents" / "skills", "migrate")
    foreign_before = foreign.joinpath("SKILL.md").read_bytes()

    result = main(
        [
            "job",
            "grant",
            "--for-job",
            JOB,
            "--skill",
            str(migrate),
            "--skill",
            str(review),
            "--repo",
            str(repo),
            "--harness",
            "codex",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    by_skill = {entry["skill"]: entry for entry in payload["skills"]}
    lock = read_surface_lock(surface_id(repo, "codex"))

    assert result == 2
    assert by_skill[str(migrate)]["action"] == "blocked"
    assert by_skill["review"]["action"] == "granted"
    assert lock is not None and len(lock.lease_ids) == 1
    assert foreign.joinpath("SKILL.md").read_bytes() == foreign_before

    # Job end still cleans whatever the partial grant produced.
    assert main(["job", "release", "--for-job", JOB, "--json"]) == 0
    released = json.loads(capsys.readouterr().out)
    assert [entry["action"] for entry in released["leases"]] == ["released"]


def test_startup_reconciliation_expires_stale_job_leases(
    tmp_path, monkeypatch, capsys
):
    _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    review = _skill(tmp_path / "candidates", "review")

    assert (
        main(
            [
                "job",
                "grant",
                "--for-job",
                JOB,
                "--skill",
                str(review),
                "--until",
                "30m",
                "--repo",
                str(repo),
                "--harness",
                "codex",
                "--json",
            ]
        )
        == 0
    )
    granted = json.loads(capsys.readouterr().out)
    lease_id = granted["skills"][0]["lease_id"]
    projection = repo / ".agents" / "skills" / "review"
    assert projection.is_symlink()

    # The job dies without releasing; the next startup reconciles the surface.
    result = run_startup(
        repo,
        "codex",
        reconcile_owned=True,
        now=datetime.now(tz=UTC) + timedelta(hours=2),
    )

    refreshed = read_surface_lock(surface_id(repo, "codex"))
    events = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (tmp_path / "state" / "lease-events").glob("*.json")
    ]

    assert result.receipt.expired_lease_ids == (lease_id,)
    assert not projection.exists()
    assert refreshed is not None and refreshed.lease_ids == ()
    assert any(
        event["event"] == "expired" and event["lease_id"] == lease_id
        for event in events
    )

    assert main(["job", "status", "--for-job", JOB, "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["leases"][0]["state"] == "released"
    assert status["leases"][0]["attached"] is False

    assert main(["job", "release", "--for-job", JOB, "--json"]) == 0
    cleanup = json.loads(capsys.readouterr().out)
    assert {entry["action"] for entry in cleanup["leases"]} == {"already-released"}
