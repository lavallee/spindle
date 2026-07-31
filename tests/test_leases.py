"""Immutable lease grants, desired-state overlays, and expiry reconciliation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from spindle.inventory import DiscoveryRoot
from spindle.leases import (
    LeaseStore,
    effective_lock_at,
    lock_with_lease,
    parse_expiry,
)
from spindle.lifecycle import (
    ExpectedProjection,
    Lease,
    LifecycleError,
    OwnershipRecord,
    OwnershipStore,
    PackageRevision,
    SurfaceLock,
    digest_path,
    read_surface_lock,
    surface_id,
    write_surface_lock,
)
from spindle.startup import run_startup


def _skill(root: Path, name: str = "review") -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Review work.\n---\n\nReview.\n",
        encoding="utf-8",
    )
    return skill


def _lease(repo: Path, skill: Path, *, expires: str) -> Lease:
    revision = PackageRevision.from_path(
        "review-package",
        "local",
        skill,
        skills=(("review", skill),),
    )
    return Lease(
        skill="review",
        package_digest=revision.content_digest,
        skill_digest=dict(revision.skill_digests)["review"],
        source=revision.source,
        source_path=str(skill.resolve()),
        surface_id=surface_id(repo, "codex"),
        harness="codex",
        kind="borrow",
        scope="repo",
        starts_at="2026-07-31T10:00:00Z",
        expires_at=expires,
        posture="read-only",
    )


def _base_lock(repo: Path) -> SurfaceLock:
    return SurfaceLock(
        surface_id=surface_id(repo, "codex"),
        surface_name=repo.name,
        repo_path=str(repo.resolve()),
        harness="codex",
        binding_coordinate="binding:test",
        projections=(),
    )


def _projection(repo: Path, lease: Lease) -> ExpectedProjection:
    return ExpectedProjection(
        skill=lease.skill,
        projection_path=str((repo / ".agents" / "skills" / lease.skill).absolute()),
        source_path=lease.source_path,
        source_digest=lease.skill_digest,
        package_digest=lease.package_digest,
        authority=f"lease:{lease.lease_id}",
    )


def test_lease_store_is_content_addressed_and_tampering_fails(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    lease = _lease(repo, _skill(tmp_path / "source"), expires="2026-07-31T12:00:00Z")
    store = LeaseStore(tmp_path / "leases")

    path = store.record(lease)

    assert store.get(lease.lease_id) == lease
    assert store.record(lease) == path
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["posture"] = "full"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(LifecycleError, match="lease_id"):
        store.get(lease.lease_id)


def test_effective_lock_keeps_active_and_excludes_expired_lease(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    skill = _skill(tmp_path / "source")
    active = _lease(repo, skill, expires="2026-07-31T12:00:00Z")
    expired = _lease(repo, skill, expires="2026-07-31T11:00:00Z")
    store = LeaseStore(tmp_path / "leases")
    store.record(active)
    store.record(expired)
    active_lock = lock_with_lease(_base_lock(repo), active, _projection(repo, active))
    # Two same-name projections cannot coexist; exercise expiry independently.
    expired_lock = lock_with_lease(
        _base_lock(repo), expired, _projection(repo, expired)
    )
    moment = datetime(2026, 7, 31, 11, 30, tzinfo=UTC)

    kept, active_ids, expired_ids = effective_lock_at(
        active_lock, store=store, now=moment
    )
    removed, no_active, removed_ids = effective_lock_at(
        expired_lock, store=store, now=moment
    )

    assert kept == active_lock
    assert active_ids == (active.lease_id,)
    assert expired_ids == ()
    assert removed.projections == ()
    assert removed.lease_ids == ()
    assert no_active == ()
    assert removed_ids == (expired.lease_id,)


def test_startup_expires_lease_removes_only_owned_projection_and_records_event(
    tmp_path,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = _skill(tmp_path / "source")
    foreign = _skill(repo / ".agents" / "skills", "ambient")
    foreign_digest = digest_path(foreign)
    lease = _lease(repo, source, expires="2026-07-31T11:00:00Z")
    lease_store = LeaseStore(tmp_path / "leases")
    lease_store.record(lease)
    projection = _projection(repo, lease)
    projection_path = Path(projection.projection_path)
    projection_path.parent.mkdir(parents=True, exist_ok=True)
    projection_path.symlink_to(source)
    lock = lock_with_lease(_base_lock(repo), lease, projection)
    lock_root = tmp_path / "locks"
    write_surface_lock(lock, root=lock_root)
    ownership = OwnershipStore(
        receipt_root=tmp_path / "ownership-receipts",
        index_root=tmp_path / "ownership",
    )
    ownership.record(
        OwnershipRecord(
            surface_id=lock.surface_id,
            surface_name=lock.surface_name,
            harness=lock.harness,
            skill=lease.skill,
            projection_path=str(projection_path.absolute()),
            source_path=str(source.resolve()),
            source_digest=lease.skill_digest,
            package_digest=lease.package_digest,
            creation_receipt_id=f"lease:{lease.lease_id}",
        )
    )

    result = run_startup(
        repo,
        "codex",
        reconcile_owned=True,
        ownership_store=ownership,
        roots=(DiscoveryRoot("repo", repo / ".agents" / "skills", 10),),
        lease_store=lease_store,
        surface_lock_root=lock_root,
        plan_root=tmp_path / "plans",
        receipt_root=tmp_path / "startup-receipts",
        observation_file=tmp_path / "observations.jsonl",
        mutex_root=tmp_path / "mutex",
        lease_event_root=tmp_path / "events",
        now=datetime(2026, 7, 31, 11, 30, tzinfo=UTC),
    )

    refreshed = read_surface_lock(lock.surface_id, root=lock_root)
    assert result.receipt.expired_lease_ids == (lease.lease_id,)
    assert result.receipt.active_lease_ids == ()
    assert result.receipt.decision == "warn"  # unrelated foreign skill preserved
    assert not projection_path.exists()
    assert digest_path(foreign) == foreign_digest
    assert refreshed is not None and refreshed.lease_ids == ()
    assert len(list((tmp_path / "events").glob("*.json"))) == 1


def test_native_resume_reports_restart_required_for_expired_projection(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = _skill(tmp_path / "source")
    lease = _lease(repo, source, expires="2026-07-31T11:00:00Z")
    store = LeaseStore(tmp_path / "leases")
    store.record(lease)
    projection = _projection(repo, lease)
    projection_path = Path(projection.projection_path)
    projection_path.parent.mkdir(parents=True)
    projection_path.symlink_to(source)
    lock = lock_with_lease(_base_lock(repo), lease, projection)
    ownership = OwnershipStore(
        receipt_root=tmp_path / "ownership-receipts",
        index_root=tmp_path / "ownership",
    )
    ownership.record(
        OwnershipRecord(
            surface_id=lock.surface_id,
            surface_name=lock.surface_name,
            harness=lock.harness,
            skill=lease.skill,
            projection_path=str(projection_path.absolute()),
            source_path=str(source.resolve()),
            source_digest=lease.skill_digest,
            package_digest=lease.package_digest,
            creation_receipt_id=f"lease:{lease.lease_id}",
        )
    )

    result = run_startup(
        repo,
        "codex",
        lock=lock,
        already_discovered=True,
        event_source="compact",
        ownership_store=ownership,
        roots=(DiscoveryRoot("repo", repo / ".agents" / "skills", 10),),
        lease_store=store,
        plan_root=tmp_path / "plans",
        receipt_root=tmp_path / "receipts",
        observation_file=tmp_path / "observations.jsonl",
        mutex_root=tmp_path / "mutex",
        now=datetime(2026, 7, 31, 11, 30, tzinfo=UTC),
    )

    assert result.receipt.decision == "restart-required"
    assert result.receipt.expired_lease_ids == (lease.lease_id,)
    assert projection_path.is_symlink()


def test_parse_expiry_accepts_duration_and_rejects_past():
    now = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)
    assert parse_expiry("2h", now=now) == datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    with pytest.raises(LifecycleError, match="future"):
        parse_expiry("2026-07-31T09:00:00Z", now=now)
