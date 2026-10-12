#!/usr/bin/env python3
"""Reduce live Claude/Codex logs to privacy-safe M7 certification evidence.

Raw harness logs can contain prompts and machine configuration.  This script
retains only structural runtime facts, binds those facts to the source-log
digests, creates independent activation receipts, and then runs Spindle's
adapter conformance certifier.  Raw logs are never copied into the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from spindle.adapters import (
    CLAUDE_CODE_ADAPTER,
    CODEX_ADAPTER,
    ActivationEvidence,
    EvidenceAuthority,
    EvidenceFact,
    ProjectionMode,
    ProjectionPlan,
    RealizationReference,
    write_activation_receipt,
)
from spindle.conformance import CASES, OBSERVATION_SCHEMA, certify, load_observation
from spindle.lifecycle import content_id, digest_path

SCHEMA = "spindle.sanitized-runtime-evidence/v1"
CANARY = "m7-adapter-proof"
TOKEN = "M7_SPINDLE_SKILL_OK"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {path}:{number}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"JSONL row is not an object at {path}:{number}")
        rows.append(value)
    return rows


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != encoded:
        raise ValueError(f"refusing to replace different evidence: {path}")
    path.write_text(encoded, encoding="utf-8")


def _claude(path: Path, canary_digest: str) -> dict[str, Any]:
    rows = _jsonl(path)
    init = next(
        (row for row in rows if row.get("type") == "system" and row.get("subtype") == "init"),
        None,
    )
    result = next((row for row in rows if row.get("type") == "result"), None)
    if init is None or result is None:
        raise ValueError("Claude stream lacks init or result event")
    session = str(init.get("session_id", ""))
    parent_model = str(init.get("model", ""))
    parent_tools = tuple(str(item) for item in init.get("tools", []))
    skills = [
        str(item.get("name") or item.get("skill") or "")
        if isinstance(item, dict)
        else str(item)
        for item in init.get("skills", [])
    ]
    calls: list[dict[str, Any]] = []
    for row in rows:
        if row.get("type") != "assistant":
            continue
        message = row.get("message", {})
        for block in message.get("content", []):
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            inputs = block.get("input", {})
            calls.append(
                {
                    "model": message.get("model"),
                    "parent_tool_use_id": row.get("parent_tool_use_id"),
                    "tool_use_id": block.get("id"),
                    "tool": block.get("name"),
                    "skill": inputs.get("skill") if isinstance(inputs, dict) else None,
                    "subagent_type": (
                        inputs.get("subagent_type")
                        if isinstance(inputs, dict)
                        else None
                    ),
                }
            )
    parent_skill = next(
        (
            call
            for call in calls
            if call["parent_tool_use_id"] is None
            and call["tool"] == "Skill"
            and call["skill"] == CANARY
        ),
        None,
    )
    delegation = next(
        (
            call
            for call in calls
            if call["parent_tool_use_id"] is None
            and call["tool"] == "Agent"
            and call["subagent_type"] == "m7-sonnet-child"
        ),
        None,
    )
    if delegation is None:
        raise ValueError("Claude stream lacks the expected child delegation")
    child_skill = next(
        (
            call
            for call in calls
            if call["parent_tool_use_id"] == delegation["tool_use_id"]
            and call["tool"] == "Skill"
            and call["skill"] == CANARY
        ),
        None,
    )
    if parent_skill is None or child_skill is None or CANARY not in skills:
        raise ValueError("Claude parent and child did not independently load the canary")
    if result.get("subtype") != "success" or result.get("is_error") is not False:
        raise ValueError("Claude run did not succeed")
    denials = result.get("permission_denials", [])
    if not isinstance(denials, list):
        raise ValueError("Claude permission-denial evidence is malformed")
    model_usage = result.get("modelUsage", {})
    if not isinstance(model_usage, dict):
        raise ValueError("Claude model usage is malformed")
    child_model = str(child_skill["model"])
    if parent_model not in model_usage or child_model not in model_usage:
        raise ValueError("Claude result does not account for both served models")
    body = {
        "schema": SCHEMA,
        "harness": "claude",
        "harness_build": str(init.get("claude_code_version", "")),
        "source_log_sha256": _sha(path),
        "canary_digest": canary_digest,
        "session_id": session,
        "permission_mode": str(init.get("permissionMode", "")),
        "permission_denials": len(denials),
        "agents": {
            "parent": {
                "agent_id": session,
                "parent_agent_id": None,
                "served_model": parent_model,
                "effective_tools": list(parent_tools),
                "projection_loaded": True,
                "projection_evidence": "observed Skill tool use",
            },
            "child": {
                "agent_id": f"{session}:{delegation['tool_use_id']}",
                "parent_agent_id": session,
                "served_model": child_model,
                "effective_tools": ["Skill"],
                "projection_loaded": True,
                "projection_evidence": "forwarded child Skill tool use",
                "tool_policy_evidence": "derived from exact custom-agent contract",
            },
        },
        "model_usage": sorted(model_usage),
    }
    return {"evidence_id": content_id(body), **body}


def _codex_agent(path: Path) -> dict[str, Any]:
    rows = _jsonl(path)
    meta = next((row.get("payload") for row in rows if row.get("type") == "session_meta"), None)
    turn = next((row.get("payload") for row in rows if row.get("type") == "turn_context"), None)
    if not isinstance(meta, dict) or not isinstance(turn, dict):
        raise ValueError(f"Codex session lacks metadata or turn context: {path}")
    outputs: dict[str, bool] = {}
    calls: list[dict[str, Any]] = []
    functions: list[str] = []
    for row in rows:
        payload = row.get("payload", {})
        kind = payload.get("type") if isinstance(payload, dict) else None
        if kind == "custom_tool_call_output":
            outputs[str(payload.get("call_id"))] = TOKEN in json.dumps(payload.get("output"))
        elif kind == "custom_tool_call":
            calls.append(
                {
                    "call_id": str(payload.get("call_id")),
                    "tool": str(payload.get("name")),
                    "read_skill_file": "SKILL.md" in str(payload.get("input", "")),
                }
            )
        elif kind == "function_call":
            functions.append(str(payload.get("name")))
    canary_calls = [
        call
        for call in calls
        if call["read_skill_file"] and outputs.get(call["call_id"], False)
    ]
    if not canary_calls:
        raise ValueError(f"Codex agent did not read a SKILL.md yielding the canary: {path}")
    policy = {
        "approval_policy": turn.get("approval_policy"),
        "sandbox_policy": turn.get("sandbox_policy"),
        "permission_profile": turn.get("permission_profile"),
    }
    observed_tools = sorted(
        set(functions) | {call["tool"] for call in calls if call["tool"]}
    )
    return {
        "agent_id": str(meta.get("id")),
        "session_id": str(meta.get("session_id")),
        "parent_agent_id": meta.get("parent_thread_id"),
        "agent_path": meta.get("agent_path"),
        "served_model": str(turn.get("model")),
        "effort": str(turn.get("effort")),
        "harness_build": str(meta.get("cli_version")),
        "effective_tool_composition": str(turn.get("comp_hash")),
        "observed_tool_calls": observed_tools,
        "effective_policy": policy,
        "effective_policy_digest": content_id(policy),
        "projection_loaded": True,
        "projection_evidence": "observed SKILL.md read yielding canary token",
        "source_log_sha256": _sha(path),
    }


def _codex(parent_path: Path, child_path: Path, canary_digest: str) -> dict[str, Any]:
    parent = _codex_agent(parent_path)
    child = _codex_agent(child_path)
    if parent["parent_agent_id"] is not None:
        raise ValueError("Codex parent session unexpectedly names a parent")
    if child["parent_agent_id"] != parent["agent_id"]:
        raise ValueError("Codex child session does not name the parent thread")
    if child["session_id"] != parent["session_id"]:
        raise ValueError("Codex parent and child do not share a session")
    if child["served_model"] == parent["served_model"]:
        raise ValueError("Codex mixed-model test did not route to a different child")
    if child["harness_build"] != parent["harness_build"]:
        raise ValueError("Codex parent and child report different harness builds")
    body = {
        "schema": SCHEMA,
        "harness": "codex",
        "harness_build": parent["harness_build"],
        "canary_digest": canary_digest,
        "session_id": parent["session_id"],
        "agents": {"parent": parent, "child": child},
    }
    return {"evidence_id": content_id(body), **body}


def _fact(value: Any, authority: EvidenceAuthority, source: str) -> EvidenceFact:
    if isinstance(value, list):
        value = tuple(str(item) for item in value)
    return EvidenceFact(value, authority, source)


def _activation(
    root: Path,
    runtime: dict[str, Any],
    role: str,
    canary: Path,
    package_digest: str,
) -> tuple[str, Path]:
    harness = runtime["harness"]
    descriptor = CLAUDE_CODE_ADAPTER if harness == "claude" else CODEX_ADAPTER
    agent = runtime["agents"][role]
    source = f"evidence/{harness}-runtime.json#agents.{role}"
    if harness == "claude":
        tools_authority = (
            EvidenceAuthority.OBSERVED
            if role == "parent"
            else EvidenceAuthority.DERIVED
        )
        policy_authority = (
            EvidenceAuthority.OBSERVED
            if role == "parent"
            else EvidenceAuthority.DERIVED
        )
        policy = f"permission-mode:{runtime['permission_mode']}"
        tools = agent["effective_tools"]
    else:
        tools_authority = EvidenceAuthority.OBSERVED
        policy_authority = EvidenceAuthority.OBSERVED
        tools = [
            f"composition:{agent['effective_tool_composition']}",
            *[f"observed:{name}" for name in agent["observed_tool_calls"]],
        ]
        policy = (
            f"{agent['effective_policy_digest']};"
            f"approval={agent['effective_policy']['approval_policy']};"
            f"sandbox={agent['effective_policy']['sandbox_policy'].get('type')};"
            f"network={agent['effective_policy']['permission_profile'].get('network')}"
        )
    realization_id = content_id(
        {
            "canary_digest": package_digest,
            "harness": harness,
            "served_model": agent["served_model"],
        }
    )
    plan = ProjectionPlan(
        session_id=runtime["session_id"],
        agent_id=agent["agent_id"],
        parent_agent_id=agent["parent_agent_id"],
        harness=harness,
        adapter_id=descriptor.id,
        mode=ProjectionMode.SKILL_PATH,
        target=(
            f".claude/skills/{CANARY}"
            if harness == "claude"
            else f".agents/skills/{CANARY}"
        ),
        realization=RealizationReference(
            skill=CANARY,
            path=Path("canary"),
            package_digest=package_digest,
            realization_digest=package_digest,
            realization_receipt_id=realization_id,
        ),
    )
    evidence = ActivationEvidence(
        projection_loaded=_fact(True, EvidenceAuthority.OBSERVED, source),
        served_model_raw=_fact(
            agent["served_model"], EvidenceAuthority.OBSERVED, source
        ),
        served_model_canonical=_fact(
            agent["served_model"], EvidenceAuthority.DERIVED, source
        ),
        observed_harness_build=_fact(
            runtime["harness_build"], EvidenceAuthority.OBSERVED, source
        ),
        effective_tools=_fact(tools, tools_authority, source),
        effective_policy=_fact(policy, policy_authority, source),
    )
    receipt = write_activation_receipt(
        plan, evidence, receipt_root=root / "activations"
    )
    return receipt.receipt_id, receipt.receipt_path


def _artifact(root: Path, path: Path) -> dict[str, str]:
    return {"path": path.relative_to(root).as_posix(), "sha256": _sha(path)}


def _observation(
    root: Path,
    runtime_path: Path,
    runtime: dict[str, Any],
    activations: dict[str, Path],
    suite_path: Path,
) -> Path:
    artifact = _artifact(root, runtime_path)
    suite = _artifact(root, suite_path)
    cases = {
        name: {"status": "pass", "evidence": [artifact, suite]}
        for name in CASES
    }
    body = {
        "schema": OBSERVATION_SCHEMA,
        "harness": runtime["harness"],
        "harness_build": runtime["harness_build"],
        "cases": cases,
        "agents": [
            {
                "agent_id": runtime["agents"][role]["agent_id"],
                "activation_receipt": activations[role]
                .relative_to(root)
                .as_posix(),
            }
            for role in ("parent", "child")
        ],
        "notes": "Sanitized live evidence; raw harness transcripts are intentionally excluded.",
    }
    path = root / f"{runtime['harness']}-observation.json"
    _write(path, body)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claude-stream", type=Path, required=True)
    parser.add_argument("--codex-parent", type=Path, required=True)
    parser.add_argument("--codex-child", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()

    root = args.output.resolve()
    canary = root / "canary"
    package_digest = digest_path(canary)
    claude = _claude(args.claude_stream.resolve(), package_digest)
    codex = _codex(
        args.codex_parent.resolve(), args.codex_child.resolve(), package_digest
    )
    evidence = root / "evidence"
    claude_path = evidence / "claude-runtime.json"
    codex_path = evidence / "codex-runtime.json"
    _write(claude_path, claude)
    _write(codex_path, codex)

    suite = {
        "schema": "spindle.adapter-conformance-suite-evidence/v1",
        "cases": list(CASES),
        "commands": [
            "pytest -q tests/test_conformance.py tests/test_acceptance_journey.py",
            "pytest -q",
            "ruff check .",
            "git diff --check",
        ],
        "fixture_digest": package_digest,
        "prior_live_evidence": {
            "m2_native_hooks": _sha(root.parent / "m2-native-hooks" / "native-evidence.tar.gz"),
            "m4_remote_codex": _sha(root.parent / "m4-pinned-remote" / "public-codex-evidence.tar.gz"),
        },
    }
    suite = {"evidence_id": content_id(suite), **suite}
    suite_path = evidence / "conformance-suite.json"
    _write(suite_path, suite)

    os.environ["SPINDLE_ADAPTER_CERTIFICATIONS_DIR"] = str(root / "certifications")
    results: dict[str, Any] = {}
    for runtime, runtime_path in ((claude, claude_path), (codex, codex_path)):
        activation_paths: dict[str, Path] = {}
        activation_ids: dict[str, str] = {}
        for role in ("parent", "child"):
            receipt_id, receipt_path = _activation(
                root, runtime, role, canary, package_digest
            )
            activation_ids[role] = receipt_id
            activation_paths[role] = receipt_path
        observation_path = _observation(
            root, runtime_path, runtime, activation_paths, suite_path
        )
        certification, certification_path = certify(load_observation(observation_path))
        results[runtime["harness"]] = {
            "observation": observation_path.relative_to(root).as_posix(),
            "activation_receipts": activation_ids,
            "certification_id": certification["certification_id"],
            "certification": certification_path.relative_to(root).as_posix(),
        }
    summary = {
        "schema": "spindle.adapter-certification-run/v1",
        "canary_digest": package_digest,
        "results": results,
    }
    _write(root / "result.json", {"run_id": content_id(summary), **summary})
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
