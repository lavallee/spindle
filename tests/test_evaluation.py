"""Behavioral evaluation manifests, paired execution, and promotion receipts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from spindle import cli
from spindle.binding import record_evaluated_binding
from spindle.composition import ComposedSkill, Composition
from spindle.evaluation import (
    EvaluationError,
    load_manifest,
    load_receipt,
    record_promotion,
    run_evaluation,
)


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
if "gates" in fixture and arm in fixture["gates"]:
    result["gates"] = fixture["gates"][arm]
Path(os.environ["SPINDLE_EVAL_RESULT_PATH"]).write_text(json.dumps(result))
'''


def _manifest(
    tmp_path: Path,
    *,
    min_cases: int = 1,
    required_gates: tuple[str, ...] = (),
) -> Path:
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
    acceptance = ""
    if required_gates:
        encoded_gates = ", ".join(json.dumps(gate) for gate in required_gates)
        acceptance = f"\n[acceptance]\nrequired_variant_gates = [{encoded_gates}]\n"
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
{acceptance}

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


def _procedure_manifest(tmp_path: Path) -> Path:
    manifest = _manifest(tmp_path)
    text = manifest.read_text(encoding="utf-8")
    text = text.replace(
        '[dimensions]\nharness = "fixture"\nmodel = "frozen-test-model"',
        '[dimensions]\nharness = "fixture"\nmodel = "frozen-test-model"\n'
        'profile = "procedure-profile@1"\nbaseline_implementation = "raw-agent@1"',
    )
    text += '''
[origin]
schema = "spindle.procedure-origin/v1"
milton_finding_id = "fnd-1"
milton_revision_id = "fnr-1"
chip_candidate_id = "candidate-1"
chip_receipt_id = "chip-receipt-1"
'''
    manifest.write_text(text, encoding="utf-8")
    return manifest


def test_load_manifest_resolves_contract_paths(tmp_path: Path) -> None:
    manifest = load_manifest(_manifest(tmp_path))
    assert manifest.id == "diagnosis-pilot"
    assert manifest.skill_path == tmp_path / "SKILL.md"
    assert [case.id for case in manifest.cases] == ["dev-repro", "held-repro"]
    assert manifest.dimensions["harness"] == "fixture"
    assert manifest.required_variant_gates == ()


def test_load_manifest_accepts_unique_nonempty_variant_gates(tmp_path: Path) -> None:
    manifest = load_manifest(_manifest(tmp_path, required_gates=("facts", "no-harm")))
    assert manifest.required_variant_gates == ("facts", "no-harm")


@pytest.mark.parametrize(
    ("acceptance", "message"),
    [
        ('acceptance = "strict"\n', r"\[acceptance\] must be a table"),
        (
            "[acceptance]\nrequired_variant_gates = []\n",
            "must be a non-empty array",
        ),
        (
            '[acceptance]\nrequired_variant_gates = ["facts", ""]\n',
            "values must be non-empty strings",
        ),
        (
            "[acceptance]\nrequired_variant_gates = [1]\n",
            "values must be non-empty strings",
        ),
        (
            '[acceptance]\nrequired_variant_gates = ["facts", " facts "]\n',
            "values must be unique",
        ),
        (
            '[acceptance]\nrequired_varaint_gates = ["facts"]\n',
            r"\[acceptance\] unknown key\(s\): required_varaint_gates",
        ),
        (
            '[acceptence]\nrequired_variant_gates = ["facts"]\n',
            r"unknown top-level manifest key\(s\): acceptence",
        ),
        (
            'required_variant_gates = ["facts"]\n',
            r"unknown top-level manifest key\(s\): required_variant_gates",
        ),
    ],
)
def test_load_manifest_rejects_malformed_acceptance(
    tmp_path: Path, acceptance: str, message: str
) -> None:
    path = _manifest(tmp_path)
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace("\n[dimensions]\n", f"\n{acceptance}\n[dimensions]\n"),
        encoding="utf-8",
    )
    with pytest.raises(EvaluationError, match=message):
        load_manifest(path)


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
    assert receipt["required_variant_gates"] == []
    assert load_receipt(output)["skill_sha256"] == receipt["skill_sha256"]


def test_failed_required_gate_blocks_high_scoring_held_out_variant(
    tmp_path: Path,
    capsys,
) -> None:
    path = _manifest(tmp_path, required_gates=("facts", "no-harm"))
    (tmp_path / "fixtures" / "held.json").write_text(
        json.dumps(
            {
                "baseline": 0.1,
                "variant": 0.99,
                "gates": {
                    "baseline": {
                        "facts": {"passed": True, "evidence": "baseline checked"},
                        "no-harm": {"passed": True, "evidence": "baseline checked"},
                    },
                    "variant": {
                        "facts": {"passed": True, "evidence": {"checked": 0}},
                        "no-harm": {
                            "passed": False,
                            "evidence": "unsafe output observed",
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    output, receipt = run_evaluation(load_manifest(path), split="held_out")
    assert receipt["summaries"]["held_out"]["delta"] == pytest.approx(0.89)
    assert receipt["promotion"] == {
        "eligible": False,
        "reasons": ["required-variant-gates-failed"],
        "required_cases": 1,
        "required_improvement": 0.1,
        "observed_delta": pytest.approx(0.89),
        "required_variant_gates": ["facts", "no-harm"],
        "failed_variant_gates": [{"case_id": "held-repro", "gate": "no-harm"}],
    }
    assert cli.main(["eval", "show", str(output)]) == 0
    assert "held-repro/no-harm" in capsys.readouterr().out


def test_false_baseline_gate_is_receipt_evidence_but_does_not_block(
    tmp_path: Path,
) -> None:
    path = _manifest(tmp_path, required_gates=("facts",))
    (tmp_path / "fixtures" / "held.json").write_text(
        json.dumps(
            {
                "baseline": 0.5,
                "variant": 0.8,
                "gates": {
                    "baseline": {"facts": {"passed": False, "evidence": False}},
                    "variant": {"facts": {"passed": True, "evidence": {"checked": 0}}},
                },
            }
        ),
        encoding="utf-8",
    )
    _, receipt = run_evaluation(load_manifest(path), split="held_out")
    baseline = next(run for run in receipt["runs"] if run["arm"] == "baseline")
    assert baseline["result"]["gates"] == {
        "facts": {"passed": False, "evidence": False}
    }
    assert receipt["promotion"]["eligible"] is True
    assert receipt["promotion"]["failed_variant_gates"] == []


@pytest.mark.parametrize(
    ("gates", "message"),
    [
        (None, "gates must be an object"),
        ([], "gates must be an object"),
        ({"other": True}, "gates is missing required gate 'facts'"),
        ({"facts": "yes"}, "gate 'facts' must be an object"),
        (
            {"facts": {"passed": "yes", "evidence": "checked"}},
            "gate 'facts' passed must be boolean",
        ),
        (
            {"facts": {"passed": True}},
            "gate 'facts' evidence must be a non-empty string, array, or object",
        ),
    ],
)
def test_required_gates_reject_malformed_runner_results(
    tmp_path: Path, gates: object, message: str
) -> None:
    path = _manifest(tmp_path, required_gates=("facts",))
    fixture = {"baseline": 0.5, "variant": 0.9}
    if gates is not None:
        fixture["gates"] = {"variant": gates}
    (tmp_path / "fixtures" / "held.json").write_text(
        json.dumps(fixture), encoding="utf-8"
    )
    _, receipt = run_evaluation(load_manifest(path), split="held_out")
    baseline = next(run for run in receipt["runs"] if run["arm"] == "baseline")
    variant = next(run for run in receipt["runs"] if run["arm"] == "variant")
    assert baseline["status"] == "ok"
    assert variant["status"] == "error"
    assert message in variant["error"]
    assert "runner-errors" in receipt["promotion"]["reasons"]


@pytest.mark.parametrize(
    ("evidence", "message"),
    [
        (None, "must be a non-empty string, array, or object"),
        (False, "must be a non-empty string, array, or object"),
        (0, "must be a non-empty string, array, or object"),
        ("", "must be a non-empty string, array, or object"),
        ("   ", "must be a non-empty string, array, or object"),
        ([], "must be a non-empty string, array, or object"),
        ({}, "must be a non-empty string, array, or object"),
    ],
)
def test_required_gates_reject_missing_or_empty_gate_evidence(
    tmp_path: Path,
    evidence: object,
    message: str,
) -> None:
    path = _manifest(tmp_path, required_gates=("facts",))
    fixture = {
        "baseline": 0.5,
        "variant": 0.9,
        "gates": {
            "variant": {"facts": {"passed": True, "evidence": evidence}}
        },
    }
    (tmp_path / "fixtures" / "held.json").write_text(
        json.dumps(fixture), encoding="utf-8"
    )
    _, receipt = run_evaluation(load_manifest(path), split="held_out")
    baseline = next(run for run in receipt["runs"] if run["arm"] == "baseline")
    variant = next(run for run in receipt["runs"] if run["arm"] == "variant")
    assert baseline["status"] == "ok"
    assert variant["status"] == "error"
    assert message in variant["error"]
    assert "runner-errors" in receipt["promotion"]["reasons"]


def test_development_only_run_never_qualifies_for_promotion(tmp_path: Path) -> None:
    _, receipt = run_evaluation(load_manifest(_manifest(tmp_path)), split="development")
    assert receipt["promotion"]["eligible"] is False
    assert "insufficient-held-out-cases" in receipt["promotion"]["reasons"]


def test_required_gates_do_not_change_development_result_contract(tmp_path: Path) -> None:
    _, receipt = run_evaluation(
        load_manifest(_manifest(tmp_path, required_gates=("facts",))),
        split="development",
    )
    assert all(run["status"] == "ok" for run in receipt["runs"])
    assert all("gates" not in run["result"] for run in receipt["runs"])
    assert receipt["required_variant_gates"] == ["facts"]


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


def test_procedure_evaluation_binds_origin_tuple_and_idempotent_promotion(
    tmp_path: Path, monkeypatch
) -> None:
    import spindle.binding as binding

    monkeypatch.setattr(binding.paths, "spindle_home", lambda: tmp_path / "state")
    output, receipt = run_evaluation(
        load_manifest(_procedure_manifest(tmp_path)),
        split="held_out",
        receipt_path=tmp_path / "evaluation-receipt.json",
    )
    assert load_receipt(output)["origin"]["milton_revision_id"] == "fnr-1"
    assert receipt["evaluation_tuple"] == {
        "implementation": f"sha256:{receipt['skill_sha256']}",
        "profile": "procedure-profile@1",
        "model": "frozen-test-model",
        "harness": "fixture",
    }
    assert receipt["baseline_tuple"]["implementation"] == "raw-agent@1"

    composition = Composition(
        surface="repo:procedure-pilot",
        autonomy_mode="deterministic",
        skills=[ComposedSkill("diagnosing-bugs", str(tmp_path / "SKILL.md"), "candidate")],
    )
    bound = record_evaluated_binding(
        composition,
        doctrine_coordinate="procedure-doctrine@1",
        channel_versions={"candidate": "1"},
        evaluation_receipt=receipt,
    )
    assert bound.evaluation_receipt_id == receipt["receipt_id"]
    assert bound.origin == receipt["origin"]

    path = tmp_path / "promotion-receipt.json"
    first = record_promotion(receipt, bound, path)
    replay = record_promotion(receipt, bound, path)
    assert replay == first
    assert first["schema"] == "spindle.procedure-promotion/v1"
    assert first["binding"]["coordinate"] == bound.coordinate
    assert first["origin"]["chip_receipt_id"] == "chip-receipt-1"


def test_procedure_origin_requires_complete_tuple_dimensions(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + '''
[origin]
schema = "spindle.procedure-origin/v1"
milton_finding_id = "fnd-1"
milton_revision_id = "fnr-1"
chip_candidate_id = "candidate-1"
chip_receipt_id = "chip-receipt-1"
''',
        encoding="utf-8",
    )
    with pytest.raises(EvaluationError, match="dimensions.*missing"):
        load_manifest(manifest)


def test_design_evaluation_requires_complete_des_profile_dimensions(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            'model = "frozen-test-model"',
            'model = "frozen-test-model"\ndes_profile = "des-operator-frontier-test"',
        ),
        encoding="utf-8",
    )
    with pytest.raises(EvaluationError, match="design evaluation.*missing"):
        load_manifest(manifest)


def test_design_evaluation_accepts_explicit_mode_model_harness_tuple(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            'model = "frozen-test-model"',
            '''model = "frozen-test-model"
des_profile = "des-public-data-frontier-test"
surface_mode = "public-data"
model_tier = "frontier"
requested_model = "gpt-test"
served_model = "gpt-test-served"
capabilities = "browser,visual-input"''',
        ),
        encoding="utf-8",
    )
    loaded = load_manifest(manifest)
    assert loaded.dimensions["surface_mode"] == "public-data"
    assert loaded.dimensions["served_model"] == "gpt-test-served"


def test_design_evaluation_rejects_unknown_surface_mode(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            'model = "frozen-test-model"',
            '''model = "frozen-test-model"
des_profile = "des-website-frontier-test"
surface_mode = "website"
model_tier = "frontier"
requested_model = "gpt-test"
served_model = "gpt-test"
capabilities = "browser"''',
        ),
        encoding="utf-8",
    )
    with pytest.raises(EvaluationError, match="surface_mode must be"):
        load_manifest(manifest)
