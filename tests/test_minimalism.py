"""Named-arm non-inferiority and bounded distillation coverage."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from spindle.cli import main
from spindle.minimalism import (
    MinimalismError,
    classify_material,
    distillation_plan,
    load_manifest,
    load_receipt,
    receipt_freshness,
    run_evaluation,
    stage_trial_revision,
)


RUNNER = '''
import json
import os
from pathlib import Path

fixture = json.loads(Path(os.environ["SPINDLE_EVAL_FIXTURE"]).read_text())
arm = os.environ["SPINDLE_EVAL_ARM"]
status = "not-applicable" if arm == "none" else "pass"
gates = {}
for gate in ("availability", "activation", "routing", "authorization", "behavior", "adapter"):
    gate_status = status if gate != "behavior" else "pass"
    gates[gate] = {"status": gate_status, "evidence": "fixture" if gate_status == "pass" else None}
result = {
    "score": fixture["scores"][arm],
    "gates": gates,
    "evidence": {"grader": "fixture", "repeat": os.environ["SPINDLE_EVAL_REPEAT"]},
    "metrics": {"corrections": 0},
}
Path(os.environ["SPINDLE_EVAL_RESULT_PATH"]).write_text(json.dumps(result))
'''


def _manifest(tmp_path: Path, *, candidate_score: float = 0.79) -> Path:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "core.md").write_text("Invariant safety rule.\n", encoding="utf-8")
    (artifacts / "empty.md").write_text("", encoding="utf-8")
    (artifacts / "incumbent.md").write_text(
        "Invariant safety rule.\nLong redundant explanation and example.\n",
        encoding="utf-8",
    )
    (artifacts / "ablation.md").write_text("Invariant safety rule.\n", encoding="utf-8")
    runner = tmp_path / "runner.py"
    runner.write_text(RUNNER, encoding="utf-8")
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    scores = {
        "none": 0.60,
        "core": 0.76,
        "empty": candidate_score,
        "incumbent": 0.80,
        "without-example": 0.79,
    }
    for name in ("dev", "held-one", "held-two"):
        fixtures.joinpath(f"{name}.json").write_text(
            json.dumps({"scores": scores}), encoding="utf-8"
        )
    manifest = tmp_path / "minimalism.toml"
    manifest.write_text(
        f'''schema = "spindle.minimalism-eval/v1"
id = "review-minimalism"
skill = "review"
runner = ["{sys.executable}", "runner.py"]
candidate_arm = "empty"
reference_arm = "incumbent"
repeats = 3
timeout_seconds = 10
seed = 17
non_inferiority_margin = 0.03
hard_floor = 0.70
min_artifact_reduction_bytes = 1
required_gates = ["availability", "activation", "routing", "authorization", "behavior", "adapter"]
receipt_dir = "receipts"

[coordinate]
model = "frontier-v1"
harness = "fixture"
harness_build = "fixture-1"
toolset_digest = "sha256:tools"
policy_digest = "sha256:policy"
active_blend_digest = "sha256:blend"

[[arms]]
id = "none"
kind = "no-skill"

[[arms]]
id = "core"
kind = "invariant-core"
artifact = "artifacts/core.md"

[[arms]]
id = "empty"
kind = "candidate-overlay"
artifact = "artifacts/empty.md"

[[arms]]
id = "incumbent"
kind = "incumbent"
artifact = "artifacts/incumbent.md"

[[arms]]
id = "without-example"
kind = "ablation"
artifact = "artifacts/ablation.md"

[[cases]]
id = "development"
split = "development"
fixture = "fixtures/dev.json"

[[cases]]
id = "held-one"
split = "held_out"
fixture = "fixtures/held-one.json"

[[cases]]
id = "held-two"
split = "held_out"
fixture = "fixtures/held-two.json"
''',
        encoding="utf-8",
    )
    return manifest


def test_named_arms_can_certify_an_empty_overlay_as_non_inferior(tmp_path):
    manifest = load_manifest(_manifest(tmp_path))
    output, receipt = run_evaluation(manifest)
    decision = receipt["distillation_gate"]

    assert output.exists()
    assert len(receipt["runs"]) == 45
    assert {arm["kind"] for arm in receipt["arms"]} == {
        "no-skill",
        "invariant-core",
        "candidate-overlay",
        "incumbent",
        "ablation",
    }
    assert next(arm for arm in receipt["arms"] if arm["id"] == "empty")[
        "artifact_bytes"
    ] == 0
    assert decision["eligible"] is True
    assert decision["non_inferior"] is True
    assert decision["hard_floor_passed"] is True
    assert decision["efficiency_passed"] is True
    assert all(value["passed"] for value in decision["gates"].values())
    assert receipt["task_distribution_digest"] == manifest.task_distribution_digest
    assert load_receipt(output)["receipt_id"] == receipt["receipt_id"]


def test_negative_result_is_retained_and_model_change_requires_rebaseline(tmp_path):
    manifest = load_manifest(_manifest(tmp_path, candidate_score=0.60))
    output, receipt = run_evaluation(manifest, split="held_out")

    assert output.exists()
    assert receipt["distillation_gate"]["eligible"] is False
    assert "hard-floor-failed" in receipt["distillation_gate"]["reasons"]
    current = dict(manifest.coordinate)
    current["model"] = "frontier-v2"
    freshness = receipt_freshness(receipt, tuple(current.items()))
    assert freshness["fresh"] is False
    assert freshness["changed"] == ["model"]
    assert freshness["decision"] == "rebaseline-required"

    tampered = json.loads(output.read_text(encoding="utf-8"))
    tampered["distillation_gate"]["eligible"] = True
    output.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(MinimalismError, match="identity mismatch"):
        load_receipt(output)


def test_classify_plan_and_stage_one_deletion_without_adoption(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    skill = package / "SKILL.md"
    original = (
        "---\nname: review\ndescription: Review.\n---\n\n"
        "## Invariant\nCheck correctness.\n\n"
        "## Redundant example\nExplain the obvious twice.\n"
    )
    skill.write_text(original, encoding="utf-8")
    scripts = package / "scripts"
    scripts.mkdir()
    scripts.joinpath("check.py").write_text("print('check')\n", encoding="utf-8")
    references = package / "references"
    references.mkdir()
    references.joinpath("protocol.md").write_text("Protocol facts.\n", encoding="utf-8")
    references.joinpath("old.md").write_text(
        "Deprecated workaround: obsolete.\n", encoding="utf-8"
    )

    classified = classify_material(package)
    rows = {row["path"]: row for row in classified["materials"]}
    assert rows["SKILL.md"]["classification"] == "behavioral-steering"
    assert rows["scripts/check.py"]["recommended_destination"] == "chip-or-tool"
    assert rows["references/protocol.md"]["recommended_destination"] == (
        "progressive-reference"
    )
    assert rows["references/old.md"]["classification"] == "obsolete-workaround"

    plan = distillation_plan(package)
    proposal = next(
        item
        for item in plan["proposals"]
        if item.get("heading") == "Redundant example"
    )
    destination = tmp_path / "candidate"
    preview = stage_trial_revision(
        package, proposal["proposal_id"], destination, dry_run=True
    )
    assert preview["action"] == "would-stage"
    assert not destination.exists()

    staged = stage_trial_revision(
        package, proposal["proposal_id"], destination, dry_run=False
    )
    assert staged["trial_revision"]["adoption_change"] is None
    assert "Redundant example" not in destination.joinpath("SKILL.md").read_text()
    assert skill.read_text(encoding="utf-8") == original
    assert Path(staged["receipt_path"]).is_file()


def test_matrix_and_distillation_cli_surface(tmp_path, capsys):
    manifest = _manifest(tmp_path)
    assert main(["eval", "matrix", "validate", str(manifest)]) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated["schema"] == "spindle.minimalism-eval/v1"

    assert (
        main(
            [
                "eval",
                "matrix",
                "run",
                str(manifest),
                "--split",
                "held_out",
                "--json",
            ]
        )
        == 0
    )
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["distillation_gate"]["eligible"] is True

    package = tmp_path / "simple-package"
    package.mkdir()
    package.joinpath("SKILL.md").write_text(
        "---\nname: simple\ndescription: Simple.\n---\n\n## Rule\nDo it.\n",
        encoding="utf-8",
    )
    assert main(["eval", "distill", "plan", str(package), "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["promotion_policy"] == "stage-as-trial-never-auto-adopt"
