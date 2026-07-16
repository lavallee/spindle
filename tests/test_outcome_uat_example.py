"""The public outcome-UAT calibration must reject asserted success."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from spindle.evaluation import load_manifest, run_evaluation


EXAMPLE = Path(__file__).parent.parent / "examples" / "outcome-uat"
RUNNER = EXAMPLE / "runner.py"


def _capture_hash(state: dict[str, object]) -> str:
    payload = json.dumps(
        state,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _run_fixture(
    tmp_path: Path,
    fixture: Path | dict[str, object],
    *,
    arm: str = "variant",
) -> dict[str, object]:
    fixture_path = fixture
    if isinstance(fixture, dict):
        fixture_path = tmp_path / "fixture.json"
        fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    result_path = tmp_path / "result.json"
    process = subprocess.run(
        [sys.executable, str(RUNNER)],
        env={
            **os.environ,
            "SPINDLE_EVAL_ARM": arm,
            "SPINDLE_EVAL_FIXTURE": str(fixture_path),
            "SPINDLE_EVAL_RESULT_PATH": str(result_path),
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stderr
    return json.loads(result_path.read_text())


def _run_fixture_error(tmp_path: Path, fixture: dict[str, object]) -> str:
    fixture_path = tmp_path / "invalid-fixture.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    process = subprocess.run(
        [sys.executable, str(RUNNER)],
        env={
            **os.environ,
            "SPINDLE_EVAL_ARM": "variant",
            "SPINDLE_EVAL_FIXTURE": str(fixture_path),
            "SPINDLE_EVAL_RESULT_PATH": str(tmp_path / "invalid-result.json"),
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert process.returncode != 0
    return process.stderr


def test_outcome_uat_negative_controls_block_promotion(tmp_path: Path) -> None:
    _, receipt = run_evaluation(
        load_manifest(EXAMPLE / "eval.toml"),
        receipt_path=tmp_path / "receipt.json",
    )

    held_out = receipt["summaries"]["held_out"]
    assert held_out["errors"] == 0
    assert held_out["mean_score"] == {"baseline": 0.75, "variant": 1.0}
    assert held_out["delta"] == 0.25
    assert receipt["promotion"]["eligible"] is False
    assert receipt["promotion"]["reasons"] == ["required-variant-gates-failed"]
    assert receipt["promotion"]["failed_variant_gates"] == [
        {"case_id": "aggregate-destination-overclaim", "gate": "critic_repair"},
        {"case_id": "aggregate-destination-overclaim", "gate": "facts_correct"},
        {"case_id": "aggregate-destination-overclaim", "gate": "no_harm"},
        {"case_id": "critic-overreach", "gate": "critic_bounded"},
        {"case_id": "critic-overreach", "gate": "critic_repair"},
        {"case_id": "critic-self-review-noop-repair", "gate": "critic_bounded"},
        {"case_id": "critic-self-review-noop-repair", "gate": "critic_repair"},
        {
            "case_id": "declared-route-without-executed-destination",
            "gate": "earned_interaction",
        },
        {
            "case_id": "declared-route-without-executed-destination",
            "gate": "task_closed",
        },
        {"case_id": "meaningless-identical-choices", "gate": "earned_interaction"},
        {"case_id": "meaningless-identical-choices", "gate": "task_closed"},
        {"case_id": "oversized-payload", "gate": "delivery_budget"},
    ]

    variants = {
        run["case_id"]: run["result"]
        for run in receipt["runs"]
        if run["split"] == "held_out" and run["arm"] == "variant"
    }
    assert all(result["score"] == 1.0 for result in variants.values())
    expected_runner_hash = hashlib.sha256(RUNNER.read_bytes()).hexdigest()
    assert all(
        result["evidence"]["grader_sha256"] == expected_runner_hash
        for result in variants.values()
    )


def test_completion_signal_without_executed_terminal_trace_fails(
    tmp_path: Path,
) -> None:
    result = _run_fixture(
        tmp_path,
        EXAMPLE / "fixtures" / "declared-route-without-executed-destination.json",
    )

    gate = result["gates"]["task_closed"]
    assert gate["passed"] is False
    assert "named-case-visible" in result["evidence"]["captured_states"][1]["signals"]
    assert (
        "event event-jump-echo did not succeed"
        in gate["evidence"]["journey"]["violations"]
    )
    earned = result["gates"]["earned_interaction"]
    assert earned["passed"] is False
    assert earned["evidence"]["unexecuted_new_interactions"] == ["jump-echo"]


def test_zero_event_trace_cannot_earn_a_new_interaction(tmp_path: Path) -> None:
    fixture = json.loads((EXAMPLE / "fixtures" / "oversized-payload.json").read_text())
    variant = fixture["variant"]
    variant["states"][0]["outcome"] = {
        "purpose": "show current status",
        "answer": "Current status: stable",
        "proof_target": "fixture://status",
        "next_action": "read details",
    }
    variant["interactions"] = [
        {
            "id": "reveal-status",
            "from_state": "status",
            "to_state": "status",
            "new": True,
            "claimed_purpose": "show current status",
        }
    ]
    variant["loop"]["critic"]["input_capture_hashes"] = [
        _capture_hash(variant["states"][0])
    ]

    result = _run_fixture(tmp_path, fixture)
    journey = result["gates"]["task_closed"]["evidence"]["journey"]
    earned = result["gates"]["earned_interaction"]["evidence"]
    assert result["gates"]["task_closed"]["passed"] is False
    assert (
        "zero-event journey cannot close while new interactions claim credit"
        in journey["violations"]
    )
    assert journey["successful_interaction_ids"] == []
    assert earned["unexecuted_new_interactions"] == ["reveal-status"]


def test_aggregate_claim_exceeds_unlinked_source_scope_and_repair_passes(
    tmp_path: Path,
) -> None:
    broken = _run_fixture(
        tmp_path,
        EXAMPLE / "fixtures" / "aggregate-destination-overclaim.json",
    )
    assert broken["gates"]["task_closed"]["passed"] is True
    assert broken["gates"]["facts_correct"]["passed"] is False
    assert broken["gates"]["no_harm"]["passed"] is False
    assert broken["gates"]["critic_repair"]["passed"] is False
    failures = broken["gates"]["facts_correct"]["evidence"]["failures"]
    assert failures == [
        {
            "claim": "Each panel follows the same students one grade higher each year",
            "reason": (
                "fixture://assessment/grade-year does not support claim kind "
                "linked_individual"
            ),
        }
    ]

    repaired = _run_fixture(
        tmp_path,
        EXAMPLE / "fixtures" / "aggregate-destination-repaired.json",
    )
    assert repaired["passed"] is True
    assert all(gate["passed"] for gate in repaired["gates"].values())
    repair = repaired["gates"]["critic_repair"]["evidence"]
    assert repair["finding_ids"] == ["aggregate-called-individual"]
    assert repair["changed_artifacts"] == ["assessment"]
    assert len(repair["post_repair_gate_inputs_sha256"]) == 64


def test_unrelated_visible_change_does_not_satisfy_finding_postcondition(
    tmp_path: Path,
) -> None:
    fixture = json.loads(
        (EXAMPLE / "fixtures" / "aggregate-destination-overclaim.json").read_text()
    )
    fixture["variant"]["states"][1]["visible"].append("Spacing adjusted")

    result = _run_fixture(tmp_path, fixture)
    repair = result["gates"]["critic_repair"]
    assert repair["passed"] is False
    assert repair["evidence"]["changed_artifacts"] == ["assessment"]
    assert (
        "finding aggregate-called-individual postcondition failed: "
        "'same students' remains visible in assessment"
        in repair["evidence"]["violations"]
    )


def test_uncovered_material_claim_fails_closed(tmp_path: Path) -> None:
    fixture = json.loads(
        (EXAMPLE / "fixtures" / "sparse-honest-state.json").read_text()
    )
    fixture["variant"]["claims"].pop()

    result = _run_fixture(tmp_path, fixture)
    facts = result["gates"]["facts_correct"]
    assert facts["passed"] is False
    assert facts["evidence"]["failures"] == [
        {
            "claim": "Latest period: 2026",
            "reason": "material claim in explained is uncovered",
        }
    ]


@pytest.mark.parametrize("target", ["state", "outcome", "journey", "event"])
def test_consequential_schemas_reject_unknown_metadata(
    tmp_path: Path,
    target: str,
) -> None:
    fixture = json.loads((EXAMPLE / "fixtures" / "direct-record-jump.json").read_text())
    variant = fixture["variant"]
    targets = {
        "state": variant["states"][0],
        "outcome": variant["states"][1]["outcome"],
        "journey": variant["journey"],
        "event": variant["journey"]["events"][0],
    }
    targets[target]["review_metadata"] = "not consequential"

    stderr = _run_fixture_error(tmp_path, fixture)
    assert "unknown field(s): review_metadata" in stderr


def test_repair_requires_findings_and_unique_mappings(tmp_path: Path) -> None:
    source = json.loads(
        (EXAMPLE / "fixtures" / "aggregate-destination-repaired.json").read_text()
    )

    no_finding = json.loads(json.dumps(source))
    no_finding["variant"]["loop"]["critic"]["findings"] = []
    no_finding["variant"]["loop"]["repair"]["addresses"] = []
    result = _run_fixture(tmp_path, no_finding)
    assert (
        "repair requires at least one valid critic finding"
        in result["gates"]["critic_repair"]["evidence"]["violations"]
    )

    duplicates = json.loads(json.dumps(source))
    repair = duplicates["variant"]["loop"]["repair"]
    repair["addresses"].append(repair["addresses"][0])
    repair["affected_artifacts"].append(repair["affected_artifacts"][0])
    result = _run_fixture(tmp_path, duplicates)
    violations = result["gates"]["critic_repair"]["evidence"]["violations"]
    assert "repair addresses must be unique" in violations
    assert "repair affected artifacts must be unique" in violations


def test_critic_repair_requires_independence_and_changed_artifacts(
    tmp_path: Path,
) -> None:
    result = _run_fixture(
        tmp_path,
        EXAMPLE / "fixtures" / "critic-self-review-noop-repair.json",
    )

    boundary = result["gates"]["critic_bounded"]
    repair = result["gates"]["critic_repair"]
    assert boundary["passed"] is False
    assert "critic is not independent of producer" in boundary["evidence"]["violations"]
    assert repair["passed"] is False
    assert (
        "affected artifact did not change: answer" in repair["evidence"]["violations"]
    )
    assert repair["evidence"]["recomputed_by_runner"] == [
        "task_closed",
        "facts_correct",
        "accessibility",
        "no_harm",
        "earned_interaction",
        "responsive_layout",
        "delivery_budget",
    ]


def test_single_added_action_must_beat_the_simpler_replacement(
    tmp_path: Path,
) -> None:
    fixture = json.loads((EXAMPLE / "fixtures" / "oversized-payload.json").read_text())
    variant = fixture["variant"]
    variant["states"] = [
        {
            "id": "start",
            "route": "/status/",
            "visible": ["Open status"],
            "signals": [],
            "foreground": ["status-action"],
            "material_claims": [],
        },
        {
            "id": "status",
            "route": "/status/?open=1",
            "visible": ["Current status: stable"],
            "signals": ["current-status-visible"],
            "foreground": ["current-status"],
            "material_claims": ["Current status: stable"],
            "outcome": {
                "purpose": "show current status",
                "answer": "Current status: stable",
                "proof_target": "fixture://status",
                "next_action": "read details",
            },
        },
    ]
    variant["journey"] = {
        "executor": "scripted-browser",
        "entry_state": "start",
        "events": [
            {
                "id": "event-open-status",
                "interaction_id": "open-status",
                "from_state": "start",
                "to_state": "status",
                "action": "activate Open status",
                "result": "succeeded",
            }
        ],
        "terminal_state": "status",
        "foreground_target": "current-status",
    }
    variant["interactions"] = [
        {
            "id": "open-status",
            "from_state": "start",
            "to_state": "status",
            "new": True,
            "claimed_purpose": "show current status",
        }
    ]
    variant["claims"] = [
        {
            "artifact_id": "status",
            "text": "Current status: stable",
            "source": "fixture://status",
            "kind": "current_status",
        }
    ]
    variant["delivery"] = {"transferred_bytes": 320000, "rendered_bytes": 600000}
    variant["loop"]["critic"]["input_capture_hashes"] = [
        _capture_hash(state) for state in variant["states"]
    ]

    result = _run_fixture(tmp_path, fixture)
    evidence = result["gates"]["earned_interaction"]["evidence"]
    assert evidence["distinct_effective_outcomes"] == 1
    assert evidence["added_action_burden"] == 1
    assert evidence["baseline_task_closed"] is True
    assert result["gates"]["earned_interaction"]["passed"] is False
