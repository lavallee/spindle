"""Behavioral evaluation manifests, paired execution, and promotion receipts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from spindle import cli
from spindle.evaluation import EvaluationError, load_manifest, load_receipt, run_evaluation


RUNNER = '''
import json
import os
from pathlib import Path

fixture = json.loads(Path(os.environ["SPINDLE_EVAL_FIXTURE"]).read_text())
arm = os.environ["SPINDLE_EVAL_ARM"]
result = {
    "score": fixture[arm],
    "passed": fixture[arm] >= 0.5,
    "skill_invoked": arm == "variant",
    "evidence": {"grader": "fixture-literal", "case": os.environ["SPINDLE_EVAL_CASE_ID"]},
    "metrics": {"corrections": 0 if arm == "variant" else 1},
    "artifacts": [],
}
Path(os.environ["SPINDLE_EVAL_RESULT_PATH"]).write_text(json.dumps(result))
'''


def _manifest(tmp_path: Path, *, min_cases: int = 1) -> Path:
    skill = tmp_path / "SKILL.md"
    skill.write_text("# Diagnose\n\nAlways reproduce first.\n", encoding="utf-8")
    runner = tmp_path / "runner.py"
    runner.write_text(RUNNER, encoding="utf-8")
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "dev.json").write_text(
        json.dumps({"baseline": 0.4, "variant": 0.7}), encoding="utf-8"
    )
    (fixtures / "held.json").write_text(
        json.dumps({"baseline": 0.5, "variant": 0.8}), encoding="utf-8"
    )
    manifest = tmp_path / "eval.toml"
    manifest.write_text(
        f'''schema_version = 1
id = "diagnosis-pilot"
skill = "diagnosing-bugs"
skill_path = "SKILL.md"
runner = ["{sys.executable}", "runner.py"]
timeout_seconds = 10
seed = 41
min_held_out_cases = {min_cases}
min_improvement = 0.1
receipt_dir = "receipts"

[dimensions]
harness = "fixture"
model = "frozen-test-model"

[[cases]]
id = "dev-repro"
split = "development"
fixture = "fixtures/dev.json"
tags = ["diagnosis"]

[[cases]]
id = "held-repro"
split = "held_out"
fixture = "fixtures/held.json"
tags = ["diagnosis", "held-out"]
''',
        encoding="utf-8",
    )
    return manifest


def test_load_manifest_resolves_contract_paths(tmp_path: Path) -> None:
    manifest = load_manifest(_manifest(tmp_path))
    assert manifest.id == "diagnosis-pilot"
    assert manifest.skill_path == tmp_path / "SKILL.md"
    assert [case.id for case in manifest.cases] == ["dev-repro", "held-repro"]
    assert manifest.dimensions["harness"] == "fixture"


def test_load_manifest_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    path = _manifest(tmp_path)
    text = path.read_text(encoding="utf-8").replace('id = "held-repro"', 'id = "dev-repro"')
    path.write_text(text, encoding="utf-8")
    with pytest.raises(EvaluationError, match="duplicate case id"):
        load_manifest(path)


def test_run_evaluation_pairs_arms_and_allows_held_out_promotion(tmp_path: Path) -> None:
    output, receipt = run_evaluation(load_manifest(_manifest(tmp_path)))
    assert output.exists()
    assert len(receipt["runs"]) == 4
    assert {(run["case_id"], run["arm"]) for run in receipt["runs"]} == {
        ("dev-repro", "baseline"),
        ("dev-repro", "variant"),
        ("held-repro", "baseline"),
        ("held-repro", "variant"),
    }
    assert receipt["summaries"]["held_out"]["delta"] == pytest.approx(0.3)
    assert receipt["promotion"] == {
        "eligible": True,
        "reasons": [],
        "required_cases": 1,
        "required_improvement": 0.1,
        "observed_delta": pytest.approx(0.3),
    }
    assert load_receipt(output)["skill_sha256"] == receipt["skill_sha256"]


def test_development_only_run_never_qualifies_for_promotion(tmp_path: Path) -> None:
    _, receipt = run_evaluation(load_manifest(_manifest(tmp_path)), split="development")
    assert receipt["promotion"]["eligible"] is False
    assert "insufficient-held-out-cases" in receipt["promotion"]["reasons"]


def test_runner_result_without_evidence_blocks_promotion(tmp_path: Path) -> None:
    path = _manifest(tmp_path)
    runner = tmp_path / "runner.py"
    runner.write_text(RUNNER.replace('"evidence": {"grader": "fixture-literal", "case": os.environ["SPINDLE_EVAL_CASE_ID"]},', '"evidence": {},'), encoding="utf-8")
    _, receipt = run_evaluation(load_manifest(path), split="held_out")
    assert all(run["status"] == "error" for run in receipt["runs"])
    assert receipt["promotion"]["eligible"] is False
    assert "runner-errors" in receipt["promotion"]["reasons"]


def test_cli_validate_run_and_show(tmp_path: Path, capsys) -> None:
    manifest = _manifest(tmp_path)
    assert cli.main(["eval", "validate", str(manifest)]) == 0
    capsys.readouterr()
    receipt = tmp_path / "pilot-receipt.json"
    assert cli.main(["eval", "run", str(manifest), "--receipt", str(receipt)]) == 0
    run_output = capsys.readouterr().out
    assert "promotion: eligible" in run_output
    assert cli.main(["eval", "show", str(receipt)]) == 0
    assert "held_out" in capsys.readouterr().out
