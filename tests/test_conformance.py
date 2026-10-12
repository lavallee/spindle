"""Adapter capability negotiation and build certification coverage."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from spindle.adapters import (
    CODEX_ADAPTER,
    ActivationEvidence,
    EvidenceAuthority,
    EvidenceFact,
    ProjectionMode,
    ProjectionPlan,
    RealizationReference,
    write_activation_receipt,
)
from spindle.conformance import (
    CASES,
    OBSERVATION_SCHEMA,
    CapabilityRequirement,
    ConformanceError,
    capability_matrix,
    certify,
    load_certification,
    load_observation,
    negotiate,
    validate_observation,
)


def _fact(value, authority, source):
    return EvidenceFact(value, authority, source)


def _activation(tmp_path: Path, agent: str, parent: str | None = None) -> Path:
    plan = ProjectionPlan(
        session_id="session",
        agent_id=agent,
        parent_agent_id=parent,
        harness="codex",
        adapter_id=CODEX_ADAPTER.id,
        mode=ProjectionMode.SKILL_PATH,
        target=f"target:{agent}",
        realization=RealizationReference(
            skill="review",
            path=Path("review"),
            package_digest="sha256:" + "1" * 64,
            realization_digest="sha256:" + ("2" if parent is None else "3") * 64,
            realization_receipt_id="sha256:" + ("4" if parent is None else "5") * 64,
        ),
    )
    evidence = ActivationEvidence(
        projection_loaded=_fact(True, EvidenceAuthority.OBSERVED, "inventory"),
        served_model_raw=_fact(
            "gpt-parent" if parent is None else "gpt-child",
            EvidenceAuthority.OBSERVED,
            "turn-context",
        ),
        observed_harness_build=_fact(
            "0.146.0", EvidenceAuthority.OBSERVED, "version"
        ),
        effective_tools=_fact(
            ("Read",) if parent is None else ("Search",),
            EvidenceAuthority.OBSERVED,
            "turn-context",
        ),
        effective_policy=_fact(
            "read-only", EvidenceAuthority.OBSERVED, "turn-context"
        ),
    )
    return write_activation_receipt(
        plan, evidence, receipt_root=tmp_path / "activations"
    ).receipt_path


def _observation(tmp_path: Path) -> dict:
    artifact = tmp_path / "evidence.json"
    artifact.write_text('{"result":"pass"}\n', encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    return {
        "schema": OBSERVATION_SCHEMA,
        "harness": "codex",
        "harness_build": "0.146.0",
        "cases": {
            name: {
                "status": "pass",
                "evidence": [{"path": str(artifact), "sha256": digest}],
            }
            for name in CASES
        },
        "agents": [
            {"agent_id": "parent", "activation_receipt": str(_activation(tmp_path, "parent"))},
            {
                "agent_id": "child",
                "activation_receipt": str(_activation(tmp_path, "child", "parent")),
            },
        ],
    }


def test_partial_defaults_fail_closed_until_observed_capabilities(tmp_path):
    matrix = capability_matrix("codex", harness_build="0.146.0")
    result = negotiate(
        matrix,
        [
            CapabilityRequirement("projection"),
            CapabilityRequirement("model-identity"),
        ],
    )
    assert result["compatible"] is False
    assert result["requirements"][1]["actual"] == "partial"

    observed = capability_matrix(
        "codex",
        harness_build="0.146.0",
        observation=_observation(tmp_path),
    )
    assert observed["capabilities"]["model-identity"]["status"] == "pass"
    assert negotiate(
        observed, [CapabilityRequirement("model-identity")]
    )["compatible"] is True


def test_certification_requires_independent_complete_agent_receipts(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "state"))
    observation = _observation(tmp_path)
    checked = validate_observation(observation)
    assert [agent["served_model"] for agent in checked["agents"]] == [
        "gpt-parent",
        "gpt-child",
    ]
    receipt, path = certify(observation)

    assert receipt["status"] == "certified"
    assert path is not None and path.is_file()
    assert load_certification(path)["certification_id"] == receipt["certification_id"]

    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["status"] = "partial"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ConformanceError, match="identity mismatch"):
        load_certification(path)


def test_passing_case_cannot_lack_evidence_and_agent_facts_cannot_be_inferred(
    tmp_path,
):
    observation = _observation(tmp_path)
    observation["cases"]["inventory"]["evidence"] = []
    with pytest.raises(ConformanceError, match="needs evidence"):
        validate_observation(observation)

    observation = _observation(tmp_path)
    receipt = Path(observation["agents"][1]["activation_receipt"])
    raw = json.loads(receipt.read_text(encoding="utf-8"))
    raw["activation_evidence"]["effective"]["policy"] = None
    stable = {
        key: value
        for key, value in raw.items()
        if key not in {"receipt_id", "created_at"}
    }
    raw["receipt_id"] = hashlib.sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    receipt.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ConformanceError, match="effective_policy"):
        validate_observation(observation)


def test_certification_requires_loaded_projection_and_matching_runtime_coordinate(
    tmp_path,
):
    observation = _observation(tmp_path)
    receipt = Path(observation["agents"][1]["activation_receipt"])
    raw = json.loads(receipt.read_text(encoding="utf-8"))
    raw["activation_evidence"]["projection_loaded"]["value"] = False
    stable = {
        key: value
        for key, value in raw.items()
        if key not in {"receipt_id", "created_at"}
    }
    raw["receipt_id"] = hashlib.sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    receipt.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ConformanceError, match="does not prove"):
        validate_observation(observation)

    second = tmp_path / "second"
    second.mkdir()
    observation = _observation(second)
    observation["harness_build"] = "0.147.0"
    with pytest.raises(ConformanceError, match="activation build does not match"):
        validate_observation(observation)


def test_certification_identity_excludes_resolved_machine_paths(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    for root in (left, right):
        root.mkdir()
        observation = _observation(root)
        # Logical references remain stable while validation resolves each copy.
        for case in observation["cases"].values():
            case["evidence"][0]["path"] = "evidence.json"
        for index, agent in enumerate(observation["agents"]):
            agent["activation_receipt"] = f"activations/{Path(agent['activation_receipt']).name}"
        (root / "observation.json").write_text(
            json.dumps(observation), encoding="utf-8"
        )

    left_checked = load_observation(left / "observation.json")
    right_checked = load_observation(right / "observation.json")
    left_receipt, _ = certify(left_checked, dry_run=True)
    right_receipt, _ = certify(right_checked, dry_run=True)
    assert left_receipt["certification_id"] == right_receipt["certification_id"]
