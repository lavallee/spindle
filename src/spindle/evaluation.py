"""Behavioral skill evaluation manifests, paired runs, and durable receipts."""

from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import tempfile
import time
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
EVALUATION_RECEIPT_SCHEMA = "spindle.evaluation-receipt/v2"
PROMOTION_RECEIPT_SCHEMA = "spindle.procedure-promotion/v1"
PROCEDURE_ORIGIN_SCHEMA = "spindle.procedure-origin/v1"
VALID_SPLITS = {"development", "held_out"}
VALID_ARMS = ("baseline", "variant")
_ORIGIN_FIELDS = (
    "milton_finding_id",
    "milton_revision_id",
    "chip_candidate_id",
    "chip_receipt_id",
)
_TUPLE_DIMENSIONS = ("profile", "model", "harness", "baseline_implementation")


class EvaluationError(ValueError):
    """Raised when an evaluation contract or runner result is invalid."""


@dataclass(frozen=True)
class EvalCase:
    id: str
    split: str
    fixture: Path
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvalManifest:
    path: Path
    id: str
    skill: str
    skill_path: Path
    runner: tuple[str, ...]
    cases: tuple[EvalCase, ...]
    timeout_seconds: int = 900
    seed: int = 0
    min_held_out_cases: int = 1
    min_improvement: float = 0.0
    receipt_dir: Path | None = None
    dimensions: dict[str, str] = field(default_factory=dict)
    origin: dict[str, str] = field(default_factory=dict)


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (root / path).resolve()


def _require_text(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EvaluationError(f"{key} must be a non-empty string")
    return value.strip()


def _number(raw: dict[str, Any], key: str, default: float) -> float:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationError(f"{key} must be a number")
    return float(value)


def load_manifest(path: str | Path) -> EvalManifest:
    manifest_path = Path(path).resolve()
    try:
        raw = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvaluationError(f"cannot read manifest: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise EvaluationError(f"invalid TOML: {exc}") from exc

    if raw.get("schema_version") != SCHEMA_VERSION:
        raise EvaluationError(f"schema_version must be {SCHEMA_VERSION}")

    root = manifest_path.parent
    runner = raw.get("runner")
    if not isinstance(runner, list) or not runner or not all(
        isinstance(part, str) and part for part in runner
    ):
        raise EvaluationError("runner must be a non-empty array of argv strings")

    skill_path = _resolve(root, _require_text(raw, "skill_path"))
    if not skill_path.is_file():
        raise EvaluationError(f"skill_path does not exist: {skill_path}")

    raw_cases = raw.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise EvaluationError("at least one [[cases]] entry is required")
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_cases, start=1):
        if not isinstance(item, dict):
            raise EvaluationError(f"cases[{index}] must be a table")
        case_id = _require_text(item, "id")
        if case_id in seen:
            raise EvaluationError(f"duplicate case id: {case_id}")
        seen.add(case_id)
        split = _require_text(item, "split")
        if split not in VALID_SPLITS:
            raise EvaluationError(f"case {case_id}: split must be development or held_out")
        fixture = _resolve(root, _require_text(item, "fixture"))
        if not fixture.is_file():
            raise EvaluationError(f"case {case_id}: fixture must be a file: {fixture}")
        tags = item.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise EvaluationError(f"case {case_id}: tags must be an array of strings")
        cases.append(EvalCase(case_id, split, fixture, tuple(tags)))

    timeout = int(_number(raw, "timeout_seconds", 900))
    min_cases = int(_number(raw, "min_held_out_cases", 1))
    improvement = _number(raw, "min_improvement", 0.0)
    if timeout <= 0:
        raise EvaluationError("timeout_seconds must be positive")
    if min_cases <= 0:
        raise EvaluationError("min_held_out_cases must be positive")
    if improvement < 0:
        raise EvaluationError("min_improvement must be non-negative")

    dimensions = raw.get("dimensions", {})
    if not isinstance(dimensions, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in dimensions.items()
    ):
        raise EvaluationError("[dimensions] values must be strings")

    origin = raw.get("origin", {})
    if not isinstance(origin, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in origin.items()
    ):
        raise EvaluationError("[origin] values must be strings")
    if origin:
        if origin.get("schema") != PROCEDURE_ORIGIN_SCHEMA:
            raise EvaluationError(f"origin.schema must be {PROCEDURE_ORIGIN_SCHEMA}")
        missing_origin = [key for key in _ORIGIN_FIELDS if not origin.get(key)]
        if missing_origin:
            raise EvaluationError(f"[origin] missing {', '.join(missing_origin)}")
        missing_dimensions = [key for key in _TUPLE_DIMENSIONS if not dimensions.get(key)]
        if missing_dimensions:
            raise EvaluationError(
                "procedure evaluation [dimensions] missing " + ", ".join(missing_dimensions)
            )

    receipt_value = raw.get("receipt_dir", "receipts")
    if not isinstance(receipt_value, str) or not receipt_value:
        raise EvaluationError("receipt_dir must be a non-empty string")

    seed = raw.get("seed", 0)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise EvaluationError("seed must be an integer")

    return EvalManifest(
        path=manifest_path,
        id=_require_text(raw, "id"),
        skill=_require_text(raw, "skill"),
        skill_path=skill_path,
        runner=tuple(runner),
        cases=tuple(cases),
        timeout_seconds=timeout,
        seed=seed,
        min_held_out_cases=min_cases,
        min_improvement=improvement,
        receipt_dir=_resolve(root, receipt_value),
        dimensions=dict(dimensions),
        origin=dict(origin),
    )


def validate_manifest(path: str | Path) -> list[str]:
    manifest = load_manifest(path)
    findings: list[str] = []
    held_out = sum(case.split == "held_out" for case in manifest.cases)
    if held_out < manifest.min_held_out_cases:
        findings.append(
            f"held_out cases ({held_out}) are below min_held_out_cases "
            f"({manifest.min_held_out_cases})"
        )
    return findings


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _result_payload(path: Path, *, case_id: str, arm: str) -> dict[str, Any]:
    try:
        if path.stat().st_size > 1024 * 1024:
            raise EvaluationError(f"case {case_id}/{arm}: result exceeds 1 MiB")
    except OSError:
        pass
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvaluationError(f"case {case_id}/{arm}: runner wrote no result: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"case {case_id}/{arm}: invalid result JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise EvaluationError(f"case {case_id}/{arm}: result must be a JSON object")
    score = payload.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
        raise EvaluationError(f"case {case_id}/{arm}: score must be between 0 and 1")
    invoked = payload.get("skill_invoked")
    if not isinstance(invoked, bool):
        raise EvaluationError(f"case {case_id}/{arm}: skill_invoked must be boolean")
    if invoked != (arm == "variant"):
        raise EvaluationError(f"case {case_id}/{arm}: skill_invoked does not match arm")
    evidence = payload.get("evidence")
    if not isinstance(evidence, dict) or not evidence:
        raise EvaluationError(f"case {case_id}/{arm}: evidence must be a non-empty object")
    metrics = payload.get("metrics", {})
    if not isinstance(metrics, dict):
        raise EvaluationError(f"case {case_id}/{arm}: metrics must be an object")
    passed = payload.get("passed", score >= 0.5)
    if not isinstance(passed, bool):
        raise EvaluationError(f"case {case_id}/{arm}: passed must be boolean")
    artifacts = payload.get("artifacts", [])
    if not isinstance(artifacts, list) or not all(isinstance(item, str) for item in artifacts):
        raise EvaluationError(f"case {case_id}/{arm}: artifacts must be an array of strings")
    payload["score"] = float(score)
    payload["passed"] = passed
    payload.setdefault("metrics", {})
    payload.setdefault("artifacts", [])
    return payload


def _output_digest(value: str | bytes | None) -> str:
    if value is None:
        payload = b""
    elif isinstance(value, str):
        payload = value.encode()
    else:
        payload = value
    return hashlib.sha256(payload).hexdigest()


def _run_one(manifest: EvalManifest, case: EvalCase, arm: str, run_id: str) -> dict[str, Any]:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="spindle-eval-") as temp_dir:
        result_path = Path(temp_dir) / "result.json"
        env = {
            **os.environ,
            "SPINDLE_EVAL_SCHEMA_VERSION": str(SCHEMA_VERSION),
            "SPINDLE_EVAL_ID": manifest.id,
            "SPINDLE_EVAL_RUN_ID": run_id,
            "SPINDLE_EVAL_CASE_ID": case.id,
            "SPINDLE_EVAL_SPLIT": case.split,
            "SPINDLE_EVAL_ARM": arm,
            "SPINDLE_EVAL_FIXTURE": str(case.fixture),
            "SPINDLE_EVAL_SKILL_FILE": str(manifest.skill_path) if arm == "variant" else "",
            "SPINDLE_EVAL_SKILL_ENABLED": "1" if arm == "variant" else "0",
            "SPINDLE_EVAL_RESULT_PATH": str(result_path),
            "SPINDLE_EVAL_DIMENSIONS": json.dumps(manifest.dimensions, sort_keys=True),
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
            return {
                "case_id": case.id,
                "split": case.split,
                "arm": arm,
                "status": "error",
                "error": f"timeout after {manifest.timeout_seconds}s",
                "duration_ms": int((time.monotonic() - started) * 1000),
                "stdout_sha256": _output_digest(exc.stdout),
                "stderr_sha256": _output_digest(exc.stderr),
            }

        stdout = process.stdout or ""
        stderr = process.stderr or ""
        record: dict[str, Any] = {
            "case_id": case.id,
            "split": case.split,
            "tags": list(case.tags),
            "fixture": str(case.fixture),
            "fixture_sha256": _sha256(case.fixture),
            "arm": arm,
            "exit_code": process.returncode,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
        }
        if process.returncode != 0:
            record.update(
                status="error",
                error=f"runner exited {process.returncode}",
                stderr_tail=stderr[-1000:],
            )
            return record
        try:
            record["result"] = _result_payload(result_path, case_id=case.id, arm=arm)
            record["status"] = "ok"
        except EvaluationError as exc:
            record.update(status="error", error=str(exc), stderr_tail=stderr[-1000:])
        return record


def _aggregate(runs: Iterable[dict[str, Any]], split: str) -> dict[str, Any]:
    selected = [run for run in runs if run.get("split") == split]
    by_arm: dict[str, list[float]] = {arm: [] for arm in VALID_ARMS}
    errors = 0
    for run in selected:
        if run.get("status") != "ok":
            errors += 1
            continue
        by_arm[run["arm"]].append(float(run["result"]["score"]))
    means = {
        arm: (sum(scores) / len(scores) if scores else None) for arm, scores in by_arm.items()
    }
    delta = None
    if means["baseline"] is not None and means["variant"] is not None:
        delta = means["variant"] - means["baseline"]
    return {
        "split": split,
        "cases": len({run.get("case_id") for run in selected}),
        "runs": len(selected),
        "errors": errors,
        "mean_score": means,
        "delta": delta,
    }


def _promotion(manifest: EvalManifest, runs: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _aggregate(runs, "held_out")
    reasons: list[str] = []
    if summary["cases"] < manifest.min_held_out_cases:
        reasons.append("insufficient-held-out-cases")
    if summary["errors"]:
        reasons.append("runner-errors")
    delta = summary["delta"]
    if delta is None:
        reasons.append("incomplete-pairs")
    elif manifest.min_improvement == 0 and delta <= 0:
        reasons.append("no-held-out-improvement")
    elif manifest.min_improvement > 0 and delta < manifest.min_improvement:
        reasons.append("below-min-improvement")
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "required_cases": manifest.min_held_out_cases,
        "required_improvement": manifest.min_improvement,
        "observed_delta": delta,
    }


def _default_receipt_path(manifest: EvalManifest, run_id: str) -> Path:
    assert manifest.receipt_dir is not None
    return manifest.receipt_dir / f"{manifest.id}-{run_id}.json"


def run_evaluation(
    manifest: EvalManifest,
    *,
    split: str = "all",
    receipt_path: str | Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    if split not in {*VALID_SPLITS, "all"}:
        raise EvaluationError("split must be development, held_out, or all")
    selected = [case for case in manifest.cases if split == "all" or case.split == split]
    if not selected:
        raise EvaluationError(f"manifest has no {split} cases")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    rng = random.Random(manifest.seed)
    rng.shuffle(selected)
    schedule: list[tuple[EvalCase, str]] = []
    for case in selected:
        arms = list(VALID_ARMS)
        rng.shuffle(arms)
        schedule.extend((case, arm) for arm in arms)

    runs = [_run_one(manifest, case, arm, run_id) for case, arm in schedule]
    skill_sha256 = _sha256(manifest.skill_path)
    evaluation_tuple, baseline_tuple = _evaluation_tuples(manifest, skill_sha256)
    receipt = {
        "schema": EVALUATION_RECEIPT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "evaluation_id": manifest.id,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest.path),
        "manifest_sha256": _sha256(manifest.path),
        "skill": manifest.skill,
        "skill_path": str(manifest.skill_path),
        "skill_sha256": skill_sha256,
        "dimensions": manifest.dimensions,
        "origin": manifest.origin or None,
        "evaluation_tuple": evaluation_tuple,
        "baseline_tuple": baseline_tuple,
        "seed": manifest.seed,
        "split_requested": split,
        "runs": runs,
        "summaries": {
            name: _aggregate(runs, name) for name in sorted(VALID_SPLITS)
        },
        "promotion": _promotion(manifest, runs),
    }
    receipt["receipt_id"] = _content_id("spr-eval", receipt)
    output = Path(receipt_path).resolve() if receipt_path else _default_receipt_path(manifest, run_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output, receipt


def load_receipt(path: str | Path) -> dict[str, Any]:
    receipt_path = Path(path)
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvaluationError(f"cannot read receipt: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"invalid receipt JSON: {exc}") from exc
    if not isinstance(receipt, dict) or receipt.get("schema_version") != SCHEMA_VERSION:
        raise EvaluationError(f"receipt schema_version must be {SCHEMA_VERSION}")
    if receipt.get("schema") == EVALUATION_RECEIPT_SCHEMA:
        _validate_procedure_receipt_fields(receipt)
    return receipt


def record_promotion(
    evaluation_receipt: dict[str, Any],
    binding_record: Any,
    path: str | Path,
) -> dict[str, Any]:
    """Write one idempotent promotion receipt after an eligible evaluated bind."""

    _validate_procedure_receipt_fields(evaluation_receipt)
    promotion = evaluation_receipt.get("promotion")
    if not isinstance(promotion, dict) or promotion.get("eligible") is not True:
        raise EvaluationError("only an eligible evaluation can be promoted")
    evaluation_receipt_id = str(evaluation_receipt["receipt_id"])
    for name in ("coordinate", "surface", "bound_at"):
        if not isinstance(getattr(binding_record, name, None), str):
            raise EvaluationError(f"binding record is missing {name}")
    if getattr(binding_record, "evaluation_receipt_id", None) != evaluation_receipt_id:
        raise EvaluationError("binding record does not name this evaluation receipt")
    for field_name in ("origin", "evaluation_tuple", "baseline_tuple"):
        if getattr(binding_record, field_name, None) != evaluation_receipt.get(field_name):
            raise EvaluationError(f"binding record {field_name} does not match evaluation")

    document: dict[str, Any] = {
        "schema": PROMOTION_RECEIPT_SCHEMA,
        "recorded_at": binding_record.bound_at,
        "evaluation_receipt_id": evaluation_receipt_id,
        "evaluation_id": evaluation_receipt["evaluation_id"],
        "origin": evaluation_receipt["origin"],
        "evaluation_tuple": evaluation_receipt["evaluation_tuple"],
        "baseline_tuple": evaluation_receipt["baseline_tuple"],
        "binding": {
            "surface": binding_record.surface,
            "coordinate": binding_record.coordinate,
            "doctrine_coordinate": binding_record.doctrine_coordinate,
            "skills": binding_record.skills,
            "channel_versions": binding_record.channel_versions,
        },
        "decision": {
            "eligible": True,
            "observed_delta": promotion.get("observed_delta"),
            "required_improvement": promotion.get("required_improvement"),
        },
    }
    document["receipt_id"] = _content_id("spr-promote", document)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if output.is_file():
        existing = output.read_text(encoding="utf-8")
        if existing != encoded:
            raise EvaluationError("promotion receipt path already contains other content")
        return document
    output.write_text(encoded, encoding="utf-8")
    return document


def manifest_as_dict(manifest: EvalManifest) -> dict[str, Any]:
    """Return a JSON-friendly manifest representation for CLI inspection."""
    raw = asdict(manifest)
    raw["path"] = str(manifest.path)
    raw["skill_path"] = str(manifest.skill_path)
    raw["receipt_dir"] = str(manifest.receipt_dir)
    raw["runner"] = list(manifest.runner)
    raw["cases"] = [
        {"id": case.id, "split": case.split, "fixture": str(case.fixture), "tags": list(case.tags)}
        for case in manifest.cases
    ]
    return raw


def _evaluation_tuples(
    manifest: EvalManifest, skill_sha256: str
) -> tuple[dict[str, str] | None, dict[str, str] | None]:
    if not manifest.origin:
        return None, None
    common = {
        "profile": manifest.dimensions["profile"],
        "model": manifest.dimensions["model"],
        "harness": manifest.dimensions["harness"],
    }
    return (
        {"implementation": f"sha256:{skill_sha256}", **common},
        {"implementation": manifest.dimensions["baseline_implementation"], **common},
    )


def _validate_procedure_receipt_fields(receipt: dict[str, Any]) -> None:
    origin = receipt.get("origin")
    if origin is None:
        return
    if not isinstance(origin, dict) or origin.get("schema") != PROCEDURE_ORIGIN_SCHEMA:
        raise EvaluationError("evaluation receipt has invalid procedure origin")
    if any(not isinstance(origin.get(key), str) or not origin[key] for key in _ORIGIN_FIELDS):
        raise EvaluationError("evaluation receipt has incomplete procedure origin")
    for name in ("evaluation_tuple", "baseline_tuple"):
        value = receipt.get(name)
        if not isinstance(value, dict) or any(
            not isinstance(value.get(key), str) or not value[key]
            for key in ("implementation", "profile", "model", "harness")
        ):
            raise EvaluationError(f"evaluation receipt has invalid {name}")
    receipt_id = receipt.get("receipt_id")
    if not isinstance(receipt_id, str) or not receipt_id:
        raise EvaluationError("evaluation receipt has no receipt_id")


def _content_id(prefix: str, document: dict[str, Any]) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"{prefix}-{hashlib.sha256(body.encode()).hexdigest()[:24]}"
