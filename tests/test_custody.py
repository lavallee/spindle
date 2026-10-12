"""Export/import, cache GC, recovery, and migration custody coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spindle import trust
from spindle.custody import (
    CustodyError,
    apply_cache_gc,
    apply_recovery,
    cache_gc_plan,
    export_state,
    import_state,
    migration_plan,
    plan_import,
    recovery_plan,
)
from spindle.lifecycle import (
    ExpectedProjection,
    OwnershipRecord,
    OwnershipStore,
    PackageRevision,
    SkillRef,
    SurfaceLock,
    cache_package,
    digest_path,
    surface_id,
    write_surface_lock,
)
from spindle.maintenance import (
    AdoptionRecord,
    AdoptionStore,
    MaintenanceEvent,
    current_status,
    record_status,
    write_maintenance_event,
)


def _isolate(tmp_path, monkeypatch):
    state = tmp_path / "state"
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SPINDLE_HOME", str(state))
    monkeypatch.setenv("HOME", str(home))
    return state, home


def _package(tmp_path: Path, name: str, text: str) -> tuple[PackageRevision, Path]:
    root = tmp_path / f"source-{name}"
    skill = root / name
    skill.mkdir(parents=True)
    skill.joinpath("SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test.\n---\n\n{text}\n",
        encoding="utf-8",
    )
    revision = PackageRevision.from_path(
        f"package-{name}",
        "1",
        root,
        skills=((name, skill),),
    )
    return revision, skill


def test_state_bundle_is_reproducible_importable_and_conflict_safe(
    tmp_path, monkeypatch
):
    state, _home = _isolate(tmp_path, monkeypatch)
    receipt = state / "example-receipts" / "one.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        '{"schema":"spindle.example/v1","value":1}\n', encoding="utf-8"
    )
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"

    one = export_state(first)
    two = export_state(second)
    assert one["manifest"]["bundle_id"] == two["manifest"]["bundle_id"]
    assert first.read_bytes() == second.read_bytes()

    restored = tmp_path / "restored"
    preview = import_state(first, destination=restored, dry_run=True)
    assert preview["action"] == "would-import"
    assert not restored.exists()
    applied = import_state(first, destination=restored)
    assert applied["action"] == "imported"
    assert restored.joinpath("example-receipts/one.json").read_bytes() == (
        receipt.read_bytes()
    )
    assert all(
        action["action"] == "identical"
        for action in plan_import(first, destination=restored)["actions"]
    )

    restored.joinpath("example-receipts/one.json").write_text("different\n")
    with pytest.raises(CustodyError, match="conflicts"):
        import_state(first, destination=restored)


def test_cache_gc_removes_only_unreferenced_verified_package_digests(
    tmp_path, monkeypatch
):
    state, _home = _isolate(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    repo.mkdir()
    keep_revision, keep_skill = _package(tmp_path, "keep", "Keep.")
    drop_revision, _drop_skill = _package(tmp_path, "drop", "Drop.")
    keep_cache = cache_package(keep_revision)
    drop_cache = cache_package(drop_revision)
    sid = surface_id(repo, "codex")
    lock = SurfaceLock(
        surface_id=sid,
        surface_name="repo",
        repo_path=str(repo),
        harness="codex",
        binding_coordinate="test",
        projections=(
            ExpectedProjection(
                skill="keep",
                projection_path=str(repo / ".agents/skills/keep"),
                source_path=str(keep_cache / "keep"),
                source_digest=digest_path(keep_skill),
                package_digest=keep_revision.content_digest,
            ),
        ),
    )
    write_surface_lock(lock)

    plan = cache_gc_plan()
    assert [item["package_digest"] for item in plan["candidates"]] == [
        drop_revision.content_digest
    ]
    preview = apply_cache_gc(plan["plan_id"], dry_run=True)
    assert preview["action"] == "would-gc" and drop_cache.exists()
    result = apply_cache_gc(plan["plan_id"])

    assert result["event"]["removed_package_digests"] == [
        drop_revision.content_digest
    ]
    assert keep_cache.is_dir()
    assert not drop_cache.exists()
    assert state.joinpath("hardening-receipts").is_dir()


def test_recovery_rebuilds_mutable_indexes_from_immutable_history(
    tmp_path, monkeypatch
):
    state, _home = _isolate(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    repo.mkdir()
    revision, source_skill = _package(tmp_path, "review", "Review.")
    cached = cache_package(revision)
    sid = surface_id(repo, "codex")
    projection_path = repo / ".agents/skills/review"
    projection = ExpectedProjection(
        skill="review",
        projection_path=str(projection_path),
        source_path=str(cached / "review"),
        source_digest=digest_path(source_skill),
        package_digest=revision.content_digest,
    )
    lock = SurfaceLock(
        surface_id=sid,
        surface_name="repo",
        repo_path=str(repo),
        harness="codex",
        binding_coordinate="test",
        projections=(projection,),
    )
    write_surface_lock(lock)
    ownership = OwnershipRecord(
        surface_id=sid,
        surface_name="repo",
        harness="codex",
        skill="review",
        projection_path=str(projection_path),
        source_path=str(cached / "review"),
        source_digest=projection.source_digest,
        package_digest=revision.content_digest,
        creation_receipt_id=lock.lock_id,
    )
    OwnershipStore().record(ownership)

    adoption = AdoptionRecord(
        skill="review",
        package_name=revision.name,
        package_digest=revision.content_digest,
        skill_digest=projection.source_digest,
        skill_subpath="review",
        source=SkillRef(
            provider="local",
            locator=str(cached),
            revision=revision.content_digest,
            content_digest=revision.content_digest,
        ),
        surface_id=sid,
        harness="codex",
        scope="repo",
        owner="team",
        adopted_at="2026-07-31T12:00:00Z",
        update_reference="manual",
        authority_ceiling="read-only",
        retirement_policy="manual",
        lease_id="sha256:" + "1" * 64,
        trial_run_receipt_id="sha256:" + "2" * 64,
        activation_receipt_id="3" * 64,
    )
    AdoptionStore().record(adoption)
    event = MaintenanceEvent(
        operation="adopt",
        skill="review",
        surface_id=sid,
        adoption_id=adoption.adoption_id,
        previous_adoption_id=None,
        prior_lock_id=lock.lock_id,
        next_lock_id=lock.lock_id,
        reason="migration",
        actor="team",
        observed_at="2026-07-31T12:00:00Z",
        startup_receipt_id=None,
    )
    write_maintenance_event(event)
    record_status(event, "active")
    quarantine = trust.set_quarantine(
        revision.content_digest,
        quarantined=True,
        reason="test",
        actor="security",
        effective_at="2026-07-31T12:00:00Z",
    )

    state.joinpath("ownership", f"{sid[7:]}.json").write_text("corrupt\n")
    state.joinpath("maintenance.json").write_text("corrupt\n")
    state.joinpath("quarantine.json").write_text("corrupt\n")
    plan = recovery_plan()
    assert plan["blockers"] == []
    assert plan["proposed"]["ownership_indexes"][sid]["entries"] == {
        str(projection_path): ownership.ownership_id
    }

    result = apply_recovery(plan["plan_id"])
    assert result["action"] == "recovered"
    assert OwnershipStore().records(sid)[str(projection_path)] == ownership
    assert current_status(sid, "review")["event_id"] == event.event_id
    assert trust.quarantine_status(revision.content_digest)["event_id"] == (
        quarantine.event_id
    )


def test_migration_audit_preserves_foreign_skill_and_blocks_unprovable_v1(
    tmp_path, monkeypatch
):
    state, _home = _isolate(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    foreign = repo / ".agents" / "skills" / "foreign"
    foreign.mkdir(parents=True)
    foreign.joinpath("SKILL.md").write_text(
        "---\nname: foreign\ndescription: Foreign.\n---\n\nKeep.\n",
        encoding="utf-8",
    )
    before = foreign.joinpath("SKILL.md").read_bytes()

    plan = migration_plan(repo, "codex")
    assert any(
        action["kind"] == "legacy-or-foreign-skill"
        and action["status"] == "preserve"
        for action in plan["actions"]
    )
    assert foreign.joinpath("SKILL.md").read_bytes() == before

    legacy = state / "adoptions" / "legacy.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        json.dumps({"schema": "spindle.adoption-record/v1"}), encoding="utf-8"
    )
    blocked = migration_plan(repo, "codex")
    assert "lacks trial/activation provenance" in blocked["blockers"][0]
    assert foreign.joinpath("SKILL.md").read_bytes() == before
