"""The public outcome-UAT calibration must reject superficial success."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from spindle.evaluation import load_manifest, run_evaluation


EXAMPLE = Path(__file__).parent.parent / "examples" / "outcome-uat"


def test_outcome_uat_negative_controls_block_promotion(tmp_path: Path) -> None:
    _, receipt = run_evaluation(
        load_manifest(EXAMPLE / "eval.toml"),
        receipt_path=tmp_path / "receipt.json",
    )

    held_out = receipt["summaries"]["held_out"]
    assert held_out["errors"] == 0
    assert held_out["mean_score"] == {"baseline": 0.75, "variant": 1.0}
    assert held_out["delta"] == 0.25

    promotion = receipt["promotion"]
    assert promotion["eligible"] is False
    assert promotion["reasons"] == ["required-variant-gates-failed"]
    assert promotion["failed_variant_gates"] == [
        {"case_id": "critic-overreach", "gate": "critic_bounded"},
        {"case_id": "meaningless-identical-choices", "gate": "earned_interaction"},
        {"case_id": "meaningless-identical-choices", "gate": "task_closed"},
        {"case_id": "oversized-payload", "gate": "delivery_budget"},
    ]

    variants = {
        run["case_id"]: run["result"]
        for run in receipt["runs"]
        if run["split"] == "held_out" and run["arm"] == "variant"
    }
    absurd = variants["meaningless-identical-choices"]
    assert absurd["score"] == 1.0
    assert absurd["gates"]["accessibility"]["passed"] is True
    assert absurd["gates"]["responsive_layout"]["passed"] is True
    assert absurd["gates"]["earned_interaction"]["passed"] is False

    oversized = variants["oversized-payload"]
    assert oversized["score"] == 1.0
    assert oversized["gates"]["delivery_budget"]["passed"] is False
    assert oversized["gates"]["delivery_budget"]["evidence"]["transferred_bytes"] == 11_200_000

    overreach = variants["critic-overreach"]
    assert overreach["score"] == 1.0
    assert overreach["gates"]["critic_bounded"]["passed"] is False
    assert all(
        gate["passed"] is True
        for name, gate in overreach["gates"].items()
        if name != "critic_bounded"
    )
    assert "critic role exceeded risk-finder-only" in overreach["gates"]["critic_bounded"]["evidence"]["violations"]

    expected_runner_hash = hashlib.sha256((EXAMPLE / "runner.py").read_bytes()).hexdigest()
    assert all(
        result["evidence"]["grader_sha256"] == expected_runner_hash
        for result in variants.values()
    )


def test_single_added_action_must_beat_the_simpler_replacement(tmp_path: Path) -> None:
    fixture = json.loads((EXAMPLE / "fixtures" / "oversized-payload.json").read_text())
    variant = fixture["variant"]
    variant["states"] = [
        {"id": "start", "route": "/status/", "visible": ["Open status"], "signals": []},
        {
            "id": "status",
            "route": "/status/?open=1",
            "visible": ["Current status: stable"],
            "signals": ["current-status-visible"],
            "outcome": {
                "purpose": "show current status",
                "answer": "Current status: stable",
                "proof_target": "fixture://status",
                "next_action": "read details",
            },
        },
    ]
    variant["interactions"] = [
        {
            "id": "open-status",
            "from_state": "start",
            "to_state": "status",
            "new": True,
            "claimed_purpose": "show current status",
        }
    ]
    variant["delivery"] = {"transferred_bytes": 320_000, "rendered_bytes": 600_000}

    fixture_path = tmp_path / "fixture.json"
    result_path = tmp_path / "result.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    process = subprocess.run(
        [sys.executable, str(EXAMPLE / "runner.py")],
        env={
            **os.environ,
            "SPINDLE_EVAL_ARM": "variant",
            "SPINDLE_EVAL_FIXTURE": str(fixture_path),
            "SPINDLE_EVAL_RESULT_PATH": str(result_path),
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stderr
    result = json.loads(result_path.read_text())
    evidence = result["gates"]["earned_interaction"]["evidence"]
    assert evidence["distinct_effective_outcomes"] == 1
    assert evidence["added_action_burden"] == 1
    assert evidence["baseline_task_closed"] is True
    assert result["gates"]["earned_interaction"]["passed"] is False
