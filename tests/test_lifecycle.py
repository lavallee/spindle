"""Lifecycle record, content identity, cache, lock, and ownership tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from spindle.lifecycle import (
    ADOPTION_RECORD_SCHEMA,
    LEASE_SCHEMA,
    PACKAGE_REVISION_SCHEMA,
    AdoptionRecord,
    ConflictDecision,
    ConflictDecisionStore,
    ExpectedProjection,
    Lease,
    LifecycleError,
    OwnershipRecord,
    OwnershipStore,
    PackageRevision,
    SkillRef,
    SurfaceLock,
    cache_package,
    digest_path,
    read_surface_lock,
    surface_id,
    write_surface_lock,
)


def _skill(root: Path, name: str = "review", body: str = "Review carefully.\n") -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Review work.\n---\n\n{body}",
        encoding="utf-8",
    )
    return skill


def _expected(repo: Path, source: Path, name: str = "review") -> ExpectedProjection:
    digest = digest_path(source)
    return ExpectedProjection(
        skill=name,
        projection_path=str((repo / ".agents" / "skills" / name).absolute()),
        source_path=str(source.resolve()),
        source_digest=digest,
        package_digest=digest,
    )


def test_digest_path_is_deterministic_and_ignores_build_residue(tmp_path):
    skill = _skill(tmp_path)
    first = digest_path(skill)
    (skill / "__pycache__").mkdir()
    (skill / "__pycache__" / "noise.pyc").write_bytes(b"noise")

    assert digest_path(skill) == first

    (skill / "SKILL.md").write_text("changed\n", encoding="utf-8")
    assert digest_path(skill) != first


def test_digest_path_tracks_executable_bit_and_symlink_target(tmp_path):
    root = tmp_path / "package"
    root.mkdir()
    script = root / "check"
    script.write_text("ok\n", encoding="utf-8")
    link = root / "current"
    link.symlink_to("check")
    plain = digest_path(root)

    script.chmod(0o755)
    executable = digest_path(root)
    assert executable != plain

    link.unlink()
    link.symlink_to("other")
    assert digest_path(root) != executable


def test_package_revision_detects_editable_drift_with_same_version(tmp_path):
    root = tmp_path / "pkg"
    skill = _skill(root)
    first = PackageRevision.from_path(
        "review-package",
        "1.0.0",
        root,
        editable=True,
        skills=(("review", skill),),
    )
    (skill / "SKILL.md").write_text("new behavior\n", encoding="utf-8")
    second = PackageRevision.from_path(
        "review-package",
        "1.0.0",
        root,
        editable=True,
        skills=(("review", skill),),
    )

    assert first.version == second.version
    assert first.content_digest != second.content_digest
    assert first.skill_digests != second.skill_digests
    assert first.to_dict()["schema"] == PACKAGE_REVISION_SCHEMA
    assert PackageRevision.from_dict(first.to_dict()) == first


def test_package_cache_is_content_addressed_and_does_not_activate(tmp_path):
    root = tmp_path / "pkg"
    skill = _skill(root)
    revision = PackageRevision.from_path(
        "review-package",
        "1.0.0",
        root,
        skills=(("review", skill),),
    )
    cache = tmp_path / "cache"

    first = cache_package(revision, cache_root=cache)
    second = cache_package(revision, cache_root=cache)

    assert first == second
    assert digest_path(first) == revision.content_digest
    assert (
        first == cache / revision.content_digest.removeprefix("sha256:") / revision.name
    )
    assert not (tmp_path / ".agents" / "skills").exists()


def test_cache_rejects_source_changed_after_revision(tmp_path):
    root = tmp_path / "pkg"
    skill = _skill(root)
    revision = PackageRevision.from_path("review-package", "1", root)
    (skill / "SKILL.md").write_text("changed\n", encoding="utf-8")

    with pytest.raises(LifecycleError, match="source changed"):
        cache_package(revision, cache_root=tmp_path / "cache")


def test_skill_ref_rejects_short_or_unversioned_identity():
    with pytest.raises(LifecycleError, match="full sha256"):
        SkillRef("git", "owner/repo", "main", "abc")


def test_adoption_and_lease_records_are_independently_versioned(tmp_path):
    skill_path = _skill(tmp_path)
    digest = digest_path(skill_path)
    sid = surface_id(tmp_path / "repo", "codex")
    adoption = AdoptionRecord(
        adoption_id="adopt-1",
        skill="review",
        package_digest=digest,
        surface_id="surface-1",
        scope="repo",
        owner="team",
        adopted_at="2026-07-31T00:00:00Z",
        update_policy="trial",
        authority_ceiling="read-only",
    )
    lease = Lease(
        skill="review",
        package_digest=digest,
        skill_digest=digest,
        source=SkillRef("local", str(skill_path), digest, digest),
        source_path=str(skill_path.resolve()),
        surface_id=sid,
        harness="codex",
        kind="borrow",
        scope="repo",
        starts_at="2026-07-31T00:00:00Z",
        expires_at="2026-07-31T02:00:00Z",
        posture="read-only",
        agents=("parent",),
    )

    assert adoption.to_dict()["schema"] == ADOPTION_RECORD_SCHEMA
    assert lease.to_dict()["schema"] == LEASE_SCHEMA
    assert lease.to_dict()["agents"] == ["parent"]
    assert lease.lease_id.startswith("sha256:")
    assert AdoptionRecord.from_dict(adoption.to_dict()) == adoption
    assert Lease.from_dict(lease.to_dict()) == lease


def test_surface_lock_round_trips_and_has_stable_identity(tmp_path):
    repo = tmp_path / "repo"
    source = _skill(tmp_path / "source")
    sid = surface_id(repo, "codex")
    lock = SurfaceLock(
        surface_id=sid,
        surface_name="repo",
        repo_path=str(repo.resolve()),
        harness="codex",
        binding_coordinate="binding-1",
        projections=(_expected(repo, source),),
    )
    lock_root = tmp_path / "locks"

    path = write_surface_lock(lock, root=lock_root)
    loaded = read_surface_lock(sid, root=lock_root)

    assert loaded == lock
    assert loaded.lock_id == lock.lock_id
    assert json.loads(path.read_text())["lock_id"] == lock.lock_id


def test_surface_lock_tampering_fails_closed(tmp_path):
    repo = tmp_path / "repo"
    source = _skill(tmp_path / "source")
    sid = surface_id(repo, "codex")
    lock = SurfaceLock(
        surface_id=sid,
        surface_name="repo",
        repo_path=str(repo.resolve()),
        harness="codex",
        binding_coordinate="binding-1",
        projections=(_expected(repo, source),),
    )
    path = write_surface_lock(lock, root=tmp_path / "locks")
    payload = json.loads(path.read_text())
    payload["harness"] = "claude"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(LifecycleError, match="lock_id"):
        read_surface_lock(sid, root=tmp_path / "locks")


def test_ownership_store_requires_exact_projection_target(tmp_path):
    repo = tmp_path / "repo"
    source = _skill(tmp_path / "source")
    projection = repo / ".agents" / "skills" / "review"
    projection.parent.mkdir(parents=True)
    projection.symlink_to(source)
    digest = digest_path(source)
    sid = surface_id(repo, "codex")
    record = OwnershipRecord(
        surface_id=sid,
        surface_name="repo",
        harness="codex",
        skill="review",
        projection_path=str(projection.absolute()),
        source_path=str(source.resolve()),
        source_digest=digest,
        package_digest=digest,
        creation_receipt_id="binding:one",
    )
    store = OwnershipStore(
        receipt_root=tmp_path / "receipts", index_root=tmp_path / "indexes"
    )

    store.record(record)
    loaded = store.records(sid)[str(projection.absolute())]
    assert loaded == record
    assert loaded.matches_symlink(projection)

    projection.unlink()
    foreign = _skill(tmp_path / "foreign")
    projection.symlink_to(foreign)
    assert not loaded.matches_symlink(projection)
    assert not store.forget(sid, projection, "sha256:" + "0" * 64)
    assert str(projection.absolute()) in store.records(sid)


def test_ownership_receipt_tampering_fails_closed(tmp_path):
    repo = tmp_path / "repo"
    source = _skill(tmp_path / "source")
    projection = repo / ".agents" / "skills" / "review"
    digest = digest_path(source)
    sid = surface_id(repo, "codex")
    record = OwnershipRecord(
        surface_id=sid,
        surface_name="repo",
        harness="codex",
        skill="review",
        projection_path=str(projection.absolute()),
        source_path=str(source.resolve()),
        source_digest=digest,
        package_digest=digest,
        creation_receipt_id="binding:one",
    )
    store = OwnershipStore(
        receipt_root=tmp_path / "receipts", index_root=tmp_path / "indexes"
    )
    receipt = store.record(record)
    raw = json.loads(receipt.read_text())
    raw["skill"] = "tampered"
    receipt.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(LifecycleError, match="ownership_id"):
        store.records(sid)


def test_relative_symlink_matches_ownership_record(tmp_path):
    source = _skill(tmp_path / "source")
    projection = tmp_path / "repo" / ".agents" / "skills" / "review"
    projection.parent.mkdir(parents=True)
    relative = os.path.relpath(source, projection.parent)
    projection.symlink_to(relative)
    digest = digest_path(source)
    record = OwnershipRecord(
        surface_id="surface",
        surface_name="repo",
        harness="codex",
        skill="review",
        projection_path=str(projection.absolute()),
        source_path=str(source.resolve()),
        source_digest=digest,
        package_digest=digest,
        creation_receipt_id="binding:one",
    )

    assert record.matches_symlink(projection)


def test_conflict_decision_is_exact_content_addressed_and_surface_bounded(tmp_path):
    repo = tmp_path / "repo"
    foreign = _skill(tmp_path / "foreign")
    sid = surface_id(repo, "codex")
    decision = ConflictDecision(
        surface_id=sid,
        harness="codex",
        skill="review",
        observed_path=str(foreign.absolute()),
        observed_digest=digest_path(foreign),
        disposition="allow",
        reason="Known user-maintained equivalent is intentional.",
    )
    store = ConflictDecisionStore(tmp_path / "conflicts")

    receipt = store.record(decision)

    assert store.get(decision.decision_id) == decision
    assert json.loads(receipt.read_text())["decision_id"] == decision.decision_id
    assert decision.matches(
        surface=sid,
        harness="codex",
        skill="review",
        observed_path=str(foreign.absolute()),
        observed_digest=digest_path(foreign),
    )
    assert not decision.matches(
        surface=sid,
        harness="codex",
        skill="review",
        observed_path=str(foreign.absolute()),
        observed_digest="sha256:" + "0" * 64,
    )
