"""Portable startup planning, ownership-safe apply, and attestation receipts.

The native harness hook is deliberately only an observer.  This module owns the
portable control loop used before launch and from hook callbacks:

``plan -> (optional ownership-safe apply) -> observe -> receipt``.

Plans and receipts are immutable and content-addressed.  Mutations are serialized
per surface and are permitted only when the current inventory still equals the
one the plan inspected.
"""

from __future__ import annotations

import json
import os
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:  # Unix is the current certified host family for Claude Code and Codex.
    import fcntl
except ImportError:  # pragma: no cover - exercised only on unsupported hosts
    fcntl = None  # type: ignore[assignment]

from . import paths
from .inventory import (
    DisabledRules,
    DiscoveryRoot,
    EffectiveInventory,
    InventoryDigestCache,
    InventoryEntry,
    InventoryState,
    scan_effective_inventory,
)
from .lifecycle import (
    ConflictDecision,
    ConflictDecisionStore,
    LifecycleError,
    OwnershipRecord,
    OwnershipStore,
    SurfaceLock,
    content_id,
    digest_path,
    read_surface_lock,
    surface_id,
    write_surface_lock,
)
from .leases import LeaseEvent, LeaseStore, effective_lock_at, write_lease_event

STARTUP_PLAN_SCHEMA = "spindle.startup-plan/v1"
STARTUP_RECEIPT_SCHEMA = "spindle.startup-receipt/v1"
STARTUP_ACTION_SCHEMA = "spindle.startup-action/v1"
STARTUP_OBSERVATION_SCHEMA = "spindle.startup-observation/v1"

DECISIONS = frozenset({"ok", "warn", "blocked", "restart-required"})
ACTION_KINDS = frozenset({"link", "update", "remove", "record"})


@dataclass(frozen=True)
class StartupFinding:
    skill: str
    state: str
    scope: str
    path: str | None
    reason: str

    @classmethod
    def from_entry(cls, entry: InventoryEntry) -> StartupFinding:
        return cls(
            skill=entry.name,
            state=entry.state.value,
            scope=entry.scope,
            path=entry.path,
            reason=entry.reason,
        )

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class StartupAction:
    kind: str
    skill: str
    projection_path: str
    reason: str
    source_path: str | None = None
    source_digest: str | None = None
    package_digest: str | None = None
    ownership_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ACTION_KINDS:
            raise LifecycleError(f"unsupported startup action: {self.kind}")
        for label, value in (
            ("startup action skill", self.skill),
            ("startup action projection_path", self.projection_path),
            ("startup action reason", self.reason),
        ):
            if not value:
                raise LifecycleError(f"{label} must not be empty")
        if self.kind in {"link", "update", "record"} and not all(
            (self.source_path, self.source_digest, self.package_digest)
        ):
            raise LifecycleError(f"startup {self.kind} requires exact source identity")

    @property
    def action_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "schema": STARTUP_ACTION_SCHEMA,
            "kind": self.kind,
            "skill": self.skill,
            "projection_path": self.projection_path,
            "source_path": self.source_path,
            "source_digest": self.source_digest,
            "package_digest": self.package_digest,
            "ownership_id": self.ownership_id,
            "reason": self.reason,
        }
        return {"action_id": self.action_id, **payload} if include_id else payload


@dataclass(frozen=True)
class StartupPlan:
    surface_id: str
    surface_name: str
    repo_path: str
    harness: str
    lock_id: str | None
    inventory_id: str
    event_source: str
    adapter_build: str
    already_discovered: bool
    prior_startup_receipt_id: str | None
    prior_startup_inventory_id: str | None
    runtime_facts: dict[str, str]
    actions: tuple[StartupAction, ...]
    blockers: tuple[StartupFinding, ...]
    warnings: tuple[StartupFinding, ...]
    foreign_conflicts: tuple[StartupFinding, ...]
    active_lease_ids: tuple[str, ...] = ()
    expired_lease_ids: tuple[str, ...] = ()

    @property
    def decision(self) -> str:
        if _post_discovery_restart(self):
            return "restart-required"
        if self.blockers:
            return "blocked"
        if self.actions:
            return "blocked"
        if self.warnings:
            return "warn"
        return "ok"

    @property
    def plan_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": STARTUP_PLAN_SCHEMA,
            "surface_id": self.surface_id,
            "surface_name": self.surface_name,
            "repo_path": self.repo_path,
            "harness": self.harness,
            "lock_id": self.lock_id,
            "inventory_id": self.inventory_id,
            "event_source": self.event_source,
            "adapter_build": self.adapter_build,
            "already_discovered": self.already_discovered,
            "prior_startup_receipt_id": self.prior_startup_receipt_id,
            "prior_startup_inventory_id": self.prior_startup_inventory_id,
            "runtime_facts": dict(sorted(self.runtime_facts.items())),
            "decision": self.decision,
            "actions": [action.to_dict() for action in self.actions],
            "blockers": [finding.to_dict() for finding in self.blockers],
            "warnings": [finding.to_dict() for finding in self.warnings],
            "foreign_conflicts": [
                finding.to_dict() for finding in self.foreign_conflicts
            ],
            "lease_status": {
                "active": sorted(self.active_lease_ids),
                "expired": sorted(self.expired_lease_ids),
            },
        }
        return {"plan_id": self.plan_id, **payload} if include_id else payload


@dataclass(frozen=True)
class StartupReceipt:
    plan_id: str
    surface_id: str
    surface_name: str
    repo_path: str
    harness: str
    lock_id: str | None
    expected_inventory_id: str
    observed_inventory_id: str
    event_source: str
    adapter_build: str
    prior_startup_receipt_id: str | None
    prior_startup_match: bool | None
    runtime_facts: dict[str, str]
    decision: str
    applied_actions: tuple[StartupAction, ...]
    foreign_conflicts: tuple[StartupFinding, ...]
    warnings: tuple[StartupFinding, ...]
    active_lease_ids: tuple[str, ...] = ()
    expired_lease_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.decision not in DECISIONS:
            raise LifecycleError(f"unsupported startup decision: {self.decision}")

    @property
    def receipt_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": STARTUP_RECEIPT_SCHEMA,
            "plan_id": self.plan_id,
            "surface_id": self.surface_id,
            "surface_name": self.surface_name,
            "repo_path": self.repo_path,
            "harness": self.harness,
            "lock_id": self.lock_id,
            "expected_inventory_id": self.expected_inventory_id,
            "observed_inventory_id": self.observed_inventory_id,
            "event_source": self.event_source,
            "adapter_build": self.adapter_build,
            "prior_startup_receipt_id": self.prior_startup_receipt_id,
            "prior_startup_match": self.prior_startup_match,
            "runtime_facts": dict(sorted(self.runtime_facts.items())),
            "decision": self.decision,
            "restart_required": self.decision == "restart-required",
            "applied_actions": [action.to_dict() for action in self.applied_actions],
            "foreign_conflicts": [
                finding.to_dict() for finding in self.foreign_conflicts
            ],
            "warnings": [finding.to_dict() for finding in self.warnings],
            "lease_status": {
                "active": sorted(self.active_lease_ids),
                "expired": sorted(self.expired_lease_ids),
            },
        }
        return {"receipt_id": self.receipt_id, **payload} if include_id else payload


@dataclass(frozen=True)
class StartupResult:
    plan: StartupPlan
    receipt: StartupReceipt
    plan_path: Path
    receipt_path: Path


class SurfaceMutex(AbstractContextManager["SurfaceMutex"]):
    """An advisory per-surface process lock around startup mutation."""

    def __init__(self, surface: str, *, root: Path | None = None) -> None:
        self.surface = surface
        self.root = root or paths.startup_locks_dir()
        self._handle = None

    def __enter__(self) -> SurfaceMutex:
        if fcntl is None:  # pragma: no cover
            raise LifecycleError("startup mutation locking is unavailable on this host")
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / f"{_digest_hex(self.surface)}.lock"
        self._handle = lock_path.open("a+", encoding="utf-8")
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        assert self._handle is not None
        assert fcntl is not None
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None


def plan_startup(
    repo_path: str | Path,
    harness: str,
    *,
    surface_name: str | None = None,
    event_source: str = "pre-launch",
    adapter_build: str = "spindle-core/v1",
    already_discovered: bool = False,
    lock: SurfaceLock | None = None,
    ownership_store: OwnershipStore | None = None,
    roots: Iterable[DiscoveryRoot] | None = None,
    disabled: DisabledRules | None = None,
    home: Path | None = None,
    admin_root: Path | None = None,
    digest_mode: str = "deep",
    digest_cache: InventoryDigestCache | None = None,
    prior_startup_receipt_id: str | None = None,
    prior_startup_inventory_id: str | None = None,
    runtime_facts: dict[str, str] | None = None,
    conflict_store: ConflictDecisionStore | None = None,
    lease_store: LeaseStore | None = None,
    now: datetime | None = None,
) -> StartupPlan:
    """Build a pure desired-versus-effective startup plan."""
    repo = Path(repo_path).resolve()
    sid = surface_id(repo, harness)
    desired = lock if lock is not None else read_surface_lock(sid)
    active_lease_ids: tuple[str, ...] = ()
    expired_lease_ids: tuple[str, ...] = ()
    if desired is not None and desired.lease_ids:
        desired, active_lease_ids, expired_lease_ids = effective_lock_at(
            desired,
            store=lease_store,
            now=now,
        )
    store = ownership_store or OwnershipStore()
    decision_store = conflict_store or ConflictDecisionStore()
    inventory = scan_effective_inventory(
        repo,
        harness,
        surface_name=surface_name,
        lock=desired,
        ownership_store=store,
        roots=roots,
        disabled=disabled,
        home=home,
        admin_root=admin_root,
        digest_mode=digest_mode,
        digest_cache=digest_cache,
    )
    ownership = store.records(sid)
    expected = {
        str(Path(projection.projection_path).absolute()): projection
        for projection in (desired.projections if desired is not None else ())
    }
    actions: list[StartupAction] = []
    blockers: list[StartupFinding] = []
    warnings: list[StartupFinding] = []
    conflicts: list[StartupFinding] = []
    conflict_decisions: tuple[ConflictDecision, ...] = ()
    if desired is not None:
        loaded = tuple(
            decision_store.get(decision_id)
            for decision_id in desired.conflict_decisions
        )
        if any(
            decision.surface_id != sid or decision.harness != harness
            for decision in loaded
        ):
            raise LifecycleError(
                "surface lock references a conflict decision from another surface"
            )
        conflict_decisions = loaded

    if already_discovered and prior_startup_receipt_id is None:
        warnings.append(
            StartupFinding(
                skill="__startup_receipt__",
                state="unverified-startup",
                scope="control",
                path=None,
                reason="no successful pre-launch startup receipt is available",
            )
        )

    for entry in inventory.entries:
        finding = StartupFinding.from_entry(entry)
        projection = expected.get(entry.path or "")
        record = ownership.get(entry.path or "")
        if entry.state is InventoryState.EXPECTED_OWNED:
            continue
        if entry.state is InventoryState.CONFLICTING:
            allowed = next(
                (
                    decision
                    for decision in conflict_decisions
                    if entry.path is not None
                    and decision.matches(
                        surface=sid,
                        harness=harness,
                        skill=entry.name,
                        observed_path=entry.path,
                        observed_digest=entry.content_digest,
                    )
                ),
                None,
            )
            if allowed is not None:
                warnings.append(
                    StartupFinding(
                        skill=entry.name,
                        state="allowed-foreign-conflict",
                        scope=entry.scope,
                        path=entry.path,
                        reason=f"preserved by explicit conflict decision {allowed.decision_id}",
                    )
                )
                continue
            blockers.append(finding)
            conflicts.append(finding)
            continue
        if entry.state is InventoryState.AMBIGUOUS_OWNERSHIP:
            blockers.append(finding)
            continue
        if entry.state is InventoryState.DISABLED and (
            entry.expected or entry.ownership_id is not None
        ):
            blockers.append(finding)
            continue
        if entry.state is InventoryState.MISSING and projection is not None:
            if _expected_source_is_available(
                projection, digest_mode=digest_mode, digest_cache=digest_cache
            ):
                actions.append(
                    _desired_action("link", projection, record, entry.reason)
                )
            else:
                blockers.append(
                    StartupFinding(
                        skill=entry.name,
                        state=entry.state.value,
                        scope=entry.scope,
                        path=entry.path,
                        reason="desired source is missing or differs from its locked digest",
                    )
                )
            continue
        if entry.state in {InventoryState.STALE_OWNED, InventoryState.BROKEN} and (
            record is not None
        ):
            if projection is None:
                actions.append(
                    StartupAction(
                        kind="remove",
                        skill=entry.name,
                        projection_path=record.projection_path,
                        ownership_id=record.ownership_id,
                        reason=entry.reason,
                    )
                )
            elif _expected_source_is_available(
                projection, digest_mode=digest_mode, digest_cache=digest_cache
            ):
                current = Path(record.source_path).resolve(strict=False)
                wanted = Path(projection.source_path).resolve(strict=False)
                kind = (
                    "record"
                    if current == wanted and entry.state is not InventoryState.BROKEN
                    else "update"
                )
                actions.append(_desired_action(kind, projection, record, entry.reason))
            else:
                blockers.append(
                    StartupFinding(
                        skill=entry.name,
                        state=entry.state.value,
                        scope=entry.scope,
                        path=entry.path,
                        reason="locked source content is unavailable; repair requires its exact package revision",
                    )
                )
            continue
        if entry.state in {
            InventoryState.FOREIGN,
            InventoryState.OPAQUE,
            InventoryState.DISABLED,
            InventoryState.BROKEN,
        }:
            warnings.append(finding)

    return StartupPlan(
        surface_id=sid,
        surface_name=surface_name or repo.name,
        repo_path=str(repo),
        harness=harness,
        lock_id=desired.lock_id if desired is not None else None,
        inventory_id=inventory.inventory_id,
        event_source=event_source,
        adapter_build=adapter_build,
        already_discovered=already_discovered,
        prior_startup_receipt_id=prior_startup_receipt_id,
        prior_startup_inventory_id=prior_startup_inventory_id,
        runtime_facts=dict(sorted((runtime_facts or {}).items())),
        actions=tuple(sorted(actions, key=lambda action: action.projection_path)),
        blockers=tuple(_unique_findings(blockers)),
        warnings=tuple(_unique_findings(warnings)),
        foreign_conflicts=tuple(_unique_findings(conflicts)),
        active_lease_ids=active_lease_ids,
        expired_lease_ids=expired_lease_ids,
    )


def run_startup(
    repo_path: str | Path,
    harness: str,
    *,
    reconcile_owned: bool = False,
    surface_name: str | None = None,
    event_source: str = "pre-launch",
    adapter_build: str = "spindle-core/v1",
    already_discovered: bool = False,
    lock: SurfaceLock | None = None,
    ownership_store: OwnershipStore | None = None,
    roots: Iterable[DiscoveryRoot] | None = None,
    disabled: DisabledRules | None = None,
    home: Path | None = None,
    admin_root: Path | None = None,
    plan_root: Path | None = None,
    receipt_root: Path | None = None,
    mutex_root: Path | None = None,
    digest_mode: str = "deep",
    digest_cache: InventoryDigestCache | None = None,
    observation_file: Path | None = None,
    runtime_facts: dict[str, str] | None = None,
    conflict_store: ConflictDecisionStore | None = None,
    lease_store: LeaseStore | None = None,
    surface_lock_root: Path | None = None,
    lease_event_root: Path | None = None,
    now: datetime | None = None,
) -> StartupResult:
    """Plan, optionally apply, observe, and persist one startup attestation."""
    repo = Path(repo_path).resolve()
    store = ownership_store or OwnershipStore()
    cache = digest_cache or InventoryDigestCache()
    sid = surface_id(repo, harness)
    raw_desired = (
        lock
        if lock is not None
        else read_surface_lock(sid, root=surface_lock_root)
    )
    desired = raw_desired
    moment = (now or datetime.now(tz=UTC)).astimezone(UTC)
    active_lease_ids: tuple[str, ...] = ()
    expired_lease_ids: tuple[str, ...] = ()
    if desired is not None and desired.lease_ids:
        desired, active_lease_ids, expired_lease_ids = effective_lock_at(
            desired,
            store=lease_store,
            now=moment,
        )
    lease_lock_changed = bool(
        raw_desired is not None
        and desired is not None
        and raw_desired.lock_id != desired.lock_id
    )
    prior_startup = (
        latest_startup_receipt(
            repo,
            harness,
            root=receipt_root,
            observation_file=observation_file,
            prelaunch=True,
        )
        if already_discovered
        else None
    )
    plan = plan_startup(
        repo,
        harness,
        surface_name=surface_name,
        event_source=event_source,
        adapter_build=adapter_build,
        already_discovered=already_discovered,
        lock=raw_desired,
        ownership_store=store,
        roots=roots,
        disabled=disabled,
        home=home,
        admin_root=admin_root,
        digest_mode=digest_mode,
        digest_cache=cache,
        prior_startup_receipt_id=(
            str(prior_startup["receipt_id"]) if prior_startup is not None else None
        ),
        prior_startup_inventory_id=(
            str(prior_startup["observed_inventory_id"])
            if prior_startup is not None
            else None
        ),
        runtime_facts=runtime_facts,
        conflict_store=conflict_store,
        lease_store=lease_store,
        now=moment,
    )
    plan_path = write_startup_plan(plan, root=plan_root)
    applied: tuple[StartupAction, ...] = ()
    lock_reconciled = False
    if reconcile_owned and not plan.blockers and (plan.actions or lease_lock_changed):
        with SurfaceMutex(plan.surface_id, root=mutex_root):
            current_lock = (
                raw_desired
                if lock is not None
                else read_surface_lock(sid, root=surface_lock_root)
            )
            if (
                raw_desired is None
                and current_lock is not None
                or raw_desired is not None
                and (
                    current_lock is None
                    or current_lock.lock_id != raw_desired.lock_id
                )
            ):
                raise LifecycleError(
                    "surface lock changed after startup planning; re-plan before mutation"
                )
            current = scan_effective_inventory(
                repo,
                harness,
                surface_name=surface_name,
                lock=desired,
                ownership_store=store,
                roots=roots,
                disabled=disabled,
                home=home,
                admin_root=admin_root,
                digest_mode=digest_mode,
                digest_cache=cache,
            )
            if current.inventory_id != plan.inventory_id:
                raise LifecycleError(
                    "effective inventory changed after startup planning; re-plan before mutation"
                )
            _apply_actions(plan, store)
            applied = plan.actions
            if lease_lock_changed:
                assert desired is not None
                write_surface_lock(desired, root=surface_lock_root)
                lock_reconciled = True

    observed = scan_effective_inventory(
        repo,
        harness,
        surface_name=surface_name,
        lock=desired,
        ownership_store=store,
        roots=roots,
        disabled=disabled,
        home=home,
        admin_root=admin_root,
        digest_mode=digest_mode,
        digest_cache=cache,
    )
    decision = _receipt_decision(plan, observed, applied)
    prior_match = (
        observed.inventory_id == plan.prior_startup_inventory_id
        if plan.prior_startup_inventory_id is not None
        else None
    )
    receipt = StartupReceipt(
        plan_id=plan.plan_id,
        surface_id=plan.surface_id,
        surface_name=plan.surface_name,
        repo_path=plan.repo_path,
        harness=plan.harness,
        lock_id=plan.lock_id,
        expected_inventory_id=plan.inventory_id,
        observed_inventory_id=observed.inventory_id,
        event_source=plan.event_source,
        adapter_build=plan.adapter_build,
        prior_startup_receipt_id=plan.prior_startup_receipt_id,
        prior_startup_match=prior_match,
        runtime_facts=plan.runtime_facts,
        decision=decision,
        applied_actions=applied,
        foreign_conflicts=plan.foreign_conflicts,
        warnings=tuple(
            _unique_findings(
                [
                    finding
                    for finding in plan.warnings
                    if finding.state == "allowed-foreign-conflict"
                ]
                + [
                    StartupFinding.from_entry(entry)
                    for entry in observed.entries
                    if entry.state
                    in {
                        InventoryState.FOREIGN,
                        InventoryState.OPAQUE,
                        InventoryState.DISABLED,
                        InventoryState.BROKEN,
                    }
                    and not (entry.expected or entry.ownership_id is not None)
                ]
            )
        ),
        active_lease_ids=plan.active_lease_ids,
        expired_lease_ids=plan.expired_lease_ids,
    )
    receipt_path = write_startup_receipt(receipt, root=receipt_root)
    append_startup_observation(receipt, file=observation_file)
    if lock_reconciled and raw_desired is not None and desired is not None:
        for lease_id in expired_lease_ids:
            write_lease_event(
                LeaseEvent(
                    event="expired",
                    lease_id=lease_id,
                    surface_id=sid,
                    observed_at=moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    previous_lock_id=raw_desired.lock_id,
                    next_lock_id=desired.lock_id,
                    startup_receipt_id=receipt.receipt_id,
                    removed_projections=tuple(
                        action.projection_path
                        for action in applied
                        if action.kind == "remove"
                    ),
                ),
                root=lease_event_root,
            )
    return StartupResult(plan, receipt, plan_path, receipt_path)


def write_startup_plan(plan: StartupPlan, *, root: Path | None = None) -> Path:
    return _write_immutable(
        root or paths.startup_plans_dir(), plan.plan_id, plan.to_dict()
    )


def write_startup_receipt(receipt: StartupReceipt, *, root: Path | None = None) -> Path:
    return _write_immutable(
        root or paths.startup_receipts_dir(), receipt.receipt_id, receipt.to_dict()
    )


def append_startup_observation(
    receipt: StartupReceipt, *, file: Path | None = None
) -> Path:
    target = file or paths.startup_observations_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "schema": STARTUP_OBSERVATION_SCHEMA,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "receipt_id": receipt.receipt_id,
        "repo_path": receipt.repo_path,
        "harness": receipt.harness,
        "event_source": receipt.event_source,
        "decision": receipt.decision,
    }
    serialized = json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(serialized)
        handle.flush()
        os.fsync(handle.fileno())
    return target


def latest_startup_receipt(
    repo_path: str | Path,
    harness: str,
    *,
    root: Path | None = None,
    observation_file: Path | None = None,
    prelaunch: bool | None = None,
) -> dict[str, Any] | None:
    """Return the latest chronologically observed matching immutable receipt."""

    repo = str(Path(repo_path).resolve())
    receipt_root = root or paths.startup_receipts_dir()
    observations = observation_file or paths.startup_observations_file()
    rows: list[dict[str, Any]] = []
    if observations.is_file():
        try:
            lines = observations.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in reversed(lines):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    for row in rows:
        if (
            row.get("schema") != STARTUP_OBSERVATION_SCHEMA
            or row.get("repo_path") != repo
            or row.get("harness") != harness
        ):
            continue
        is_prelaunch = row.get("event_source") == "pre-launch"
        if prelaunch is not None and is_prelaunch != prelaunch:
            continue
        if is_prelaunch and row.get("decision") not in {"ok", "warn"}:
            continue
        receipt_id = row.get("receipt_id")
        if not isinstance(receipt_id, str):
            continue
        receipt_path = receipt_root / f"{_digest_hex(receipt_id)}.json"
        try:
            raw = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, LifecycleError):
            continue
        if (
            raw.get("schema") == STARTUP_RECEIPT_SCHEMA
            and raw.get("receipt_id") == receipt_id
            and raw.get("repo_path") == repo
            and raw.get("harness") == harness
            and raw.get("event_source") == row.get("event_source")
        ):
            return raw
    return None


def _desired_action(kind, projection, record, reason) -> StartupAction:
    return StartupAction(
        kind=kind,
        skill=projection.skill,
        projection_path=str(Path(projection.projection_path).absolute()),
        source_path=str(Path(projection.source_path).resolve()),
        source_digest=projection.source_digest,
        package_digest=projection.package_digest,
        ownership_id=record.ownership_id if record is not None else None,
        reason=reason,
    )


def _expected_source_is_available(
    projection,
    *,
    digest_mode: str,
    digest_cache: InventoryDigestCache | None,
) -> bool:
    source = Path(projection.source_path)
    if not source.exists():
        return False
    if digest_cache is not None:
        return (
            digest_cache.resolve(source, mode=digest_mode) == projection.source_digest
        )
    if digest_mode == "cache-only":
        return False
    try:
        return digest_path(source) == projection.source_digest
    except LifecycleError:
        return False


def _apply_actions(plan: StartupPlan, store: OwnershipStore) -> None:
    ownership = store.records(plan.surface_id)
    # Revalidate every action before the first mutation.
    for action in plan.actions:
        projection = Path(action.projection_path)
        record = ownership.get(action.projection_path)
        if action.kind == "link":
            if projection.exists() or projection.is_symlink():
                raise LifecycleError(f"startup link target appeared: {projection}")
        else:
            if (
                record is None
                or record.ownership_id != action.ownership_id
                or not record.matches_symlink(projection)
            ):
                raise LifecycleError(
                    f"startup ownership changed before {action.kind}: {projection}"
                )
        if action.kind in {"link", "update", "record"}:
            assert action.source_path is not None
            assert action.source_digest is not None
            if digest_path(action.source_path) != action.source_digest:
                raise LifecycleError(
                    f"startup source changed before {action.kind}: {action.source_path}"
                )

    for action in plan.actions:
        projection = Path(action.projection_path)
        old_record = ownership.get(action.projection_path)
        if action.kind == "remove":
            assert old_record is not None
            projection.unlink()
            if not store.forget(plan.surface_id, projection, old_record.ownership_id):
                raise LifecycleError(
                    f"ownership index changed while removing {projection}"
                )
            continue
        assert action.source_path is not None
        assert action.source_digest is not None
        assert action.package_digest is not None
        if action.kind == "update":
            projection.unlink()
        if action.kind in {"link", "update"}:
            projection.parent.mkdir(parents=True, exist_ok=True)
            projection.symlink_to(Path(action.source_path))
        store.record(
            OwnershipRecord(
                surface_id=plan.surface_id,
                surface_name=plan.surface_name,
                harness=plan.harness,
                skill=action.skill,
                projection_path=str(projection.absolute()),
                source_path=action.source_path,
                source_digest=action.source_digest,
                package_digest=action.package_digest,
                creation_receipt_id=f"startup:{plan.plan_id}",
            )
        )


def _receipt_decision(
    plan: StartupPlan,
    observed: EffectiveInventory,
    applied: tuple[StartupAction, ...],
) -> str:
    if _post_discovery_restart(plan):
        return "restart-required"
    if plan.blockers:
        return "blocked"
    allowed_conflict_paths = {
        finding.path
        for finding in plan.warnings
        if finding.state == "allowed-foreign-conflict"
    }
    unresolved = tuple(
        entry
        for entry in observed.blocking_entries()
        if not (
            entry.state is InventoryState.CONFLICTING
            and entry.path in allowed_conflict_paths
        )
    )
    if unresolved:
        return "blocked"
    if any(
        finding.state == "allowed-foreign-conflict" for finding in plan.warnings
    ):
        return "warn"
    if any(
        entry.state
        in {
            InventoryState.FOREIGN,
            InventoryState.OPAQUE,
            InventoryState.DISABLED,
            InventoryState.BROKEN,
        }
        for entry in observed.entries
    ):
        return "warn"
    return "ok"


def _post_discovery_restart(plan: StartupPlan) -> bool:
    if not plan.already_discovered:
        return False
    if plan.actions:
        return True
    if (
        plan.prior_startup_inventory_id is not None
        and plan.prior_startup_inventory_id != plan.inventory_id
    ):
        return True
    restartable = {
        InventoryState.MISSING.value,
        InventoryState.STALE_OWNED.value,
        InventoryState.BROKEN.value,
    }
    return any(finding.state in restartable for finding in plan.blockers)


def _unique_findings(findings: list[StartupFinding]) -> list[StartupFinding]:
    unique = {content_id(finding.to_dict()): finding for finding in findings}
    return [unique[key] for key in sorted(unique)]


def _write_immutable(root: Path, identity: str, payload: dict[str, Any]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{_digest_hex(identity)}.json"
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != serialized:
            raise LifecycleError(f"content-addressed record collision at {target}")
        return target
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(target, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(serialized)
        handle.flush()
        os.fsync(handle.fileno())
    return target


def _digest_hex(identity: str) -> str:
    prefix, separator, value = identity.partition(":")
    if separator != ":" or prefix != "sha256" or len(value) != 64:
        raise LifecycleError(f"invalid content identity: {identity}")
    return value
