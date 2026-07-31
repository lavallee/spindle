"""Provider-neutral contracts for projecting and verifying skill realizations.

Realization receipts record what Spindle selected.  Adapter receipts separately
record how one agent was configured and what the harness later exposed as
runtime evidence.  This module deliberately describes those facts without
invoking a harness or putting harness-specific launch syntax in skill packages.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable

from . import paths
from .realization import RealizationResult

ACTIVATION_RECEIPT_SCHEMA = "spindle.activation-receipt/v1"
DELEGATION_RECEIPT_SCHEMA = "spindle.delegation-receipt/v1"


class AdapterError(ValueError):
    """An adapter plan, observation, or receipt is internally inconsistent."""


class EvidenceAuthority(StrEnum):
    """How an adapter knows a fact.

    Requested and configured values are intent.  Observed values come directly
    from a harness event or result.  Derived values are reproducible
    interpretations of other evidence, such as canonicalizing a raw model id.
    """

    REQUESTED = "requested"
    CONFIGURED = "configured"
    OBSERVED = "observed"
    DERIVED = "derived"


class ProjectionMode(StrEnum):
    """Portable projection mechanisms; adapters map these to harness surfaces."""

    SKILL_PATH = "skill-path"
    AGENT_INSTRUCTIONS = "agent-instructions"


FactValue = str | bool | int | float | tuple[str, ...]


@dataclass(frozen=True)
class EvidenceFact:
    """One typed value with explicit provenance and epistemic authority."""

    value: FactValue
    authority: EvidenceAuthority
    source: str

    def __post_init__(self) -> None:
        if not isinstance(self.authority, EvidenceAuthority):
            raise AdapterError("evidence authority must be an EvidenceAuthority")
        if not self.source.strip():
            raise AdapterError("evidence source must not be empty")
        if isinstance(self.value, str) and not self.value.strip():
            raise AdapterError("string evidence value must not be empty")
        if isinstance(self.value, tuple):
            if any(
                not isinstance(item, str) or not item.strip() for item in self.value
            ):
                raise AdapterError("tuple evidence values must be non-empty strings")

    def to_dict(self) -> dict[str, Any]:
        value: Any = list(self.value) if isinstance(self.value, tuple) else self.value
        return {
            "value": value,
            "authority": self.authority.value,
            "source": self.source,
        }


@dataclass(frozen=True)
class RealizationReference:
    """Immutable link from an adapter plan back to one realization decision."""

    skill: str
    path: Path
    package_digest: str
    realization_digest: str
    realization_receipt_id: str

    @classmethod
    def from_result(cls, result: RealizationResult) -> RealizationReference:
        return cls(
            skill=result.skill,
            path=result.path,
            package_digest=result.package_digest,
            realization_digest=result.realization_digest,
            realization_receipt_id=result.receipt_id,
        )

    def __post_init__(self) -> None:
        for label, value in (
            ("skill", self.skill),
            ("package_digest", self.package_digest),
            ("realization_digest", self.realization_digest),
            ("realization_receipt_id", self.realization_receipt_id),
        ):
            if not value.strip():
                raise AdapterError(f"{label} must not be empty")

    def to_dict(self) -> dict[str, str]:
        return {
            "skill": self.skill,
            "path": str(self.path),
            "package_digest": self.package_digest,
            "realization_digest": self.realization_digest,
            "realization_receipt_id": self.realization_receipt_id,
        }


@dataclass(frozen=True)
class ProjectionPlan:
    """Agent-local intent for projecting one immutable realization."""

    session_id: str
    agent_id: str
    harness: str
    adapter_id: str
    mode: ProjectionMode
    target: str
    realization: RealizationReference
    parent_agent_id: str | None = None
    requested_model: EvidenceFact | None = None
    configured_model: EvidenceFact | None = None
    configured_harness_build: EvidenceFact | None = None
    configured_effort: EvidenceFact | None = None
    configured_role: EvidenceFact | None = None
    configured_tools: EvidenceFact | None = None
    configured_policy: EvidenceFact | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("session_id", self.session_id),
            ("agent_id", self.agent_id),
            ("harness", self.harness),
            ("adapter_id", self.adapter_id),
            ("target", self.target),
        ):
            if not value.strip():
                raise AdapterError(f"{label} must not be empty")
        if self.parent_agent_id is not None and not self.parent_agent_id.strip():
            raise AdapterError("parent_agent_id must not be empty")
        if not isinstance(self.mode, ProjectionMode):
            raise AdapterError("mode must be a ProjectionMode")
        self._require_authority(
            "requested_model", self.requested_model, EvidenceAuthority.REQUESTED
        )
        for name in (
            "configured_model",
            "configured_harness_build",
            "configured_effort",
            "configured_role",
            "configured_tools",
            "configured_policy",
        ):
            self._require_authority(
                name, getattr(self, name), EvidenceAuthority.CONFIGURED
            )
        for name in (
            "requested_model",
            "configured_model",
            "configured_harness_build",
            "configured_effort",
            "configured_role",
            "configured_policy",
        ):
            fact = getattr(self, name)
            if fact is not None and not isinstance(fact.value, str):
                raise AdapterError(f"{name} must be string evidence")
        if self.configured_tools is not None and not isinstance(
            self.configured_tools.value, tuple
        ):
            raise AdapterError("configured_tools must be a tuple of tool names")

    @staticmethod
    def _require_authority(
        name: str, fact: EvidenceFact | None, expected: EvidenceAuthority
    ) -> None:
        if fact is not None and fact.authority is not expected:
            raise AdapterError(f"{name} evidence authority must be {expected.value}")

    @property
    def plan_id(self) -> str:
        return _content_digest(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        model = {
            "requested": _fact_dict(self.requested_model),
            "configured": _fact_dict(self.configured_model),
        }
        configured = {
            "harness_build": _fact_dict(self.configured_harness_build),
            "effort": _fact_dict(self.configured_effort),
            "role": _fact_dict(self.configured_role),
            "tools": _fact_dict(self.configured_tools),
            "policy": _fact_dict(self.configured_policy),
        }
        payload: dict[str, Any] = {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "parent_agent_id": self.parent_agent_id,
            "harness": self.harness,
            "adapter_id": self.adapter_id,
            "projection": {"mode": self.mode.value, "target": self.target},
            "realization": self.realization.to_dict(),
            "model": model,
            "configured": configured,
        }
        if include_id:
            payload = {"plan_id": self.plan_id, **payload}
        return payload


@dataclass(frozen=True)
class PermissionDenial:
    """An observed refusal by the effective harness permission boundary."""

    capability: str
    reason: str
    evidence: EvidenceFact

    def __post_init__(self) -> None:
        if not self.capability.strip():
            raise AdapterError("permission denial capability must not be empty")
        if not self.reason.strip():
            raise AdapterError("permission denial reason must not be empty")
        if self.evidence.authority is not EvidenceAuthority.OBSERVED:
            raise AdapterError("permission denial evidence authority must be observed")

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "reason": self.reason,
            "evidence": self.evidence.to_dict(),
        }


@dataclass(frozen=True)
class ActivationEvidence:
    """Post-projection evidence for the exact agent named by a plan."""

    projection_loaded: EvidenceFact
    served_model_raw: EvidenceFact | None = None
    served_model_canonical: EvidenceFact | None = None
    observed_harness_build: EvidenceFact | None = None
    effective_tools: EvidenceFact | None = None
    effective_policy: EvidenceFact | None = None
    permission_denials: tuple[PermissionDenial, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.projection_loaded.value, bool):
            raise AdapterError("projection_loaded must be boolean evidence")
        self._require_runtime_authority("projection_loaded", self.projection_loaded)
        self._require_runtime_authority("served_model_raw", self.served_model_raw)
        self._require_runtime_authority(
            "served_model_canonical", self.served_model_canonical
        )
        self._require_runtime_authority(
            "observed_harness_build", self.observed_harness_build
        )
        self._require_runtime_authority("effective_tools", self.effective_tools)
        self._require_runtime_authority("effective_policy", self.effective_policy)
        if self.served_model_raw is None and self.served_model_canonical is not None:
            raise AdapterError(
                "canonical served model requires raw served model evidence"
            )
        for name in (
            "served_model_raw",
            "served_model_canonical",
            "observed_harness_build",
            "effective_policy",
        ):
            fact = getattr(self, name)
            if fact is not None and not isinstance(fact.value, str):
                raise AdapterError(f"{name} must be string evidence")
        if self.effective_tools is not None and not isinstance(
            self.effective_tools.value, tuple
        ):
            raise AdapterError("effective_tools must be a tuple of tool names")

    @staticmethod
    def _require_runtime_authority(name: str, fact: EvidenceFact | None) -> None:
        if fact is not None and fact.authority not in {
            EvidenceAuthority.OBSERVED,
            EvidenceAuthority.DERIVED,
        }:
            raise AdapterError(f"{name} evidence must be observed or derived")

    def to_dict(self) -> dict[str, Any]:
        return {
            "projection_loaded": self.projection_loaded.to_dict(),
            "model": {
                "served_raw": _fact_dict(self.served_model_raw),
                "served_canonical": _fact_dict(self.served_model_canonical),
            },
            "harness": {
                "build": _fact_dict(self.observed_harness_build),
            },
            "effective": {
                "tools": _fact_dict(self.effective_tools),
                "policy": _fact_dict(self.effective_policy),
            },
            "permission_denials": [item.to_dict() for item in self.permission_denials],
        }


@dataclass(frozen=True)
class AdapterDescriptor:
    """A launch-syntax-free description of a harness adapter's capabilities."""

    id: str
    harness: str
    projection_modes: tuple[ProjectionMode, ...]
    runtime_evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.harness.strip():
            raise AdapterError("adapter id and harness must not be empty")
        if not self.projection_modes:
            raise AdapterError("adapter must support at least one projection mode")
        if any(not isinstance(mode, ProjectionMode) for mode in self.projection_modes):
            raise AdapterError("adapter projection modes must be ProjectionMode values")

    def validate_plan(self, plan: ProjectionPlan) -> None:
        if plan.adapter_id != self.id:
            raise AdapterError(
                f"plan adapter {plan.adapter_id!r} does not match descriptor {self.id!r}"
            )
        if plan.harness != self.harness:
            raise AdapterError(
                f"plan harness {plan.harness!r} does not match descriptor {self.harness!r}"
            )
        if plan.mode not in self.projection_modes:
            raise AdapterError(
                f"adapter {self.id!r} does not support {plan.mode.value!r} projection"
            )


CLAUDE_CODE_ADAPTER = AdapterDescriptor(
    id="claude-code-reference/v1",
    harness="claude",
    projection_modes=(ProjectionMode.SKILL_PATH, ProjectionMode.AGENT_INSTRUCTIONS),
    runtime_evidence=(
        "projection-loaded",
        "harness-build",
        "served-model",
        "effective-tools",
        "effective-policy",
        "permission-denials",
    ),
)

CODEX_ADAPTER = AdapterDescriptor(
    id="codex-reference/v1",
    harness="codex",
    projection_modes=(ProjectionMode.SKILL_PATH, ProjectionMode.AGENT_INSTRUCTIONS),
    runtime_evidence=(
        "projection-loaded",
        "harness-build",
        "served-model",
        "effective-tools",
        "effective-policy",
        "permission-denials",
    ),
)

REFERENCE_ADAPTERS = {
    CLAUDE_CODE_ADAPTER.harness: CLAUDE_CODE_ADAPTER,
    CODEX_ADAPTER.harness: CODEX_ADAPTER,
}


@dataclass(frozen=True)
class ActivationReceipt:
    receipt_id: str
    receipt_path: Path
    plan: ProjectionPlan
    evidence: ActivationEvidence

    def participant_dict(self) -> dict[str, Any]:
        """The transitive links a delegation receipt retains for this agent."""

        return {
            "agent_id": self.plan.agent_id,
            "parent_agent_id": self.plan.parent_agent_id,
            "activation_receipt_id": self.receipt_id,
            "realization_receipt_id": self.plan.realization.realization_receipt_id,
            "package_digest": self.plan.realization.package_digest,
            "realization_digest": self.plan.realization.realization_digest,
            "served_model_raw": _fact_dict(self.evidence.served_model_raw),
            "served_model_canonical": _fact_dict(self.evidence.served_model_canonical),
        }


@dataclass(frozen=True)
class DelegationReceipt:
    receipt_id: str
    receipt_path: Path
    delegation_id: str
    parent: ActivationReceipt
    children: tuple[ActivationReceipt, ...]


def write_activation_receipt(
    plan: ProjectionPlan,
    evidence: ActivationEvidence,
    *,
    receipt_root: Path | None = None,
) -> ActivationReceipt:
    """Persist one content-addressed intent-plus-observation receipt."""

    descriptor = REFERENCE_ADAPTERS.get(plan.harness)
    if descriptor is not None and plan.adapter_id == descriptor.id:
        descriptor.validate_plan(plan)
    payload = {
        "projection_plan": plan.to_dict(),
        "activation_evidence": evidence.to_dict(),
    }
    receipt_id, receipt_path = _write_content_receipt(
        ACTIVATION_RECEIPT_SCHEMA,
        payload,
        receipt_root=receipt_root or paths.activation_receipts_dir(),
    )
    return ActivationReceipt(receipt_id, receipt_path, plan, evidence)


def write_delegation_receipt(
    delegation_id: str,
    parent: ActivationReceipt,
    children: Iterable[ActivationReceipt],
    *,
    receipt_root: Path | None = None,
) -> DelegationReceipt:
    """Join independently activated parent/child realizations into one receipt."""

    child_receipts = tuple(children)
    if not delegation_id.strip():
        raise AdapterError("delegation_id must not be empty")
    if not child_receipts:
        raise AdapterError("delegation receipt requires at least one child")
    seen = {parent.plan.agent_id}
    for child in child_receipts:
        if child.plan.agent_id in seen:
            raise AdapterError(f"duplicate delegation agent id: {child.plan.agent_id}")
        seen.add(child.plan.agent_id)
        if child.plan.session_id != parent.plan.session_id:
            raise AdapterError("parent and child must share a session_id")
        if child.plan.parent_agent_id != parent.plan.agent_id:
            raise AdapterError(
                f"child {child.plan.agent_id!r} does not name parent "
                f"{parent.plan.agent_id!r}"
            )

    payload = {
        "delegation_id": delegation_id,
        "session_id": parent.plan.session_id,
        "parent": parent.participant_dict(),
        "children": [child.participant_dict() for child in child_receipts],
    }
    receipt_id, receipt_path = _write_content_receipt(
        DELEGATION_RECEIPT_SCHEMA,
        payload,
        receipt_root=receipt_root or paths.delegation_receipts_dir(),
    )
    return DelegationReceipt(
        receipt_id,
        receipt_path,
        delegation_id,
        parent,
        child_receipts,
    )


def _fact_dict(fact: EvidenceFact | None) -> dict[str, Any] | None:
    return fact.to_dict() if fact is not None else None


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AdapterError(f"receipt contains non-JSON evidence: {exc}") from exc


def _content_digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_content_receipt(
    schema: str,
    payload: dict[str, Any],
    *,
    receipt_root: Path,
) -> tuple[str, Path]:
    addressed = {"schema": schema, **payload}
    receipt_id = _content_digest(addressed)
    receipt = {
        "schema": schema,
        "receipt_id": receipt_id,
        "created_at": _now_iso(),
        **payload,
    }
    receipt_root.mkdir(parents=True, exist_ok=True)
    destination = receipt_root / f"{receipt_id}.json"
    if destination.exists():
        _verify_existing_receipt(destination, addressed, receipt_id)
        return receipt_id, destination

    fd, raw_temp = tempfile.mkstemp(prefix=f".{receipt_id[:12]}-", dir=receipt_root)
    temp_path = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(receipt, handle, indent=2, sort_keys=True)
            handle.write("\n")
        try:
            os.link(temp_path, destination)
        except FileExistsError:
            _verify_existing_receipt(destination, addressed, receipt_id)
    finally:
        temp_path.unlink(missing_ok=True)
    return receipt_id, destination


def _verify_existing_receipt(
    path: Path, addressed: dict[str, Any], receipt_id: str
) -> None:
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterError(f"invalid existing receipt at {path}: {exc}") from exc
    stable = {
        key: value
        for key, value in existing.items()
        if key not in {"receipt_id", "created_at"}
    }
    if existing.get("receipt_id") != receipt_id or stable != addressed:
        raise AdapterError(f"receipt store collision at {path}")
