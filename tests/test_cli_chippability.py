"""Tests for `spindle chippability` — table, JSON, candidate emit, ledger append."""

from __future__ import annotations

import json

import pytest

from spindle.cli import main
from spindle.paths import chippability_ledger_path


@pytest.fixture(autouse=True)
def isolated_spindle_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "spindle-state"))


CHIP_CANDIDATE = """\
---
name: signoff
---
# signoff

Invoke this after every review lands. Read the findings registry at
~/.signoff/registry and compare against the stored commit SHA; a record goes
stale when the file changed since last run. The doctor exits 1 and refuses to
proceed while any finding is unresolved. Emit a verdict: cleared or concerns.
"""

PLAIN_TOOL = """\
---
name: pdf
---
# pdf

Read a PDF, extract text, merge, split. A reference for common operations.
"""


def _pkg(tmp_path):
    """A two-skill package dir discoverable via spindle package metadata."""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.spindle.package]\n"
        'name = "demo-skills"\nversion = "0.1.0"\n'
        'skills = ["signoff", "pdf"]\n'
    )
    for name, body in (("signoff", CHIP_CANDIDATE), ("pdf", PLAIN_TOOL)):
        d = tmp_path / "demo_skills" / "skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(body)
    return tmp_path


def test_table_lists_every_skill(tmp_path, capsys):
    root = _pkg(tmp_path)
    rc = main(["chippability", str(root)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "signoff" in out
    assert "pdf" in out
    assert "chip-candidate" in out
    assert "assessed 2 skill(s)" in out


def test_ledger_appended_per_skill(tmp_path):
    root = _pkg(tmp_path)
    main(["chippability", str(root)])
    lines = chippability_ledger_path().read_text().splitlines()
    assert len(lines) == 2
    records = [json.loads(ln) for ln in lines]
    skills = {r["skill"]: r for r in records}
    assert skills["signoff"]["hint"] == "chip-candidate"
    assert skills["signoff"]["package"] == "demo-skills"
    for r in records:
        assert set(r) == {"at", "skill", "package", "score", "hint"}


def test_emit_candidates_appends_only_candidates(tmp_path):
    root = _pkg(tmp_path)
    cand = tmp_path / "candidates.jsonl"
    main(["chippability", str(root), "--emit-candidates", str(cand)])
    lines = cand.read_text().splitlines()
    assert len(lines) == 1  # only the chip-candidate skill, not the plain tool
    record = json.loads(lines[0])
    # the public candidates.jsonl convention (github.com/lavallee/chip docs/candidates.md)
    assert set(record) == {"observedAt", "shape", "occurrenceRefs", "fixtureRefs", "count", "notedBy"}
    assert record["notedBy"] == "spindle:chippability"
    assert record["occurrenceRefs"] == ["skill:demo-skills/signoff"]
    assert record["shape"]


def test_json_output(tmp_path, capsys):
    root = _pkg(tmp_path)
    rc = main(["chippability", str(root), "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert {p["skill"] for p in payload} == {"signoff", "pdf"}
    signoff = next(p for p in payload if p["skill"] == "signoff")
    assert signoff["classification_hint"] == "chip-candidate"
    assert any(s["polarity"] == "positive" for s in signoff["signals"])


def test_single_skill_dir(tmp_path, capsys):
    d = tmp_path / "signoff"
    d.mkdir()
    (d / "SKILL.md").write_text(CHIP_CANDIDATE)
    rc = main(["chippability", str(d)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "signoff" in out


def test_missing_path_errors(tmp_path, capsys):
    rc = main(["chippability", str(tmp_path / "nope")])
    assert rc == 1
