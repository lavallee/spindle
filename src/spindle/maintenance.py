"""Durable adoption, update, health, rollback, and retirement records."""

from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from . import paths
from .lifecycle import (
    ExpectedProjection,
    LifecycleError,
    SkillRef,
    SurfaceLock,
    content_id,
    digest_path,
)

ADOPTION_RECORD_SCHEMA = "spindle.adoption-record/v2"
ADOPTION_PLAN_SCHEMA = "spindle.adoption-plan/v1"
MAINTENANCE_EVENT_SCHEMA = "spindle.maintenance-event/v1"
MAINTENANCE_INDEX_SCHEMA = "spindle.maintenance-index/v1"
HEALTH_REPORT_SCHEMA = "spindle.health-report/v1"

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_STATUS = frozenset({"active", "disabled", "deprecated", "retired"})
_OPERATIONS = frozenset(
    {"adopt", "update-promote", "rollback", "disable", "enable", "deprecate", "retire"}
)


def _require(label: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleError(f"{label} must not be empty")


def _digest(label: str, value: str) -> None:
    if not _DIGEST.fullmatch(value):
        raise LifecycleError(f"{label} must be a full sha256 digest")


@dataclass(frozen=True)
class AdoptionRecord:
    skill: str
    package_name: str
    package_digest: str
    skill_digest: str
    skill_subpath: str
    source: SkillRef
    surface_id: str
    harness: str
    scope: str
    owner: str
    adopted_at: str
    update_reference: str
    authority_ceiling: str
    retirement_policy: str
    lease_id: str
    trial_run_receipt_id: str
    activation_receipt_id: str
    preflight_report_id: str | None = None
    source_receipt_id: str | None = None
    previous_adoption_id: str | None = None
    evidence_coordinate: tuple[tuple[str, str], ...] = ()
    evaluation_claim_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for label, value in (
            ("skill", self.skill),
            ("package_name", self.package_name),
            ("skill_subpath", self.skill_subpath),
            ("surface_id", self.surface_id),
            ("harness", self.harness),
            ("scope", self.scope),
            ("owner", self.owner),
            ("adopted_at", self.adopted_at),
            ("update_reference", self.update_reference),
            ("authority_ceiling", self.authority_ceiling),
            ("retirement_policy", self.retirement_policy),
            ("lease_id", self.lease_id),
            ("trial_run_receipt_id", self.trial_run_receipt_id),
            ("activation_receipt_id", self.activation_receipt_id),
        ):
            _require(label, value)
        for label, value in (
            ("package_digest", self.package_digest),
            ("skill_digest", self.skill_digest),
            ("surface_id", self.surface_id),
            ("lease_id", self.lease_id),
            ("trial_run_receipt_id", self.trial_run_receipt_id),
        ):
            _digest(label, value)
        for label, value in (
            ("preflight_report_id", self.preflight_report_id),
            ("source_receipt_id", self.source_receipt_id),
            ("previous_adoption_id", self.previous_adoption_id),
        ):
            if value is not None:
                _digest(label, value)
        if self.scope != "repo":
            raise LifecycleError("adoption scope currently must be repo")
        if self.authority_ceiling not in {"read-only", "sandboxed", "full"}:
            raise LifecycleError("unsupported adoption authority ceiling")
        if self.skill_subpath.startswith("/") or ".." in Path(self.skill_subpath).parts:
            raise LifecycleError("adoption skill subpath must remain within its package")
        if len(dict(self.evidence_coordinate)) != len(self.evidence_coordinate):
            raise LifecycleError("adoption evidence coordinate keys must be unique")
        for claim in self.evaluation_claim_ids:
            _require("evaluation claim id", claim)

    @property
    def adoption_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "schema": ADOPTION_RECORD_SCHEMA,
            "skill": self.skill,
            "package_name": self.package_name,
            "package_digest": self.package_digest,
            "skill_digest": self.skill_digest,
            "skill_subpath": self.skill_subpath,
            "source": self.source.to_dict(),
            "surface_id": self.surface_id,
            "harness": self.harness,
            "scope": self.scope,
            "owner": self.owner,
            "adopted_at": self.adopted_at,
            "update_reference": self.update_reference,
            "authority_ceiling": self.authority_ceiling,
            "retirement_policy": self.retirement_policy,
            "lease_id": self.lease_id,
            "trial_run_receipt_id": self.trial_run_receipt_id,
            "activation_receipt_id": self.activation_receipt_id,
            "preflight_report_id": self.preflight_report_id,
            "source_receipt_id": self.source_receipt_id,
            "previous_adoption_id": self.previous_adoption_id,
            "evidence_coordinate": dict(sorted(self.evidence_coordinate)),
            "evaluation_claim_ids": sorted(self.evaluation_claim_ids),
        }
        return {"adoption_id": self.adoption_id, **payload} if include_id else payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AdoptionRecord:
        if raw.get("schema") != ADOPTION_RECORD_SCHEMA:
            raise LifecycleError("unsupported adoption record schema")
        source = raw.get("source")
        coordinate = raw.get("evidence_coordinate", {})
        claims = raw.get("evaluation_claim_ids", [])
        if not isinstance(source, dict) or not isinstance(coordinate, dict):
            raise LifecycleError("adoption source and evidence coordinate must be objects")
        if not isinstance(claims, list):
            raise LifecycleError("adoption evaluation claims must be a list")
        record = cls(
            skill=str(raw["skill"]),
            package_name=str(raw["package_name"]),
            package_digest=str(raw["package_digest"]),
            skill_digest=str(raw["skill_digest"]),
            skill_subpath=str(raw["skill_subpath"]),
            source=SkillRef.from_dict(source),
            surface_id=str(raw["surface_id"]),
            harness=str(raw["harness"]),
            scope=str(raw["scope"]),
            owner=str(raw["owner"]),
            adopted_at=str(raw["adopted_at"]),
            update_reference=str(raw["update_reference"]),
            authority_ceiling=str(raw["authority_ceiling"]),
            retirement_policy=str(raw["retirement_policy"]),
            lease_id=str(raw["lease_id"]),
            trial_run_receipt_id=str(raw["trial_run_receipt_id"]),
            activation_receipt_id=str(raw["activation_receipt_id"]),
            preflight_report_id=_optional_text(raw.get("preflight_report_id")),
            source_receipt_id=_optional_text(raw.get("source_receipt_id")),
            previous_adoption_id=_optional_text(raw.get("previous_adoption_id")),
            evidence_coordinate=tuple(
                sorted((str(key), str(value)) for key, value in coordinate.items())
            ),
            evaluation_claim_ids=tuple(str(item) for item in claims),
        )
        if raw.get("adoption_id") not in {None, record.adoption_id}:
            raise LifecycleError("adoption record content does not match adoption_id")
        return record

    def cached_package_path(self, cache_root: Path | None = None) -> Path:
        root = cache_root or paths.package_cache_dir()
        return root / self.package_digest.removeprefix("sha256:") / self.package_name

    def cached_skill_path(self, cache_root: Path | None = None) -> Path:
        package = self.cached_package_path(cache_root)
        return package if self.skill_subpath == "." else package / self.skill_subpath


class AdoptionStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or paths.adoption_receipts_dir()

    def record(self, adoption: AdoptionRecord) -> Path:
        return _write_immutable(self.root, adoption.adoption_id, adoption.to_dict())

    def get(self, adoption_id: str) -> AdoptionRecord:
        target = self.root / f"{_digest_hex(adoption_id)}.json"
        raw = _read_object(target, "adoption record")
        record = AdoptionRecord.from_dict(raw)
        if record.adoption_id != adoption_id or target.stem != _digest_hex(adoption_id):
            raise LifecycleError("adoption store identity mismatch")
        return record

    def list(self) -> tuple[AdoptionRecord, ...]:
        if not self.root.is_dir():
            return ()
        records: list[AdoptionRecord] = []
        for target in sorted(self.root.glob("*.json")):
            record = AdoptionRecord.from_dict(_read_object(target, "adoption record"))
            if target.stem != _digest_hex(record.adoption_id):
                raise LifecycleError(f"adoption filename identity mismatch at {target}")
            records.append(record)
        return tuple(records)


@dataclass(frozen=True)
class AdoptionPlan:
    operation: str
    skill: str
    surface_id: str
    current_lock_id: str
    proposed_lock: SurfaceLock
    adoption: AdoptionRecord | None
    affected_adoption_id: str | None
    evidence_receipt_id: str | None
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.operation not in _OPERATIONS:
            raise LifecycleError(f"unsupported adoption operation: {self.operation}")

    @property
    def plan_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "schema": ADOPTION_PLAN_SCHEMA,
            "operation": self.operation,
            "skill": self.skill,
            "surface_id": self.surface_id,
            "current_lock_id": self.current_lock_id,
            "proposed_lock": self.proposed_lock.to_dict(),
            "adoption": self.adoption.to_dict() if self.adoption else None,
            "affected_adoption_id": self.affected_adoption_id,
            "evidence_receipt_id": self.evidence_receipt_id,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            # Adoption currently changes only the surface lock. Keep the other
            # durable scopes explicit so preview consumers never infer them.
            "distribution_change": None,
            "channel_change": None,
        }
        return {"plan_id": self.plan_id, **payload} if include_id else payload


@dataclass(frozen=True)
class MaintenanceEvent:
    operation: str
    skill: str
    surface_id: str
    adoption_id: str
    previous_adoption_id: str | None
    prior_lock_id: str
    next_lock_id: str
    reason: str
    actor: str
    observed_at: str
    startup_receipt_id: str | None

    def __post_init__(self) -> None:
        if self.operation not in _OPERATIONS:
            raise LifecycleError(f"unsupported maintenance event: {self.operation}")
        for label, value in (
            ("skill", self.skill),
            ("surface_id", self.surface_id),
            ("adoption_id", self.adoption_id),
            ("prior_lock_id", self.prior_lock_id),
            ("next_lock_id", self.next_lock_id),
            ("reason", self.reason),
            ("actor", self.actor),
            ("observed_at", self.observed_at),
        ):
            _require(label, value)
        for label, value in (
            ("surface_id", self.surface_id),
            ("adoption_id", self.adoption_id),
            ("prior_lock_id", self.prior_lock_id),
            ("next_lock_id", self.next_lock_id),
        ):
            _digest(label, value)
        if self.previous_adoption_id is not None:
            _digest("previous_adoption_id", self.previous_adoption_id)

    @property
    def event_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "schema": MAINTENANCE_EVENT_SCHEMA,
            "operation": self.operation,
            "skill": self.skill,
            "surface_id": self.surface_id,
            "adoption_id": self.adoption_id,
            "previous_adoption_id": self.previous_adoption_id,
            "prior_lock_id": self.prior_lock_id,
            "next_lock_id": self.next_lock_id,
            "reason": self.reason,
            "actor": self.actor,
            "observed_at": self.observed_at,
            "startup_receipt_id": self.startup_receipt_id,
        }
        return {"event_id": self.event_id, **payload} if include_id else payload


@dataclass(frozen=True)
class HealthReport:
    surface_id: str
    lock_id: str | None
    inventory_id: str
    current_coordinate: tuple[tuple[str, str], ...]
    skills: tuple[dict[str, Any], ...]

    @property
    def report_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "schema": HEALTH_REPORT_SCHEMA,
            "surface_id": self.surface_id,
            "lock_id": self.lock_id,
            "inventory_id": self.inventory_id,
            "current_coordinate": dict(sorted(self.current_coordinate)),
            "skills": list(self.skills),
        }
        return {"report_id": self.report_id, **payload} if include_id else payload


def projection_for_adoption(
    adoption: AdoptionRecord, projection_path: Path
) -> ExpectedProjection:
    skill_path = adoption.cached_skill_path()
    if skill_path.is_symlink() or not skill_path.is_dir():
        raise LifecycleError("adopted skill bytes are absent from the package cache")
    if digest_path(skill_path) != adoption.skill_digest:
        raise LifecycleError("adopted skill cache digest mismatch")
    return ExpectedProjection(
        skill=adoption.skill,
        projection_path=str(projection_path.absolute()),
        source_path=str(skill_path.absolute()),
        source_digest=adoption.skill_digest,
        package_digest=adoption.package_digest,
        authority=f"adoption:{adoption.adoption_id}",
    )


def lock_with_adoption(
    current: SurfaceLock,
    adoption: AdoptionRecord,
    projection: ExpectedProjection,
    *,
    remove_lease_id: str | None = None,
    replace_adoption_id: str | None = None,
) -> SurfaceLock:
    if current.surface_id != adoption.surface_id or current.harness != adoption.harness:
        raise LifecycleError("adoption does not belong to the target surface")
    removed_authorities = {
        value
        for value in (
            f"lease:{remove_lease_id}" if remove_lease_id else None,
            f"adoption:{replace_adoption_id}" if replace_adoption_id else None,
        )
        if value is not None
    }
    projections = [
        item for item in current.projections if item.authority not in removed_authorities
    ]
    for existing in projections:
        if existing.skill == projection.skill or existing.projection_path == projection.projection_path:
            raise LifecycleError(
                f"adoption {projection.skill!r} collides with {existing.authority!r}"
            )
    projections.append(projection)
    adoption_ids = set(current.adoption_ids)
    if replace_adoption_id:
        adoption_ids.discard(replace_adoption_id)
    adoption_ids.add(adoption.adoption_id)
    lease_ids = set(current.lease_ids)
    if remove_lease_id:
        lease_ids.discard(remove_lease_id)
    return SurfaceLock(
        surface_id=current.surface_id,
        surface_name=current.surface_name,
        repo_path=current.repo_path,
        harness=current.harness,
        binding_coordinate=current.binding_coordinate,
        projections=tuple(projections),
        adoption_ids=tuple(sorted(adoption_ids)),
        lease_ids=tuple(sorted(lease_ids)),
        conflict_decisions=current.conflict_decisions,
    )


def lock_without_adoption(current: SurfaceLock, adoption_id: str) -> SurfaceLock:
    return SurfaceLock(
        surface_id=current.surface_id,
        surface_name=current.surface_name,
        repo_path=current.repo_path,
        harness=current.harness,
        binding_coordinate=current.binding_coordinate,
        projections=tuple(
            item
            for item in current.projections
            if item.authority != f"adoption:{adoption_id}"
        ),
        adoption_ids=tuple(item for item in current.adoption_ids if item != adoption_id),
        lease_ids=current.lease_ids,
        conflict_decisions=current.conflict_decisions,
    )


def write_adoption_plan(plan: AdoptionPlan) -> Path:
    return _write_immutable(paths.adoption_plans_dir(), plan.plan_id, plan.to_dict())


def write_maintenance_event(event: MaintenanceEvent) -> Path:
    return _write_immutable(paths.maintenance_events_dir(), event.event_id, event.to_dict())


def current_status(surface_id: str, skill: str) -> dict[str, Any] | None:
    raw = _read_index(paths.maintenance_index_file())
    surface = raw["surfaces"].get(surface_id, {})
    skills = surface.get("skills", {}) if isinstance(surface, dict) else {}
    value = skills.get(skill) if isinstance(skills, dict) else None
    return dict(value) if isinstance(value, dict) else None


def record_status(event: MaintenanceEvent, status: str) -> None:
    if status not in _STATUS:
        raise LifecycleError(f"unsupported maintenance status: {status}")
    target = paths.maintenance_index_file()
    with _index_lock(target):
        raw = _read_index(target)
        surface = raw["surfaces"].setdefault(event.surface_id, {"skills": {}})
        if not isinstance(surface, dict):
            raise LifecycleError("maintenance surface index is malformed")
        skills = surface.setdefault("skills", {})
        if not isinstance(skills, dict):
            raise LifecycleError("maintenance skill index is malformed")
        skills[event.skill] = {
            "status": status,
            "adoption_id": event.adoption_id,
            "previous_adoption_id": event.previous_adoption_id,
            "event_id": event.event_id,
            "reason": event.reason,
        }
        _write_json_atomic(target, raw)


def find_successful_trial(lease_id: str) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    root = paths.trial_run_receipts_dir()
    if root.is_dir():
        for target in sorted(root.glob("*.json")):
            raw = _read_object(target, "trial run receipt")
            identity = content_id({key: value for key, value in raw.items() if key != "receipt_id"})
            if raw.get("receipt_id") != identity or target.stem != _digest_hex(identity):
                raise LifecycleError(f"trial run receipt identity mismatch at {target}")
            if (
                raw.get("lease_id") == lease_id
                and raw.get("exit_code") == 0
                and isinstance(raw.get("activation_receipt_id"), str)
                and isinstance(raw.get("cleanup_event_id"), str)
            ):
                matches.append(raw)
    if not matches:
        raise LifecycleError("adoption requires a zero-exit trial run receipt for the lease")
    return sorted(matches, key=lambda item: str(item["receipt_id"]))[-1]


def find_lease_plan_facts(lease_id: str) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    root = paths.lease_plans_dir()
    if root.is_dir():
        for target in sorted(root.glob("*.json")):
            raw = _read_object(target, "lease plan")
            identity = content_id(
                {key: value for key, value in raw.items() if key != "plan_id"}
            )
            if raw.get("plan_id") != identity or target.stem != _digest_hex(identity):
                raise LifecycleError(f"lease plan identity mismatch at {target}")
            if raw.get("lease", {}).get("lease_id") == lease_id and raw.get("operation") in {
                "try",
                "borrow",
                "update-try",
            }:
                matches.append(raw)
    if not matches:
        raise LifecycleError("lease has no provenance-bearing creation plan")
    return sorted(matches, key=lambda item: str(item.get("plan_id")))[-1]


def activation_coordinate(receipt_id: str) -> tuple[tuple[str, str], ...]:
    target = paths.activation_receipts_dir() / f"{receipt_id.removeprefix('sha256:')}.json"
    raw = _read_object(target, "activation receipt")
    plan = raw.get("projection_plan", {})
    evidence = raw.get("activation_evidence", {})
    coordinate: dict[str, str] = {}
    if isinstance(plan, dict):
        if plan.get("harness"):
            coordinate["harness"] = str(plan["harness"])
        model = plan.get("model", {})
        if isinstance(model, dict):
            configured = model.get("configured") or model.get("requested")
            if isinstance(configured, dict) and configured.get("value"):
                coordinate["model"] = str(configured["value"])
        configured = plan.get("configured", {})
        if isinstance(configured, dict):
            _coordinate_fact(coordinate, "harness_build", configured.get("harness_build"))
            tools = configured.get("tools")
            if isinstance(tools, dict) and tools.get("value") is not None:
                coordinate["toolset_digest"] = content_id({"tools": tools["value"]})
            policy = configured.get("policy")
            if isinstance(policy, dict) and policy.get("value") is not None:
                coordinate["policy_digest"] = content_id({"policy": policy["value"]})
    if isinstance(evidence, dict):
        model = evidence.get("model", {})
        if isinstance(model, dict):
            served = model.get("served_canonical") or model.get("served_raw")
            if isinstance(served, dict) and served.get("value"):
                coordinate["model"] = str(served["value"])
        harness = evidence.get("harness", {})
        if isinstance(harness, dict):
            _coordinate_fact(coordinate, "harness_build", harness.get("build"))
        effective = evidence.get("effective", {})
        if isinstance(effective, dict):
            tools = effective.get("tools")
            if isinstance(tools, dict) and tools.get("value") is not None:
                coordinate["toolset_digest"] = content_id({"tools": tools["value"]})
            policy = effective.get("policy")
            if isinstance(policy, dict) and policy.get("value") is not None:
                coordinate["policy_digest"] = content_id({"policy": policy["value"]})
    return tuple(sorted(coordinate.items()))


def active_adoptions(lock: SurfaceLock, store: AdoptionStore | None = None) -> tuple[AdoptionRecord, ...]:
    records = store or AdoptionStore()
    return tuple(records.get(adoption_id) for adoption_id in sorted(lock.adoption_ids))


def health_report(
    lock: SurfaceLock | None,
    *,
    surface_id: str,
    inventory_id: str,
    current_coordinate: Iterable[tuple[str, str]],
    inventory_findings: Iterable[tuple[str, str]] = (),
    store: AdoptionStore | None = None,
) -> HealthReport:
    current = dict(current_coordinate)
    runtime_findings: dict[str, set[str]] = {}
    for skill, finding in inventory_findings:
        runtime_findings.setdefault(skill, set()).add(finding)
    adoption_store = store or AdoptionStore()
    rows: list[dict[str, Any]] = []
    active_ids = set(lock.adoption_ids if lock else ())
    records = {record.adoption_id: record for record in adoption_store.list()}
    indexed = _read_index(paths.maintenance_index_file())["surfaces"].get(surface_id, {})
    indexed_skills = indexed.get("skills", {}) if isinstance(indexed, dict) else {}
    relevant = {
        record.skill: record
        for identity, record in records.items()
        if record.surface_id == surface_id and identity in active_ids
    }
    if isinstance(indexed_skills, dict):
        for skill, state in indexed_skills.items():
            if skill in relevant or not isinstance(state, dict):
                continue
            identity = state.get("adoption_id")
            if identity in records:
                relevant[str(skill)] = records[str(identity)]
    for skill, adoption in sorted(relevant.items()):
        state = current_status(surface_id, skill) or {
            "status": "active" if adoption.adoption_id in active_ids else "unknown"
        }
        evidence = dict(adoption.evidence_coordinate)
        drift: list[str] = []
        for key, value in current.items():
            expected = evidence.get(key)
            if key == "source_revision":
                expected = adoption.source.revision
            elif key == "package_digest":
                expected = adoption.package_digest
            if expected not in {None, value}:
                drift.append(key)
        drift.sort()
        cache_state = "ok"
        path = adoption.cached_skill_path()
        if path.is_symlink() or not path.is_dir():
            cache_state = "missing"
        elif digest_path(path) != adoption.skill_digest:
            cache_state = "digest-mismatch"
        projection_state = "inactive"
        if lock is not None:
            matches = [
                item
                for item in lock.projections
                if item.authority == f"adoption:{adoption.adoption_id}"
            ]
            projection_state = "expected" if len(matches) == 1 else "missing"
        findings: list[str] = []
        if drift:
            findings.append("stale-evidence:" + ",".join(drift))
        if cache_state != "ok":
            findings.append("cache-" + cache_state)
        if not adoption.evaluation_claim_ids:
            findings.append("behavioral-contribution-unassessed")
        if state.get("status") == "deprecated":
            findings.append("deprecated")
        findings.extend(sorted(runtime_findings.get(skill, ())))
        source_freshness = "unchecked"
        if current.get("source_revision"):
            source_freshness = (
                "current"
                if current["source_revision"] == adoption.source.revision
                else "changed"
            )
        rows.append(
            {
                "skill": skill,
                "status": state.get("status"),
                "adoption_id": adoption.adoption_id,
                "package_digest": adoption.package_digest,
                "source_revision": adoption.source.revision,
                "source_freshness": source_freshness,
                "last_activation_receipt_id": adoption.activation_receipt_id,
                "last_behavioral_claim_id": (
                    adoption.evaluation_claim_ids[-1]
                    if adoption.evaluation_claim_ids
                    else None
                ),
                "evidence_coverage": sorted(evidence),
                "evidence_drift": drift,
                "cache_state": cache_state,
                "projection_state": projection_state,
                "findings": findings,
            }
        )
    return HealthReport(
        surface_id=surface_id,
        lock_id=lock.lock_id if lock else None,
        inventory_id=inventory_id,
        current_coordinate=tuple(sorted(current.items())),
        skills=tuple(rows),
    )


def _coordinate_fact(target: dict[str, str], key: str, fact: Any) -> None:
    if isinstance(fact, dict) and fact.get("value") is not None:
        target[key] = str(fact["value"])


def _optional_text(value: Any) -> str | None:
    return str(value) if value is not None else None


def _digest_hex(value: str) -> str:
    _digest("content identity", value)
    return value.removeprefix("sha256:")


def _read_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise LifecycleError(f"invalid or missing {label} at {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError(f"invalid {label} at {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise LifecycleError(f"{label} at {path} must be an object")
    return raw


def _read_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": MAINTENANCE_INDEX_SCHEMA, "surfaces": {}}
    raw = _read_object(path, "maintenance index")
    if raw.get("schema") != MAINTENANCE_INDEX_SCHEMA or not isinstance(
        raw.get("surfaces"), dict
    ):
        raise LifecycleError(f"unsupported maintenance index at {path}")
    return raw


@contextmanager
def _index_lock(path: Path) -> Iterator[None]:
    lock = path.with_suffix(path.suffix + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_immutable(root: Path, identity: str, payload: dict[str, Any]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{_digest_hex(identity)}.json"
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != serialized:
            raise LifecycleError(f"immutable receipt collision at {target}")
        return target
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{target.name}-", dir=root)
    temporary = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.read_text(encoding="utf-8") != serialized:
                raise LifecycleError(f"immutable receipt collision at {target}")
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
