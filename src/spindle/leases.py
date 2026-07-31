"""Executable local lease records and time-bounded desired-state projection."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from . import paths
from .lifecycle import (
    ExpectedProjection,
    Lease,
    LifecycleError,
    SurfaceLock,
    content_id,
)

LEASE_PLAN_SCHEMA = "spindle.lease-plan/v1"
LEASE_EVENT_SCHEMA = "spindle.lease-event/v1"
TRIAL_RUN_RECEIPT_SCHEMA = "spindle.trial-run-receipt/v1"


class LeaseStore:
    """Immutable content-addressed lease grants."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or paths.lease_receipts_dir()

    def record(self, lease: Lease) -> Path:
        return _write_immutable(self.root, lease.lease_id, lease.to_dict())

    def get(self, lease_id: str) -> Lease:
        target = self.root / f"{_digest_hex(lease_id)}.json"
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LifecycleError(f"invalid or missing lease {lease_id}: {exc}") from exc
        if not isinstance(raw, dict):
            raise LifecycleError(f"lease receipt at {target} must be an object")
        lease = Lease.from_dict(raw)
        if lease.lease_id != lease_id:
            raise LifecycleError("lease receipt identity mismatch")
        return lease

    def list(self) -> tuple[Lease, ...]:
        if not self.root.is_dir():
            return ()
        leases: list[Lease] = []
        for target in sorted(self.root.glob("*.json")):
            try:
                raw = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise LifecycleError(f"invalid lease receipt at {target}: {exc}") from exc
            if not isinstance(raw, dict):
                raise LifecycleError(f"lease receipt at {target} must be an object")
            lease = Lease.from_dict(raw)
            if target.stem != _digest_hex(lease.lease_id):
                raise LifecycleError(f"lease filename identity mismatch at {target}")
            leases.append(lease)
        return tuple(sorted(leases, key=lambda item: item.lease_id))


@dataclass(frozen=True)
class LeasePlan:
    operation: str
    lease: Lease
    current_lock_id: str | None
    inventory_id: str
    proposed_lock: SurfaceLock
    projection: ExpectedProjection
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    source_receipt_id: str | None = None
    preflight_report_id: str | None = None

    def __post_init__(self) -> None:
        if self.operation not in {
            "borrow",
            "try",
            "update-try",
            "release",
            "expire",
        }:
            raise LifecycleError(f"unsupported lease plan operation: {self.operation}")

    @property
    def plan_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "schema": LEASE_PLAN_SCHEMA,
            "operation": self.operation,
            "lease": self.lease.to_dict(),
            "current_lock_id": self.current_lock_id,
            "inventory_id": self.inventory_id,
            "proposed_lock": self.proposed_lock.to_dict(),
            "projection": self.projection.to_dict(),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "source_receipt_id": self.source_receipt_id,
            "preflight_report_id": self.preflight_report_id,
        }
        return {"plan_id": self.plan_id, **payload} if include_id else payload


@dataclass(frozen=True)
class LeaseEvent:
    event: str
    lease_id: str
    surface_id: str
    observed_at: str
    previous_lock_id: str
    next_lock_id: str
    startup_receipt_id: str | None
    removed_projections: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.event not in {"released", "expired", "trial-cleanup"}:
            raise LifecycleError(f"unsupported lease event: {self.event}")
        for label, value in (
            ("lease_id", self.lease_id),
            ("surface_id", self.surface_id),
            ("observed_at", self.observed_at),
            ("previous_lock_id", self.previous_lock_id),
            ("next_lock_id", self.next_lock_id),
        ):
            if not value:
                raise LifecycleError(f"{label} must not be empty")

    @property
    def event_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "schema": LEASE_EVENT_SCHEMA,
            "event": self.event,
            "lease_id": self.lease_id,
            "surface_id": self.surface_id,
            "observed_at": self.observed_at,
            "previous_lock_id": self.previous_lock_id,
            "next_lock_id": self.next_lock_id,
            "startup_receipt_id": self.startup_receipt_id,
            "removed_projections": sorted(self.removed_projections),
        }
        return {"event_id": self.event_id, **payload} if include_id else payload


@dataclass(frozen=True)
class TrialRunReceipt:
    lease_id: str
    harness: str
    task_digest: str
    command_shape: tuple[str, ...]
    exit_code: int
    startup_receipt_id: str
    activation_receipt_id: str | None
    cleanup_event_id: str | None
    stdout_digest: str | None = None
    stderr_digest: str | None = None

    @property
    def receipt_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "schema": TRIAL_RUN_RECEIPT_SCHEMA,
            "lease_id": self.lease_id,
            "harness": self.harness,
            "task_digest": self.task_digest,
            "command_shape": list(self.command_shape),
            "exit_code": self.exit_code,
            "startup_receipt_id": self.startup_receipt_id,
            "activation_receipt_id": self.activation_receipt_id,
            "cleanup_event_id": self.cleanup_event_id,
            "stdout_digest": self.stdout_digest,
            "stderr_digest": self.stderr_digest,
        }
        return {"receipt_id": self.receipt_id, **payload} if include_id else payload


def parse_expiry(value: str, *, now: datetime | None = None) -> datetime:
    """Parse a bounded duration (`30m`, `2h`, `7d`) or an ISO-8601 instant."""

    current = (now or datetime.now(tz=UTC)).astimezone(UTC)
    units = {"m": 60, "h": 3600, "d": 86400}
    if len(value) >= 2 and value[-1] in units and value[:-1].isdigit():
        seconds = int(value[:-1]) * units[value[-1]]
        if seconds <= 0:
            raise LifecycleError("lease duration must be positive")
        return current + timedelta(seconds=seconds)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LifecycleError(
            "lease expiry must be an ISO-8601 instant or duration such as 30m, 2h, or 7d"
        ) from exc
    if parsed.tzinfo is None:
        raise LifecycleError("lease expiry must include a timezone")
    parsed = parsed.astimezone(UTC)
    if parsed <= current:
        raise LifecycleError("lease expiry must be in the future")
    return parsed


def iso_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def lock_with_lease(
    current: SurfaceLock,
    lease: Lease,
    projection: ExpectedProjection,
) -> SurfaceLock:
    if lease.surface_id != current.surface_id or lease.harness != current.harness:
        raise LifecycleError("lease does not belong to the target surface")
    if projection.authority != f"lease:{lease.lease_id}":
        raise LifecycleError("lease projection authority does not name its lease")
    projections = list(current.projections)
    for existing in projections:
        if existing.skill == projection.skill:
            if existing == projection:
                break
            raise LifecycleError(
                f"candidate {projection.skill!r} collides with desired projection "
                f"owned by {existing.authority!r}"
            )
        if existing.projection_path == projection.projection_path:
            raise LifecycleError(
                f"lease projection target already belongs to {existing.skill!r}"
            )
    else:
        projections.append(projection)
    return SurfaceLock(
        surface_id=current.surface_id,
        surface_name=current.surface_name,
        repo_path=current.repo_path,
        harness=current.harness,
        binding_coordinate=current.binding_coordinate,
        projections=tuple(projections),
        adoption_ids=current.adoption_ids,
        lease_ids=tuple(sorted({*current.lease_ids, lease.lease_id})),
        conflict_decisions=current.conflict_decisions,
    )


def lock_without_leases(
    current: SurfaceLock, lease_ids: Iterable[str]
) -> SurfaceLock:
    removed = frozenset(lease_ids)
    return SurfaceLock(
        surface_id=current.surface_id,
        surface_name=current.surface_name,
        repo_path=current.repo_path,
        harness=current.harness,
        binding_coordinate=current.binding_coordinate,
        projections=tuple(
            projection
            for projection in current.projections
            if projection.authority.removeprefix("lease:") not in removed
            or not projection.authority.startswith("lease:")
        ),
        adoption_ids=current.adoption_ids,
        lease_ids=tuple(item for item in current.lease_ids if item not in removed),
        conflict_decisions=current.conflict_decisions,
    )


def effective_lock_at(
    lock: SurfaceLock,
    *,
    store: LeaseStore | None = None,
    now: datetime | None = None,
) -> tuple[SurfaceLock, tuple[str, ...], tuple[str, ...]]:
    """Return desired state with expired leases removed, without writing it."""

    lease_store = store or LeaseStore()
    moment = (now or datetime.now(tz=UTC)).astimezone(UTC)
    active: list[str] = []
    expired: list[str] = []
    for lease_id in lock.lease_ids:
        lease = lease_store.get(lease_id)
        if lease.surface_id != lock.surface_id or lease.harness != lock.harness:
            raise LifecycleError("surface lock references a lease from another surface")
        if lease.active_at(moment):
            active.append(lease_id)
        elif moment >= datetime.fromisoformat(
            lease.expires_at.replace("Z", "+00:00")
        ).astimezone(UTC):
            expired.append(lease_id)
        else:
            raise LifecycleError(f"lease {lease_id} is not active yet")
    return (
        lock_without_leases(lock, expired) if expired else lock,
        tuple(sorted(active)),
        tuple(sorted(expired)),
    )


def write_lease_plan(plan: LeasePlan, *, root: Path | None = None) -> Path:
    return _write_immutable(root or paths.lease_plans_dir(), plan.plan_id, plan.to_dict())


def write_lease_event(event: LeaseEvent, *, root: Path | None = None) -> Path:
    return _write_immutable(
        root or paths.lease_events_dir(), event.event_id, event.to_dict()
    )


def write_trial_run_receipt(
    receipt: TrialRunReceipt, *, root: Path | None = None
) -> Path:
    return _write_immutable(
        root or paths.trial_run_receipts_dir(), receipt.receipt_id, receipt.to_dict()
    )


def _digest_hex(value: str) -> str:
    prefix, separator, raw = value.partition(":")
    if prefix != "sha256" or separator != ":" or len(raw) != 64:
        raise LifecycleError(f"invalid content identity: {value!r}")
    try:
        int(raw, 16)
    except ValueError as exc:
        raise LifecycleError(f"invalid content identity: {value!r}") from exc
    return raw


def _write_immutable(root: Path, identity: str, payload: dict[str, Any]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{_digest_hex(identity)}.json"
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != serialized:
            raise LifecycleError(f"immutable receipt collision at {target}")
        return target
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{target.name}-", dir=root)
    temp = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
        try:
            os.link(temp, target)
        except FileExistsError:
            if target.read_text(encoding="utf-8") != serialized:
                raise LifecycleError(f"immutable receipt collision at {target}")
    finally:
        temp.unlink(missing_ok=True)
    return target
