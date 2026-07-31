"""Adapter capability negotiation and evidence-backed build certification."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import adapters, paths
from .lifecycle import content_id

OBSERVATION_SCHEMA = "spindle.adapter-conformance-observation/v1"
CERTIFICATION_SCHEMA = "spindle.adapter-certification/v1"
MATRIX_SCHEMA = "spindle.adapter-capability-matrix/v1"

CASES = (
    "inventory",
    "bootstrap",
    "projection",
    "model-identity",
    "effective-tools",
    "effective-policy",
    "subagent-independence",
    "resume-reload",
    "restart",
    "receipt-integrity",
)
STATUSES = frozenset({"pass", "partial", "fail", "unknown"})


class ConformanceError(ValueError):
    """Raised when adapter certification evidence is incomplete or corrupt."""


@dataclass(frozen=True)
class CapabilityRequirement:
    name: str
    required_status: str = "pass"

    def __post_init__(self) -> None:
        if self.name not in CASES or self.required_status not in {"pass", "partial"}:
            raise ConformanceError("invalid capability requirement")


def capability_matrix(
    harness: str,
    *,
    harness_build: str,
    observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    descriptor = adapters.REFERENCE_ADAPTERS.get(harness)
    if descriptor is None:
        raise ConformanceError(f"no reference adapter for {harness!r}")
    statuses = {
        "inventory": "pass",
        "bootstrap": "pass",
        "projection": "pass",
        "model-identity": "partial",
        "effective-tools": "partial",
        "effective-policy": "partial",
        "subagent-independence": "partial",
        "resume-reload": "pass",
        "restart": "pass",
        "receipt-integrity": "pass",
    }
    evidence: dict[str, list[dict[str, str]]] = {name: [] for name in CASES}
    if observation is not None:
        validated = validate_observation(observation)
        if validated["harness"] != harness or validated["harness_build"] != harness_build:
            raise ConformanceError("observation does not match requested harness/build")
        for name, case in validated["cases"].items():
            statuses[name] = case["status"]
            evidence[name] = [_portable_artifact(item) for item in case["evidence"]]
    body = {
        "schema": MATRIX_SCHEMA,
        "harness": harness,
        "harness_build": harness_build,
        "adapter_id": descriptor.id,
        "projection_modes": [mode.value for mode in descriptor.projection_modes],
        "capabilities": {
            name: {"status": statuses[name], "evidence": evidence[name]}
            for name in CASES
        },
    }
    return {"matrix_id": content_id(body), **body}


def negotiate(
    matrix: dict[str, Any], requirements: Iterable[CapabilityRequirement]
) -> dict[str, Any]:
    capabilities = matrix.get("capabilities")
    if not isinstance(capabilities, dict):
        raise ConformanceError("capability matrix is malformed")
    rows: list[dict[str, str]] = []
    passed = True
    for requirement in requirements:
        actual = capabilities.get(requirement.name, {}).get("status", "unknown")
        accepted = actual == "pass" or (
            requirement.required_status == "partial" and actual == "partial"
        )
        passed = passed and accepted
        rows.append(
            {
                "capability": requirement.name,
                "required": requirement.required_status,
                "actual": str(actual),
                "decision": "accepted" if accepted else "unavailable",
            }
        )
    return {
        "matrix_id": matrix.get("matrix_id"),
        "compatible": passed,
        "requirements": rows,
        "decision": "compatible" if passed else "capability-gap",
    }


def load_observation(path: str | Path) -> dict[str, Any]:
    target = Path(path).resolve()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConformanceError(f"cannot read conformance observation: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConformanceError("conformance observation must be an object")
    return validate_observation(raw, root=target.parent)


def validate_observation(
    raw: dict[str, Any], *, root: Path | None = None
) -> dict[str, Any]:
    if raw.get("schema") != OBSERVATION_SCHEMA:
        raise ConformanceError(f"observation schema must be {OBSERVATION_SCHEMA}")
    harness = raw.get("harness")
    build = raw.get("harness_build")
    if harness not in adapters.REFERENCE_ADAPTERS or not isinstance(build, str) or not build:
        raise ConformanceError("observation needs a reference harness and named build")
    raw_cases = raw.get("cases")
    if not isinstance(raw_cases, dict) or set(raw_cases) != set(CASES):
        raise ConformanceError("observation must report every conformance case")
    base = root or Path.cwd()
    cases: dict[str, dict[str, Any]] = {}
    for name in CASES:
        case = raw_cases[name]
        if not isinstance(case, dict) or case.get("status") not in STATUSES:
            raise ConformanceError(f"invalid conformance status for {name}")
        artifacts = case.get("evidence", [])
        if not isinstance(artifacts, list):
            raise ConformanceError(f"conformance evidence for {name} must be a list")
        checked = [_validate_artifact(item, base, name) for item in artifacts]
        if case["status"] == "pass" and not checked:
            raise ConformanceError(f"passing conformance case {name} needs evidence")
        cases[name] = {"status": case["status"], "evidence": checked}
    agents = raw.get("agents", [])
    if not isinstance(agents, list):
        raise ConformanceError("observation agents must be a list")
    checked_agents = [_validate_agent(item, base) for item in agents]
    for agent in checked_agents:
        if agent["harness"] != harness:
            raise ConformanceError(
                f"agent {agent['agent_id']!r} activation harness does not match "
                f"{harness!r}"
            )
        if agent["harness_build"] != build:
            raise ConformanceError(
                f"agent {agent['agent_id']!r} activation build does not match "
                f"{build!r}"
            )
    if cases["subagent-independence"]["status"] == "pass":
        _validate_agent_tree(checked_agents)
    return {
        "schema": OBSERVATION_SCHEMA,
        "harness": harness,
        "harness_build": build,
        "cases": cases,
        "agents": checked_agents,
        "notes": str(raw.get("notes", "")),
    }


def certify(
    observation: dict[str, Any], *, dry_run: bool = False
) -> tuple[dict[str, Any], Path | None]:
    checked = validate_observation(observation)
    matrix = capability_matrix(
        checked["harness"],
        harness_build=checked["harness_build"],
        observation=checked,
    )
    failures = [
        name
        for name, case in checked["cases"].items()
        if case["status"] != "pass"
    ]
    body = {
        "schema": CERTIFICATION_SCHEMA,
        "harness": checked["harness"],
        "harness_build": checked["harness_build"],
        "adapter_id": adapters.REFERENCE_ADAPTERS[checked["harness"]].id,
        "observation_digest": content_id(_portable_observation(checked)),
        "matrix": matrix,
        "agents": [_portable_agent(agent) for agent in checked["agents"]],
        "status": "certified" if not failures else "partial",
        "capability_gaps": failures,
    }
    receipt = {"certification_id": content_id(body), **body}
    if dry_run:
        return receipt, None
    target = paths.adapter_certifications_dir() / f"{receipt['certification_id'][7:]}.json"
    _write_immutable(target, receipt)
    return receipt, target


def load_certification(path: str | Path) -> dict[str, Any]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConformanceError(f"cannot read adapter certification: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema") != CERTIFICATION_SCHEMA:
        raise ConformanceError("unsupported adapter certification schema")
    identity = content_id(
        {key: value for key, value in raw.items() if key != "certification_id"}
    )
    if raw.get("certification_id") != identity:
        raise ConformanceError("adapter certification identity mismatch")
    return raw


def _validate_artifact(item: Any, root: Path, case: str) -> dict[str, str]:
    if not isinstance(item, dict):
        raise ConformanceError(f"{case} evidence must contain artifact objects")
    raw_path = item.get("path")
    reference = item.get("reference", raw_path)
    expected = item.get("sha256")
    if (
        not isinstance(raw_path, str)
        or not raw_path
        or not isinstance(reference, str)
        or not reference
        or not isinstance(expected, str)
    ):
        raise ConformanceError(f"{case} artifact needs path and sha256")
    target = Path(raw_path)
    target = target.resolve() if target.is_absolute() else (root / target).resolve()
    if target.is_symlink() or not target.is_file():
        raise ConformanceError(f"{case} evidence artifact is missing: {target}")
    observed = _sha256_file(target)
    normalized = expected.removeprefix("sha256:")
    if normalized != observed:
        raise ConformanceError(f"{case} evidence artifact digest mismatch: {target}")
    return {
        "path": str(target),
        "reference": reference,
        "sha256": f"sha256:{observed}",
    }


def _validate_agent(item: Any, root: Path) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ConformanceError("agent evidence must be an object")
    identity = item.get("agent_id")
    raw_path = item.get("activation_receipt")
    reference = item.get("activation_receipt_reference", raw_path)
    if (
        not isinstance(identity, str)
        or not identity
        or not isinstance(raw_path, str)
        or not isinstance(reference, str)
    ):
        raise ConformanceError("agent evidence needs agent_id and activation_receipt")
    target = Path(raw_path)
    target = target.resolve() if target.is_absolute() else (root / target).resolve()
    receipt = _load_activation(target)
    plan = receipt["projection_plan"]
    evidence = receipt["activation_evidence"]
    if plan.get("agent_id") != identity:
        raise ConformanceError("activation receipt agent identity mismatch")
    if evidence.get("projection_loaded", {}).get("value") is not True:
        raise ConformanceError(
            f"agent {identity!r} does not prove that its projection loaded"
        )
    required_facts = {
        "projection_loaded": evidence.get("projection_loaded"),
        "served_model": evidence.get("model", {}).get("served_raw"),
        "harness_build": evidence.get("harness", {}).get("build"),
        "effective_tools": evidence.get("effective", {}).get("tools"),
        "effective_policy": evidence.get("effective", {}).get("policy"),
    }
    missing = [
        name
        for name, fact in required_facts.items()
        if not isinstance(fact, dict)
        or fact.get("authority") not in {"observed", "derived"}
        or fact.get("value") is None
    ]
    if missing:
        raise ConformanceError(
            f"agent {identity!r} lacks observed " + ", ".join(missing)
        )
    return {
        "agent_id": identity,
        "parent_agent_id": plan.get("parent_agent_id"),
        "activation_receipt_id": receipt["receipt_id"],
        "activation_receipt": str(target),
        "activation_receipt_reference": reference,
        "harness": plan.get("harness"),
        "adapter_id": plan.get("adapter_id"),
        "harness_build": required_facts["harness_build"]["value"],
        "served_model": required_facts["served_model"]["value"],
        "effective_tools": required_facts["effective_tools"]["value"],
        "effective_policy": required_facts["effective_policy"]["value"],
    }


def _portable_artifact(item: dict[str, str]) -> dict[str, str]:
    """Remove machine-local resolution paths from addressed certification data."""

    return {"path": item["reference"], "sha256": item["sha256"]}


def _portable_agent(agent: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in agent.items()
        if key not in {"activation_receipt", "activation_receipt_reference"}
    } | {"activation_receipt": agent["activation_receipt_reference"]}


def _portable_observation(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        **observation,
        "cases": {
            name: {
                **case,
                "evidence": [_portable_artifact(item) for item in case["evidence"]],
            }
            for name, case in observation["cases"].items()
        },
        "agents": [_portable_agent(agent) for agent in observation["agents"]],
    }


def _validate_agent_tree(agents: list[dict[str, Any]]) -> None:
    identities = [agent["agent_id"] for agent in agents]
    if len(identities) < 2 or len(set(identities)) != len(identities):
        raise ConformanceError("subagent certification needs distinct parent and child agents")
    parents = [agent for agent in agents if agent["parent_agent_id"] is None]
    children = [agent for agent in agents if agent["parent_agent_id"] is not None]
    if len(parents) != 1 or not children:
        raise ConformanceError("subagent certification needs one parent and at least one child")
    if any(child["parent_agent_id"] != parents[0]["agent_id"] for child in children):
        raise ConformanceError("child activation does not name the certified parent")
    receipt_ids = [agent["activation_receipt_id"] for agent in agents]
    if len(set(receipt_ids)) != len(receipt_ids):
        raise ConformanceError("parent and child need independent activation receipts")


def _load_activation(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConformanceError(f"cannot read activation receipt: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema") != adapters.ACTIVATION_RECEIPT_SCHEMA:
        raise ConformanceError("unsupported activation receipt")
    stable = {
        key: value for key, value in raw.items() if key not in {"receipt_id", "created_at"}
    }
    identity = hashlib.sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if raw.get("receipt_id") != identity:
        raise ConformanceError("activation receipt identity mismatch")
    return raw


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_immutable(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.is_symlink() or path.read_text(encoding="utf-8") != encoded:
            raise ConformanceError(f"adapter certification collision at {path}")
        return
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_text(encoding="utf-8") != encoded:
                raise ConformanceError(f"adapter certification collision at {path}")
    finally:
        temporary.unlink(missing_ok=True)
