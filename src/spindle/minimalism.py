"""Named-arm evaluation and deletion-first distillation contracts."""

from __future__ import annotations

import json
import math
import os
import random
import shutil
import statistics
import subprocess
import tempfile
import time
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .lifecycle import content_id, digest_path

MANIFEST_SCHEMA = "spindle.minimalism-eval/v1"
RECEIPT_SCHEMA = "spindle.minimalism-evaluation-receipt/v1"
CLASSIFICATION_SCHEMA = "spindle.material-classification/v1"
DISTILLATION_PLAN_SCHEMA = "spindle.distillation-plan/v1"
TRIAL_REVISION_SCHEMA = "spindle.distillation-trial-revision/v1"

ARM_KINDS = frozenset(
    {"no-skill", "invariant-core", "candidate-overlay", "incumbent", "ablation"}
)
SPLITS = frozenset({"development", "held_out"})
GATES = (
    "availability",
    "activation",
    "routing",
    "authorization",
    "behavior",
    "adapter",
)
GATE_STATUSES = frozenset({"pass", "fail", "not-applicable", "unknown"})
COORDINATE_FIELDS = (
    "model",
    "harness",
    "harness_build",
    "toolset_digest",
    "policy_digest",
    "active_blend_digest",
)
MATERIAL_CLASSES = frozenset(
    {
        "behavioral-steering",
        "reference-knowledge",
        "deterministic-procedure",
        "tool-integration",
        "fixture",
        "obsolete-workaround",
    }
)


class MinimalismError(ValueError):
    """Raised when a minimalism experiment or proposal is invalid."""


@dataclass(frozen=True)
class Arm:
    id: str
    kind: str
    artifact: Path | None
    artifact_digest: str
    artifact_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "artifact": str(self.artifact) if self.artifact else None,
            "artifact_digest": self.artifact_digest,
            "artifact_bytes": self.artifact_bytes,
        }


@dataclass(frozen=True)
class Case:
    id: str
    split: str
    fixture: Path
    fixture_digest: str
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "split": self.split,
            "fixture": str(self.fixture),
            "fixture_digest": self.fixture_digest,
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class Manifest:
    path: Path
    id: str
    skill: str
    runner: tuple[str, ...]
    arms: tuple[Arm, ...]
    cases: tuple[Case, ...]
    candidate_arm: str
    reference_arm: str
    repeats: int
    timeout_seconds: int
    seed: int
    non_inferiority_margin: float
    hard_floor: float
    min_artifact_reduction_bytes: int
    required_gates: tuple[str, ...]
    coordinate: tuple[tuple[str, str], ...]
    receipt_dir: Path

    @property
    def task_distribution_digest(self) -> str:
        return content_id(
            {
                "cases": [case.to_dict() for case in self.cases],
                "repeats": self.repeats,
            }
        )

    @property
    def coordinate_digest(self) -> str:
        return content_id({"coordinate": dict(self.coordinate)})

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MANIFEST_SCHEMA,
            "path": str(self.path),
            "id": self.id,
            "skill": self.skill,
            "runner": list(self.runner),
            "arms": [arm.to_dict() for arm in self.arms],
            "cases": [case.to_dict() for case in self.cases],
            "candidate_arm": self.candidate_arm,
            "reference_arm": self.reference_arm,
            "repeats": self.repeats,
            "timeout_seconds": self.timeout_seconds,
            "seed": self.seed,
            "non_inferiority_margin": self.non_inferiority_margin,
            "hard_floor": self.hard_floor,
            "min_artifact_reduction_bytes": self.min_artifact_reduction_bytes,
            "required_gates": list(self.required_gates),
            "coordinate": dict(self.coordinate),
            "coordinate_digest": self.coordinate_digest,
            "task_distribution_digest": self.task_distribution_digest,
            "receipt_dir": str(self.receipt_dir),
        }


def load_manifest(path: str | Path) -> Manifest:
    manifest_path = Path(path).resolve()
    try:
        raw = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise MinimalismError(f"cannot read minimalism manifest: {exc}") from exc
    if raw.get("schema") != MANIFEST_SCHEMA:
        raise MinimalismError(f"schema must be {MANIFEST_SCHEMA}")
    root = manifest_path.parent
    runner = raw.get("runner")
    if not isinstance(runner, list) or not runner or not all(
        isinstance(item, str) and item for item in runner
    ):
        raise MinimalismError("runner must be a non-empty argv array")
    arms = _load_arms(root, raw.get("arms"))
    cases = _load_cases(root, raw.get("cases"))
    candidate = _text(raw, "candidate_arm")
    reference = _text(raw, "reference_arm")
    arm_ids = {arm.id for arm in arms}
    if candidate not in arm_ids or reference not in arm_ids or candidate == reference:
        raise MinimalismError("candidate_arm and reference_arm must name distinct arms")
    repeats = _integer(raw, "repeats", 2)
    timeout = _integer(raw, "timeout_seconds", 900)
    reduction = _integer(raw, "min_artifact_reduction_bytes", 1)
    if repeats < 2:
        raise MinimalismError("repeats must be at least 2")
    if timeout <= 0 or reduction < 0:
        raise MinimalismError("timeout must be positive and reduction non-negative")
    margin = _number(raw, "non_inferiority_margin", 0.0)
    floor = _number(raw, "hard_floor", 0.0)
    if not 0 <= margin <= 1 or not 0 <= floor <= 1:
        raise MinimalismError("non-inferiority margin and hard floor must be in [0, 1]")
    required = raw.get("required_gates", list(GATES))
    if not isinstance(required, list) or not required or not all(
        isinstance(item, str) and item in GATES for item in required
    ):
        raise MinimalismError("required_gates must contain known gate names")
    coordinate = raw.get("coordinate")
    if not isinstance(coordinate, dict):
        raise MinimalismError("[coordinate] is required")
    missing = [
        name
        for name in COORDINATE_FIELDS
        if not isinstance(coordinate.get(name), str) or not coordinate[name]
    ]
    if missing:
        raise MinimalismError("[coordinate] missing " + ", ".join(missing))
    receipt_dir = raw.get("receipt_dir", "receipts")
    if not isinstance(receipt_dir, str) or not receipt_dir:
        raise MinimalismError("receipt_dir must be a path string")
    return Manifest(
        path=manifest_path,
        id=_text(raw, "id"),
        skill=_text(raw, "skill"),
        runner=tuple(runner),
        arms=arms,
        cases=cases,
        candidate_arm=candidate,
        reference_arm=reference,
        repeats=repeats,
        timeout_seconds=timeout,
        seed=_integer(raw, "seed", 0),
        non_inferiority_margin=margin,
        hard_floor=floor,
        min_artifact_reduction_bytes=reduction,
        required_gates=tuple(dict.fromkeys(required)),
        coordinate=tuple(sorted((str(key), str(value)) for key, value in coordinate.items())),
        receipt_dir=_resolve(root, receipt_dir),
    )


def _load_arms(root: Path, raw: Any) -> tuple[Arm, ...]:
    if not isinstance(raw, list) or len(raw) < 2:
        raise MinimalismError("at least two [[arms]] entries are required")
    result: list[Arm] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise MinimalismError(f"arms[{index}] must be a table")
        identity = _text(item, "id")
        kind = _text(item, "kind")
        if identity in seen:
            raise MinimalismError(f"duplicate arm id: {identity}")
        if kind not in ARM_KINDS:
            raise MinimalismError(f"arm {identity}: unsupported kind {kind!r}")
        seen.add(identity)
        artifact_value = item.get("artifact")
        artifact = None
        if artifact_value is not None:
            if not isinstance(artifact_value, str) or not artifact_value:
                raise MinimalismError(f"arm {identity}: artifact must be a path")
            artifact = _resolve(root, artifact_value)
            if not artifact.exists() or artifact.is_symlink():
                raise MinimalismError(f"arm {identity}: artifact is missing or a symlink")
        if kind == "no-skill" and artifact is not None:
            raise MinimalismError("no-skill arms cannot name an artifact")
        digest = digest_path(artifact) if artifact else content_id({"empty": True})
        result.append(Arm(identity, kind, artifact, digest, _path_bytes(artifact)))
    return tuple(result)


def _load_cases(root: Path, raw: Any) -> tuple[Case, ...]:
    if not isinstance(raw, list) or not raw:
        raise MinimalismError("at least one [[cases]] entry is required")
    result: list[Case] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise MinimalismError(f"cases[{index}] must be a table")
        identity = _text(item, "id")
        split = _text(item, "split")
        if identity in seen:
            raise MinimalismError(f"duplicate case id: {identity}")
        if split not in SPLITS:
            raise MinimalismError(f"case {identity}: unsupported split")
        seen.add(identity)
        fixture = _resolve(root, _text(item, "fixture"))
        if not fixture.is_file() or fixture.is_symlink():
            raise MinimalismError(f"case {identity}: fixture must be a regular file")
        tags = item.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise MinimalismError(f"case {identity}: tags must be strings")
        result.append(Case(identity, split, fixture, digest_path(fixture), tuple(tags)))
    return tuple(result)


def run_evaluation(
    manifest: Manifest,
    *,
    split: str = "all",
    receipt_path: str | Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    if split not in {*SPLITS, "all"}:
        raise MinimalismError("split must be development, held_out, or all")
    cases = [case for case in manifest.cases if split == "all" or case.split == split]
    if not cases:
        raise MinimalismError(f"manifest has no {split} cases")
    rng = random.Random(manifest.seed)
    schedule = [
        (case, repeat, arm)
        for case in cases
        for repeat in range(1, manifest.repeats + 1)
        for arm in manifest.arms
    ]
    rng.shuffle(schedule)
    run_id = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S%fZ")
    runs = [
        _run_one(manifest, case, repeat, arm, run_id)
        for case, repeat, arm in schedule
    ]
    summaries = {
        name: _summaries(manifest, runs, name) for name in sorted(SPLITS)
    }
    decision = _distillation_gate(manifest, runs)
    body = {
        "schema": RECEIPT_SCHEMA,
        "evaluation_id": manifest.id,
        "run_id": run_id,
        "observed_at": datetime.now(tz=UTC).isoformat(),
        "manifest_digest": digest_path(manifest.path),
        "skill": manifest.skill,
        "candidate_arm": manifest.candidate_arm,
        "reference_arm": manifest.reference_arm,
        "arms": [arm.to_dict() for arm in manifest.arms],
        "coordinate": dict(manifest.coordinate),
        "coordinate_digest": manifest.coordinate_digest,
        "task_distribution_digest": manifest.task_distribution_digest,
        "repeats": manifest.repeats,
        "split_requested": split,
        "runs": runs,
        "summaries": summaries,
        "distillation_gate": decision,
    }
    receipt_id = content_id(body)
    receipt = {"receipt_id": receipt_id, **body}
    output = (
        Path(receipt_path).resolve()
        if receipt_path
        else manifest.receipt_dir / f"{manifest.id}-{receipt_id[7:19]}.json"
    )
    _write_exact(output, receipt)
    return output, receipt


def _run_one(
    manifest: Manifest, case: Case, repeat: int, arm: Arm, run_id: str
) -> dict[str, Any]:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="spindle-minimalism-") as temp_dir:
        result_path = Path(temp_dir) / "result.json"
        env = {
            **os.environ,
            "SPINDLE_MINIMALISM_SCHEMA": MANIFEST_SCHEMA,
            "SPINDLE_EVAL_ID": manifest.id,
            "SPINDLE_EVAL_RUN_ID": run_id,
            "SPINDLE_EVAL_CASE_ID": case.id,
            "SPINDLE_EVAL_SPLIT": case.split,
            "SPINDLE_EVAL_REPEAT": str(repeat),
            "SPINDLE_EVAL_ARM": arm.id,
            "SPINDLE_EVAL_ARM_KIND": arm.kind,
            "SPINDLE_EVAL_ARTIFACT": str(arm.artifact) if arm.artifact else "",
            "SPINDLE_EVAL_FIXTURE": str(case.fixture),
            "SPINDLE_EVAL_RESULT_PATH": str(result_path),
            "SPINDLE_EVAL_COORDINATE": json.dumps(dict(manifest.coordinate), sort_keys=True),
        }
        try:
            process = subprocess.run(
                manifest.runner,
                cwd=manifest.path.parent,
                env=env,
                capture_output=True,
                text=True,
                timeout=manifest.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return _error_run(case, repeat, arm, started, "timeout", exc.stdout, exc.stderr)
        base = {
            "case_id": case.id,
            "split": case.split,
            "fixture_digest": case.fixture_digest,
            "tags": list(case.tags),
            "repeat": repeat,
            "arm": arm.id,
            "arm_kind": arm.kind,
            "artifact_digest": arm.artifact_digest,
            "exit_code": process.returncode,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "stdout_digest": content_id({"stdout": process.stdout or ""}),
            "stderr_digest": content_id({"stderr": process.stderr or ""}),
        }
        if process.returncode != 0:
            return {**base, "status": "error", "error": "runner-exit"}
        try:
            result = _load_result(result_path, case.id, arm.id)
        except MinimalismError as exc:
            return {**base, "status": "error", "error": str(exc)}
        return {**base, "status": "ok", "result": result}


def _load_result(path: Path, case_id: str, arm_id: str) -> dict[str, Any]:
    try:
        if path.stat().st_size > 1024 * 1024:
            raise MinimalismError(f"{case_id}/{arm_id}: result exceeds 1 MiB")
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MinimalismError(f"{case_id}/{arm_id}: invalid result: {exc}") from exc
    if not isinstance(raw, dict):
        raise MinimalismError(f"{case_id}/{arm_id}: result must be an object")
    score = raw.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
        raise MinimalismError(f"{case_id}/{arm_id}: score must be in [0, 1]")
    gates = raw.get("gates")
    if not isinstance(gates, dict) or set(gates) != set(GATES):
        raise MinimalismError(f"{case_id}/{arm_id}: all distinct gates are required")
    normalized: dict[str, dict[str, str | None]] = {}
    for name in GATES:
        gate = gates[name]
        if not isinstance(gate, dict) or gate.get("status") not in GATE_STATUSES:
            raise MinimalismError(f"{case_id}/{arm_id}: invalid {name} gate")
        evidence = gate.get("evidence")
        if gate["status"] in {"pass", "fail"} and (
            not isinstance(evidence, str) or not evidence
        ):
            raise MinimalismError(f"{case_id}/{arm_id}: {name} gate needs evidence")
        if evidence is not None and not isinstance(evidence, str):
            raise MinimalismError(f"{case_id}/{arm_id}: gate evidence must be text or null")
        normalized[name] = {"status": gate["status"], "evidence": evidence}
    evidence = raw.get("evidence")
    metrics = raw.get("metrics", {})
    if not isinstance(evidence, dict) or not evidence or not isinstance(metrics, dict):
        raise MinimalismError(f"{case_id}/{arm_id}: evidence and metrics are required objects")
    return {"score": float(score), "gates": normalized, "evidence": evidence, "metrics": metrics}


def _error_run(
    case: Case,
    repeat: int,
    arm: Arm,
    started: float,
    error: str,
    stdout: str | bytes | None,
    stderr: str | bytes | None,
) -> dict[str, Any]:
    return {
        "case_id": case.id,
        "split": case.split,
        "fixture_digest": case.fixture_digest,
        "tags": list(case.tags),
        "repeat": repeat,
        "arm": arm.id,
        "arm_kind": arm.kind,
        "artifact_digest": arm.artifact_digest,
        "status": "error",
        "error": error,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "stdout_digest": content_id({"stdout": _output_text(stdout)}),
        "stderr_digest": content_id({"stderr": _output_text(stderr)}),
    }


def _summaries(
    manifest: Manifest, runs: Iterable[dict[str, Any]], split: str
) -> dict[str, Any]:
    selected = [run for run in runs if run["split"] == split]
    arms: dict[str, Any] = {}
    for arm in manifest.arms:
        arm_runs = [run for run in selected if run["arm"] == arm.id]
        scores = [run["result"]["score"] for run in arm_runs if run["status"] == "ok"]
        gate_counts = {
            gate: {
                status: sum(
                    run["result"]["gates"][gate]["status"] == status
                    for run in arm_runs
                    if run["status"] == "ok"
                )
                for status in sorted(GATE_STATUSES)
            }
            for gate in GATES
        }
        arms[arm.id] = {
            "kind": arm.kind,
            "runs": len(arm_runs),
            "errors": sum(run["status"] != "ok" for run in arm_runs),
            "mean_score": statistics.mean(scores) if scores else None,
            "min_score": min(scores) if scores else None,
            "gate_counts": gate_counts,
        }
    return {
        "split": split,
        "cases": len({run["case_id"] for run in selected}),
        "runs": len(selected),
        "arms": arms,
    }


def _distillation_gate(manifest: Manifest, runs: list[dict[str, Any]]) -> dict[str, Any]:
    relevant = [
        run
        for run in runs
        if run["split"] == "held_out"
        and run["arm"] in {manifest.candidate_arm, manifest.reference_arm}
    ]
    errors = [run for run in relevant if run["status"] != "ok"]
    by_key = {
        (run["case_id"], run["repeat"], run["arm"]): run
        for run in relevant
        if run["status"] == "ok"
    }
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    keys = {(case.id, repeat) for case in manifest.cases if case.split == "held_out" for repeat in range(1, manifest.repeats + 1)}
    for case_id, repeat in sorted(keys):
        candidate = by_key.get((case_id, repeat, manifest.candidate_arm))
        reference = by_key.get((case_id, repeat, manifest.reference_arm))
        if candidate and reference:
            pairs.append((candidate, reference))
    deltas = [
        candidate["result"]["score"] - reference["result"]["score"]
        for candidate, reference in pairs
    ]
    mean_delta = statistics.mean(deltas) if deltas else None
    standard_error = (
        statistics.stdev(deltas) / math.sqrt(len(deltas)) if len(deltas) > 1 else None
    )
    lower_bound = (
        mean_delta - 1.645 * standard_error
        if mean_delta is not None and standard_error is not None
        else mean_delta
    )
    candidate_runs = [candidate for candidate, _reference in pairs]
    minimum = min(
        (run["result"]["score"] for run in candidate_runs), default=None
    )
    arm_map = {arm.id: arm for arm in manifest.arms}
    reduction = (
        arm_map[manifest.reference_arm].artifact_bytes
        - arm_map[manifest.candidate_arm].artifact_bytes
    )
    separated: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    complete = len(pairs) == len(keys) and bool(keys) and not errors
    separated["availability"] = _required_gate(candidate_runs, "availability", complete)
    separated["activation"] = _required_gate(candidate_runs, "activation", complete)
    separated["routing"] = _required_gate(candidate_runs, "routing", complete)
    separated["authorization"] = _required_gate(candidate_runs, "authorization", complete)
    separated["behavior"] = _required_gate(candidate_runs, "behavior", complete)
    separated["adapter"] = _required_gate(candidate_runs, "adapter", complete)
    for name in manifest.required_gates:
        if not separated[name]["passed"]:
            reasons.append(f"{name}-gate")
    non_inferior = lower_bound is not None and lower_bound >= -manifest.non_inferiority_margin
    floor_passed = minimum is not None and minimum >= manifest.hard_floor
    efficient = reduction >= manifest.min_artifact_reduction_bytes
    if not complete:
        reasons.append("incomplete-held-out-pairs")
    if not non_inferior:
        reasons.append("non-inferiority-failed")
    if not floor_passed:
        reasons.append("hard-floor-failed")
    if not efficient:
        reasons.append("efficiency-gain-failed")
    return {
        "eligible": not reasons,
        "reasons": sorted(set(reasons)),
        "candidate_arm": manifest.candidate_arm,
        "reference_arm": manifest.reference_arm,
        "paired_observations": len(pairs),
        "expected_observations": len(keys),
        "mean_delta": mean_delta,
        "standard_error": standard_error,
        "one_sided_95_lower_bound": lower_bound,
        "non_inferiority_margin": manifest.non_inferiority_margin,
        "non_inferior": non_inferior,
        "candidate_min_score": minimum,
        "hard_floor": manifest.hard_floor,
        "hard_floor_passed": floor_passed,
        "artifact_reduction_bytes": reduction,
        "required_artifact_reduction_bytes": manifest.min_artifact_reduction_bytes,
        "efficiency_passed": efficient,
        "gates": separated,
        "evaluation_inheritance": "none",
    }


def _required_gate(
    runs: list[dict[str, Any]], gate: str, complete: bool
) -> dict[str, Any]:
    statuses = [run["result"]["gates"][gate]["status"] for run in runs]
    return {
        "passed": complete and bool(statuses) and all(status == "pass" for status in statuses),
        "statuses": {status: statuses.count(status) for status in sorted(GATE_STATUSES)},
    }


def load_receipt(path: str | Path) -> dict[str, Any]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MinimalismError(f"cannot read minimalism receipt: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema") != RECEIPT_SCHEMA:
        raise MinimalismError("unsupported minimalism receipt schema")
    identity = content_id({key: value for key, value in raw.items() if key != "receipt_id"})
    if raw.get("receipt_id") != identity:
        raise MinimalismError("minimalism receipt content identity mismatch")
    return raw


def receipt_freshness(
    receipt: dict[str, Any], current_coordinate: Iterable[tuple[str, str]]
) -> dict[str, Any]:
    expected = receipt.get("coordinate")
    if not isinstance(expected, dict):
        raise MinimalismError("receipt has no evaluation coordinate")
    current = dict(current_coordinate)
    changed = sorted(
        key for key, value in current.items() if expected.get(key) not in {None, value}
    )
    missing = sorted(key for key in COORDINATE_FIELDS if key not in current)
    return {
        "receipt_id": receipt["receipt_id"],
        "fresh": not changed and not missing,
        "changed": changed,
        "missing_current_coordinates": missing,
        "expected": expected,
        "current": current,
        "decision": "current" if not changed and not missing else "rebaseline-required",
    }


def classify_material(package: str | Path) -> dict[str, Any]:
    root = Path(package).resolve()
    if root.is_symlink() or not root.is_dir():
        raise MinimalismError("classification target must be a non-symlink directory")
    rows: list[dict[str, Any]] = []
    for item in sorted(root.rglob("*")):
        if item.is_symlink() or not item.is_file():
            continue
        relative = item.relative_to(root).as_posix()
        category, basis, destination = _classify_file(item, relative)
        rows.append(
            {
                "path": relative,
                "digest": digest_path(item),
                "bytes": item.stat().st_size,
                "classification": category,
                "basis": basis,
                "recommended_destination": destination,
            }
        )
    body = {
        "schema": CLASSIFICATION_SCHEMA,
        "package_path": str(root),
        "package_digest": digest_path(root),
        "materials": rows,
        "counts": {
            category: sum(row["classification"] == category for row in rows)
            for category in sorted(MATERIAL_CLASSES)
        },
        "execution": "none",
    }
    return {"classification_id": content_id(body), **body}


def distillation_plan(package: str | Path) -> dict[str, Any]:
    classification = classify_material(package)
    root = Path(package).resolve()
    proposals: list[dict[str, Any]] = []
    skill = root / "SKILL.md"
    if skill.is_file() and not skill.is_symlink():
        lines = skill.read_text(encoding="utf-8").splitlines(keepends=True)
        for heading, start, end in _heading_blocks(lines):
            body = {
                "action": "delete-section",
                "path": "SKILL.md",
                "heading": heading,
                "start_line": start + 1,
                "end_line": end,
                "bounded_change": "one-markdown-section",
            }
            proposals.append({"proposal_id": content_id(body), **body})
    for row in classification["materials"]:
        if row["path"] == "SKILL.md":
            continue
        if row["classification"] == "obsolete-workaround":
            action = "delete-resource"
        elif row["classification"] == "deterministic-procedure":
            action = "extract-to-chip-or-tool"
        elif row["classification"] == "reference-knowledge":
            action = "keep-progressive-reference"
        else:
            continue
        body = {
            "action": action,
            "path": row["path"],
            "bounded_change": "one-resource",
        }
        proposals.append({"proposal_id": content_id(body), **body})
    body = {
        "schema": DISTILLATION_PLAN_SCHEMA,
        "package_path": str(root),
        "package_digest": classification["package_digest"],
        "classification_id": classification["classification_id"],
        "proposals": proposals,
        "promotion_policy": "stage-as-trial-never-auto-adopt",
    }
    return {"plan_id": content_id(body), **body}


def stage_trial_revision(
    package: str | Path,
    proposal_id: str,
    destination: str | Path,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    plan = distillation_plan(package)
    matches = [item for item in plan["proposals"] if item["proposal_id"] == proposal_id]
    if len(matches) != 1:
        raise MinimalismError("proposal does not belong to the current package digest")
    proposal = matches[0]
    if proposal["action"] not in {"delete-section", "delete-resource"}:
        raise MinimalismError(
            f"{proposal['action']} needs an external Chip/tool or reference review"
        )
    source = Path(package).resolve()
    target = Path(destination).resolve()
    if target.exists() or target.is_symlink():
        raise MinimalismError("trial destination already exists")
    preview = {
        "action": "would-stage" if dry_run else "staged",
        "plan_id": plan["plan_id"],
        "proposal": proposal,
        "source_digest": plan["package_digest"],
        "destination": str(target),
        "adoption_change": None,
    }
    if dry_run:
        return preview
    shutil.copytree(source, target, symlinks=True)
    if proposal["action"] == "delete-resource":
        resource = target / proposal["path"]
        if resource.is_symlink() or not resource.is_file():
            raise MinimalismError("staged resource shape changed unexpectedly")
        resource.unlink()
    else:
        skill = target / proposal["path"]
        lines = skill.read_text(encoding="utf-8").splitlines(keepends=True)
        start = int(proposal["start_line"]) - 1
        end = int(proposal["end_line"])
        skill.write_text("".join(lines[:start] + lines[end:]), encoding="utf-8")
    body = {
        "schema": TRIAL_REVISION_SCHEMA,
        "plan_id": plan["plan_id"],
        "proposal_id": proposal_id,
        "source_digest": plan["package_digest"],
        "candidate_digest": digest_path(target),
        "destination": str(target),
        "adoption_change": None,
        "next": "inspect and evaluate this local candidate before any adoption",
    }
    receipt = {"trial_revision_id": content_id(body), **body}
    receipt_path = target.parent / f".{target.name}.spindle-trial.json"
    _write_exact(receipt_path, receipt)
    return {**preview, "trial_revision": receipt, "receipt_path": str(receipt_path)}


def _classify_file(path: Path, relative: str) -> tuple[str, str, str]:
    lowered = relative.lower()
    try:
        text = path.read_text(encoding="utf-8")[:65536].lower()
    except (OSError, UnicodeDecodeError):
        text = ""
    if any(part in lowered for part in ("fixture", "fixtures/", "testdata/", "examples/")):
        return "fixture", "fixture/example path", "evaluation-fixture"
    if any(word in text for word in ("deprecated workaround", "legacy workaround", "obsolete")):
        return "obsolete-workaround", "explicit obsolete/workaround marker", "ablation-candidate"
    if lowered == "skill.md":
        return "behavioral-steering", "portable skill instruction entrypoint", "invariant-or-overlay"
    if lowered.startswith(("references/", "docs/")) or path.suffix.lower() in {".pdf", ".csv"}:
        return "reference-knowledge", "reference/documentation resource", "progressive-reference"
    if lowered.startswith(("scripts/", "bin/")) or path.suffix.lower() in {
        ".py",
        ".sh",
        ".js",
        ".ts",
    }:
        return "deterministic-procedure", "executable procedure resource", "chip-or-tool"
    if any(word in text for word in ("mcp", "api key", "oauth", "tool call", "subprocess")):
        return "tool-integration", "tool/service integration indicator", "tool-adapter"
    return "reference-knowledge", "non-entrypoint package material", "progressive-reference"


def _heading_blocks(lines: list[str]) -> tuple[tuple[str, int, int], ...]:
    frontmatter_end = 0
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                frontmatter_end = index + 1
                break
    headings = [
        (line.lstrip("#").strip(), index)
        for index, line in enumerate(lines)
        if index >= frontmatter_end and line.startswith("## ")
    ]
    return tuple(
        (heading, start, headings[index + 1][1] if index + 1 < len(headings) else len(lines))
        for index, (heading, start) in enumerate(headings)
    )


def _write_exact(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_text(encoding="utf-8") != encoded:
            raise MinimalismError(f"receipt path already contains different content: {path}")
        return
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _text(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MinimalismError(f"{key} must be non-empty text")
    return value.strip()


def _number(raw: dict[str, Any], key: str, default: float) -> float:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MinimalismError(f"{key} must be numeric")
    return float(value)


def _integer(raw: dict[str, Any], key: str, default: int) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise MinimalismError(f"{key} must be an integer")
    return value


def _path_bytes(path: Path | None) -> int:
    if path is None:
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file() and not item.is_symlink())


def _output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value
