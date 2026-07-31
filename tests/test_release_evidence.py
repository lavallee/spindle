"""Checked-in 1.0 adapter evidence remains complete and content-valid."""

from __future__ import annotations

import json
from pathlib import Path

from spindle.conformance import CASES, load_certification, load_observation


ROOT = Path(__file__).parents[1] / "experiments" / "m7-adapter-certification"


def test_reference_adapter_certifications_are_complete_and_independent():
    result = json.loads((ROOT / "result.json").read_text(encoding="utf-8"))
    expected = {
        "claude": ("2.1.220", "claude-opus-5", "claude-sonnet-5"),
        "codex": ("0.146.0", "gpt-5.6-sol", "gpt-5.6-terra"),
    }
    for harness, (build, parent_model, child_model) in expected.items():
        entry = result["results"][harness]
        certification = load_certification(ROOT / entry["certification"])
        observation = load_observation(ROOT / entry["observation"])

        assert certification["certification_id"] == entry["certification_id"]
        assert certification["status"] == "certified"
        assert certification["harness_build"] == build
        assert certification["capability_gaps"] == []
        assert set(certification["matrix"]["capabilities"]) == set(CASES)
        assert all(
            item["status"] == "pass"
            for item in certification["matrix"]["capabilities"].values()
        )
        assert observation["harness"] == harness
        assert [agent["served_model"] for agent in observation["agents"]] == [
            parent_model,
            child_model,
        ]
        assert observation["agents"][0]["parent_agent_id"] is None
        assert (
            observation["agents"][1]["parent_agent_id"]
            == observation["agents"][0]["agent_id"]
        )
        assert len(set(entry["activation_receipts"].values())) == 2


def test_runtime_evidence_is_sanitized_and_raw_transcripts_are_not_checked_in():
    assert not list(ROOT.rglob("*.jsonl"))
    assert not list(ROOT.rglob("*.log"))
    for target in sorted((ROOT / "evidence").glob("*-runtime.json")):
        raw = target.read_text(encoding="utf-8")
        assert '"prompt"' not in raw
        assert '"message"' not in raw
        assert '"result"' not in raw
        assert '"source_log_sha256"' in raw
