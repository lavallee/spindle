"""Tests for spindle.gates — body shape, dry-run, injectable sink."""

from __future__ import annotations

import spindle.gates as gg


def test_build_body_has_gate_and_tag():
    body = gg.build_gate_body(crux="absolutes at system scope?",
                              proposed_diff="P-X: A over B", pilot="measure X", source="spec-kit")
    # surfaces via the needs:human steering tag (verified contract); spindle:doctrine scopes it
    assert gg.STEERING_TAG in body["tags"]
    assert gg.GATE_TAG in body["tags"]
    assert "gate" not in body  # no dead top-level field — /register ignores it
    assert body["context"]["gate"] is True  # belt-and-suspenders; steering also checks this
    assert body["context"]["proposed_diff"] == "P-X: A over B"
    assert body["context"]["pilot"] == "measure X"
    assert body["context"]["source"] == "spec-kit"
    assert body["content"] == "absolutes at system scope?"
    assert body["kind"] == "decision"
    assert body["project"] == "spindle"


def test_build_body_omits_empty_optionals():
    body = gg.build_gate_body(crux="just a crux")
    assert "proposed_diff" not in body["context"]
    assert "pilot" not in body["context"]
    assert "source" not in body["context"]


def test_build_body_handles_empty_crux():
    body = gg.build_gate_body(crux="   ")
    assert "no crux" in body["content"]


def test_file_gate_dry_run_does_not_post():
    posted = []
    result = gg.file_gate(crux="x", dry_run=True, sink=lambda b: posted.append(b))
    assert "dry_run" in result
    assert result["dry_run"]["content"] == "x"
    assert posted == []  # injected sink never called on dry-run


def test_file_gate_uses_injected_sink():
    calls = []

    def fake_sink(body):
        calls.append(body)
        return {"id": "ENTRY123", "ts": "2026-05-21T00:00:00Z"}

    result = gg.file_gate(crux="real crux", proposed_diff="d", sink=fake_sink)
    assert result["id"] == "ENTRY123"
    assert len(calls) == 1
    body = calls[0]
    assert gg.STEERING_TAG in body["tags"]
    assert gg.GATE_TAG in body["tags"]


# ---- adjudication parsing + file_from_result ----------------------------

ADJ_REPORT = '''
Some preamble prose from the adjudicator.

```yaml
crux: "absolutes at system scope or not?"
proposed_diff: "system favors absolutes; repo favors preferences"
pilot: "values call — no pilot"
recommendation: "graduate by scope"
source: "spec-kit"
```
'''


def test_parse_adjudication_from_yaml_block():
    f = gg.parse_adjudication(ADJ_REPORT)
    assert f["crux"] == "absolutes at system scope or not?"
    assert f["proposed_diff"].startswith("system favors")
    assert f["pilot"] == "values call — no pilot"
    assert f["source"] == "spec-kit"


def test_parse_adjudication_loose_lines():
    f = gg.parse_adjudication('crux: just a crux\npilot: measure X\n')
    assert f["crux"] == "just a crux"
    assert f["pilot"] == "measure X"


def test_file_from_result_plain_md(tmp_path):
    p = tmp_path / "adj.md"
    p.write_text(ADJ_REPORT)
    captured = []
    res = gg.file_from_result(p, sink=lambda b: captured.append(b) or {"id": "E1"})
    assert res["id"] == "E1"
    body = captured[0]
    assert body["content"] == "absolutes at system scope or not?"
    assert body["context"]["source"] == "spec-kit"
    assert gg.GATE_TAG in body["tags"]


def test_file_from_result_json_output(tmp_path):
    import json
    p = tmp_path / "adj.json"
    p.write_text(json.dumps({"output": ADJ_REPORT}))
    res = gg.file_from_result(p, dry_run=True)
    assert res["dry_run"]["content"] == "absolutes at system scope or not?"


def test_file_from_result_no_crux_errors(tmp_path):
    p = tmp_path / "empty.md"
    p.write_text("no structured fields here\n")
    res = gg.file_from_result(p, dry_run=True)
    assert "error" in res
