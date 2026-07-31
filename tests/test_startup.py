"""Portable startup plan/apply/observe and receipt gates."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

import spindle.inventory as inventory_mod
import spindle.startup as startup_mod
from spindle.inventory import DiscoveryRoot, InventoryDigestCache
from spindle.lifecycle import (
    ConflictDecision,
    ConflictDecisionStore,
    ExpectedProjection,
    LifecycleError,
    OwnershipRecord,
    OwnershipStore,
    SurfaceLock,
    digest_path,
    surface_id,
)
from spindle.startup import SurfaceMutex, run_startup


def _skill(root: Path, name: str, body: str = "Use evidence.\n") -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Exercise {name}.\n---\n\n{body}",
        encoding="utf-8",
    )
    return skill


def _store(tmp_path: Path) -> OwnershipStore:
    return OwnershipStore(
        receipt_root=tmp_path / "ownership-receipts",
        index_root=tmp_path / "ownership",
    )


def _record(
    store: OwnershipStore,
    repo: Path,
    projection: Path,
    source: Path,
    name: str,
) -> OwnershipRecord:
    digest = digest_path(source)
    record = OwnershipRecord(
        surface_id=surface_id(repo, "codex"),
        surface_name=repo.name,
        harness="codex",
        skill=name,
        projection_path=str(projection.absolute()),
        source_path=str(source.resolve()),
        source_digest=digest,
        package_digest=digest,
        creation_receipt_id="binding:test",
    )
    store.record(record)
    return record


def _lock(
    repo: Path,
    projections: list[tuple[str, Path, Path, str | None]],
) -> SurfaceLock:
    expected = []
    for name, projection, source, package_digest in projections:
        digest = digest_path(source)
        expected.append(
            ExpectedProjection(
                skill=name,
                projection_path=str(projection.absolute()),
                source_path=str(source.resolve()),
                source_digest=digest,
                package_digest=package_digest or digest,
            )
        )
    return SurfaceLock(
        surface_id=surface_id(repo, "codex"),
        surface_name=repo.name,
        repo_path=str(repo.resolve()),
        harness="codex",
        binding_coordinate="binding:test",
        projections=tuple(expected),
    )


def _roots(repo: Path, *additional: DiscoveryRoot) -> tuple[DiscoveryRoot, ...]:
    return (
        DiscoveryRoot("repo:.", repo / ".agents" / "skills", precedence=100),
        *additional,
    )


def _run_roots(tmp_path: Path) -> dict:
    return {
        "plan_root": tmp_path / "startup-plans",
        "receipt_root": tmp_path / "startup-receipts",
        "mutex_root": tmp_path / "startup-locks",
        "observation_file": tmp_path / "startup-observations.jsonl",
        "digest_cache": InventoryDigestCache(tmp_path / "inventory-digests"),
    }


def test_clean_startup_is_content_addressed_and_idempotent(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = _skill(tmp_path / "sources", "review")
    projection = repo / ".agents" / "skills" / "review"
    projection.parent.mkdir(parents=True)
    projection.symlink_to(source)
    store = _store(tmp_path)
    _record(store, repo, projection, source, "review")
    lock = _lock(repo, [("review", projection, source, None)])
    kwargs = {
        "lock": lock,
        "ownership_store": store,
        "roots": _roots(repo),
        **_run_roots(tmp_path),
    }

    first = run_startup(repo, "codex", **kwargs)
    second = run_startup(repo, "codex", **kwargs)

    assert first.plan.decision == "ok"
    assert first.receipt.decision == "ok"
    assert first.plan.plan_id == second.plan.plan_id
    assert first.receipt.receipt_id == second.receipt.receipt_id
    assert first.plan_path == second.plan_path
    assert first.receipt_path == second.receipt_path


def test_check_reports_owned_repair_without_mutating_then_apply_removes_it(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = _skill(tmp_path / "sources", "stale")
    projection = repo / ".agents" / "skills" / "stale"
    projection.parent.mkdir(parents=True)
    projection.symlink_to(source)
    store = _store(tmp_path)
    _record(store, repo, projection, source, "stale")
    kwargs = {
        "ownership_store": store,
        "roots": _roots(repo),
        **_run_roots(tmp_path),
    }

    checked = run_startup(repo, "codex", **kwargs)
    repaired = run_startup(repo, "codex", reconcile_owned=True, **kwargs)

    assert checked.plan.actions[0].kind == "remove"
    assert checked.receipt.decision == "blocked"
    assert checked.receipt.applied_actions == ()
    assert repaired.receipt.applied_actions[0].kind == "remove"
    assert repaired.receipt.decision == "ok"
    assert not projection.is_symlink()


def test_prelaunch_repairs_owned_target_and_records_locked_package_digest(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    old = _skill(tmp_path / "sources", "old")
    new = _skill(tmp_path / "sources", "new")
    projection = repo / ".agents" / "skills" / "review"
    projection.parent.mkdir(parents=True)
    projection.symlink_to(old)
    store = _store(tmp_path)
    _record(store, repo, projection, old, "review")
    package_digest = "sha256:" + "b" * 64
    lock = _lock(repo, [("review", projection, new, package_digest)])

    result = run_startup(
        repo,
        "codex",
        reconcile_owned=True,
        lock=lock,
        ownership_store=store,
        roots=_roots(repo),
        **_run_roots(tmp_path),
    )

    assert result.plan.actions[0].kind == "update"
    assert projection.resolve() == new.resolve()
    record = store.records(surface_id(repo, "codex"))[str(projection.absolute())]
    assert record.package_digest == package_digest
    assert result.receipt.decision == "ok"


def test_post_discovery_repair_never_claims_clean_session(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = _skill(tmp_path / "sources", "review")
    projection = repo / ".agents" / "skills" / "review"
    store = _store(tmp_path)
    lock = _lock(repo, [("review", projection, source, None)])

    result = run_startup(
        repo,
        "codex",
        reconcile_owned=True,
        already_discovered=True,
        event_source="session-start",
        lock=lock,
        ownership_store=store,
        roots=_roots(repo),
        **_run_roots(tmp_path),
    )

    assert projection.is_symlink()
    assert result.receipt.decision == "restart-required"
    assert result.receipt.to_dict()["restart_required"] is True


def test_locked_editable_content_drift_blocks_without_rewriting_receipt(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = _skill(tmp_path / "sources", "review", "old\n")
    projection = repo / ".agents" / "skills" / "review"
    projection.parent.mkdir(parents=True)
    projection.symlink_to(source)
    store = _store(tmp_path)
    original = _record(store, repo, projection, source, "review")
    lock = _lock(repo, [("review", projection, source, None)])
    (source / "SKILL.md").write_text("same version, changed content\n")

    result = run_startup(
        repo,
        "codex",
        reconcile_owned=True,
        lock=lock,
        ownership_store=store,
        roots=_roots(repo),
        **_run_roots(tmp_path),
    )

    assert result.plan.actions == ()
    assert result.plan.blockers
    assert result.receipt.decision == "blocked"
    assert projection.is_symlink()
    assert (
        store.records(surface_id(repo, "codex"))[str(projection.absolute())] == original
    )


def test_foreign_conflict_blocks_all_owned_mutation(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    root = repo / ".agents" / "skills"
    root.mkdir(parents=True)
    stale_source = _skill(tmp_path / "sources", "stale")
    stale = root / "stale"
    stale.symlink_to(stale_source)
    store = _store(tmp_path)
    _record(store, repo, stale, stale_source, "stale")
    desired_source = _skill(tmp_path / "sources", "review")
    desired = root / "review"
    lock = _lock(repo, [("review", desired, desired_source, None)])
    user_root = tmp_path / "home-skills"
    _skill(user_root, "review")

    result = run_startup(
        repo,
        "codex",
        reconcile_owned=True,
        lock=lock,
        ownership_store=store,
        roots=_roots(repo, DiscoveryRoot("user", user_root, precedence=50)),
        **_run_roots(tmp_path),
    )

    assert result.plan.foreign_conflicts
    assert result.receipt.decision == "blocked"
    assert result.receipt.applied_actions == ()
    assert stale.is_symlink()
    assert not desired.exists()


def test_inventory_change_between_plan_and_apply_aborts_before_mutation(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = _skill(tmp_path / "sources", "stale")
    root = repo / ".agents" / "skills"
    root.mkdir(parents=True)
    stale = root / "stale"
    stale.symlink_to(source)
    store = _store(tmp_path)
    _record(store, repo, stale, source, "stale")
    original_scan = startup_mod.scan_effective_inventory
    calls = 0

    def changing_scan(*args, **kwargs):
        nonlocal calls
        inventory = original_scan(*args, **kwargs)
        calls += 1
        if calls == 1:
            _skill(root, "appeared")
        return inventory

    monkeypatch.setattr(startup_mod, "scan_effective_inventory", changing_scan)

    with pytest.raises(LifecycleError, match="changed after startup planning"):
        run_startup(
            repo,
            "codex",
            reconcile_owned=True,
            ownership_store=store,
            roots=_roots(repo),
            **_run_roots(tmp_path),
        )

    assert stale.is_symlink()


def test_surface_mutex_serializes_same_surface(tmp_path):
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first():
        with SurfaceMutex("sha256:" + "a" * 64, root=tmp_path / "locks"):
            first_entered.set()
            release_first.wait(timeout=2)

    def second():
        first_entered.wait(timeout=2)
        with SurfaceMutex("sha256:" + "a" * 64, root=tmp_path / "locks"):
            second_entered.set()

    one = threading.Thread(target=first)
    two = threading.Thread(target=second)
    one.start()
    two.start()
    assert first_entered.wait(timeout=2)
    assert not second_entered.wait(timeout=0.1)
    release_first.set()
    one.join(timeout=2)
    two.join(timeout=2)
    assert second_entered.is_set()


def test_native_fast_path_uses_cached_digest_and_attests_prelaunch(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = _skill(tmp_path / "sources", "review", "stable\n")
    projection = repo / ".agents" / "skills" / "review"
    projection.parent.mkdir(parents=True)
    projection.symlink_to(source)
    store = _store(tmp_path)
    _record(store, repo, projection, source, "review")
    lock = _lock(repo, [("review", projection, source, None)])
    kwargs = {
        "lock": lock,
        "ownership_store": store,
        "roots": _roots(repo),
        **_run_roots(tmp_path),
    }
    prelaunch = run_startup(repo, "codex", **kwargs)

    def no_deep_hash(_path):
        raise AssertionError("native startup hook performed a deep content hash")

    monkeypatch.setattr(inventory_mod, "digest_path", no_deep_hash)
    monkeypatch.setattr(startup_mod, "digest_path", no_deep_hash)
    hook = run_startup(
        repo,
        "codex",
        already_discovered=True,
        event_source="session-start",
        digest_mode="cache-only",
        **kwargs,
    )

    assert hook.receipt.decision == "ok"
    assert hook.receipt.prior_startup_receipt_id == prelaunch.receipt.receipt_id
    assert hook.receipt.prior_startup_match is True

    (source / "SKILL.md").write_text("drift after launch\n", encoding="utf-8")
    drifted = run_startup(
        repo,
        "codex",
        already_discovered=True,
        event_source="resume",
        digest_mode="cache-only",
        **kwargs,
    )

    assert drifted.receipt.prior_startup_match is False
    assert drifted.receipt.decision == "restart-required"


def test_exact_conflict_decision_preserves_foreign_entry_and_expires_on_drift(
    tmp_path,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    root = repo / ".agents" / "skills"
    root.mkdir(parents=True)
    source = _skill(tmp_path / "sources", "review")
    projection = root / "review"
    projection.symlink_to(source)
    foreign_root = tmp_path / "user-skills"
    foreign = _skill(foreign_root, "review", "intentional alternate\n")
    store = _store(tmp_path)
    _record(store, repo, projection, source, "review")
    initial = _lock(repo, [("review", projection, source, None)])
    decision_store = ConflictDecisionStore(tmp_path / "conflict-receipts")
    decision = ConflictDecision(
        surface_id=initial.surface_id,
        harness="codex",
        skill="review",
        observed_path=str(foreign.absolute()),
        observed_digest=digest_path(foreign),
        disposition="allow",
        reason="This user-scoped alternate is intentionally visible.",
    )
    decision_store.record(decision)
    lock = SurfaceLock(
        surface_id=initial.surface_id,
        surface_name=initial.surface_name,
        repo_path=initial.repo_path,
        harness=initial.harness,
        binding_coordinate=initial.binding_coordinate,
        projections=initial.projections,
        conflict_decisions=(decision.decision_id,),
    )
    roots = _roots(repo, DiscoveryRoot("user", foreign_root, precedence=50))

    allowed = run_startup(
        repo,
        "codex",
        lock=lock,
        ownership_store=store,
        conflict_store=decision_store,
        roots=roots,
        **_run_roots(tmp_path),
    )

    assert allowed.receipt.decision == "warn"
    assert not allowed.receipt.foreign_conflicts
    assert any(
        finding.state == "allowed-foreign-conflict" for finding in allowed.plan.warnings
    )
    assert foreign.is_dir()

    (foreign / "SKILL.md").write_text("changed foreign content\n", encoding="utf-8")
    drifted = run_startup(
        repo,
        "codex",
        lock=lock,
        ownership_store=store,
        conflict_store=decision_store,
        roots=roots,
        **_run_roots(tmp_path),
    )

    assert drifted.receipt.decision == "blocked"
    assert drifted.receipt.foreign_conflicts
    assert foreign.is_dir()
