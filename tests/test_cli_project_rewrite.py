"""Tests for `spindle ingest`'s project-name rewrite and idempotency.

Pins:
  - Default: project field is rewritten to basename(context.cwd) from each
    task's own context — so tasks that live in ~/Projects/magpie land under
    project=magpie regardless of where the spindle tool is run from.
  - Fallback: task_id first segment when context.cwd is absent
    (e.g. "magpie-ajs-0.1" → project="magpie").
  - --project NAME explicit override wins over per-task inference.
  - --keep-project disables rewriting entirely.
  - Original project (typically the plan slug) is stashed in
    context.plan_slug for traceability.
  - Concept entries are not touched (they don't have a project).
  - Idempotency: a sidecar .ingested.json file prevents duplicate POSTs on
    a second run; --reimport forces re-ingestion.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from spindle import cli as cli_mod
from spindle import ingest as ingest_mod


@pytest.fixture
def jsonl_path(tmp_path: Path) -> Path:
    """A 3-row plan where context.cwd correctly identifies the repo."""
    rows = [
        {"kind": "todo", "project": "ai-journalism-scouting",
         "content": "Set up scaffolding",
         "context": {"task_id": "ajs-0.1", "epic_id": "ajs-0",
                     "cwd": "/home/marc/Projects/magpie"}},
        {"kind": "todo", "project": "ai-journalism-scouting",
         "content": "Wire data model",
         "context": {"task_id": "ajs-0.2",
                     "cwd": "/home/marc/Projects/magpie"},
         "edges": [{"type": "depends_on", "target": "ajs-0.1"}]},
        {"kind": "idea", "concept": "story-as-notebook",
         "content": "Portable bundles across tools",
         "context": {"task_id": "ajs-1.0"}},
    ]
    p = tmp_path / "itemized-plan.todos.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return p


def _run_cli(jsonl_path, monkeypatch, *, posted_capture, **kwargs):
    """Run cmd_ingest with stubbed network + the chosen overrides."""
    posted_capture.clear()

    def fake_post(_url, body):
        posted_capture.append(body)
        return {"id": f"01HX{len(posted_capture):022d}", "ts": "x"}

    monkeypatch.setattr(ingest_mod, "_post_register", fake_post)
    args = SimpleNamespace(
        path=str(jsonl_path),
        task_url="http://stub",
        dry_run=False,
        strict=False,
        project=kwargs.get("project"),
        keep_project=kwargs.get("keep_project", False),
        reimport=kwargs.get("reimport", False),
    )
    return cli_mod.cmd_ingest(args)


def test_default_uses_context_cwd_basename(jsonl_path, monkeypatch, tmp_path):
    """context.cwd basename is used as the project, not the spindle tool's cwd."""
    # Run from an unrelated directory — should not affect project resolution.
    monkeypatch.chdir(tmp_path)

    posted: list = []
    rc = _run_cli(jsonl_path, monkeypatch, posted_capture=posted)
    assert rc == 0
    # Both todo entries carry context.cwd="/home/marc/Projects/magpie" → "magpie"
    todos = [b for b in posted if b.get("kind") == "todo"]
    assert all(t["project"] == "magpie" for t in todos), [t["project"] for t in todos]
    # Original plan slug stashed for traceability
    for t in todos:
        assert t["context"]["plan_slug"] == "ai-journalism-scouting"
    # Concept entry preserved
    concepts = [b for b in posted if b.get("kind") == "idea"]
    assert len(concepts) == 1
    assert concepts[0]["concept"] == "story-as-notebook"
    assert "project" not in concepts[0]


def test_tool_cwd_is_not_used_as_project(tmp_path, monkeypatch):
    """Running spindle from inside the tool directory must NOT produce project='spindle'."""
    fake_tool_dir = tmp_path / "spindle"
    fake_tool_dir.mkdir()
    monkeypatch.chdir(fake_tool_dir)

    rows = [
        {"kind": "todo", "project": "ai-journalism-scouting",
         "content": "A task",
         "context": {"task_id": "magpie-ajs-0.1",
                     "cwd": "/home/marc/Projects/magpie"}},
    ]
    jsonl = tmp_path / "plan.todos.jsonl"
    jsonl.write_text(json.dumps(rows[0]) + "\n")

    posted: list = []

    def fake_post(_url, body):
        posted.append(body)
        return {"id": "01HX0000000000000000000001", "ts": "x"}

    monkeypatch.setattr(ingest_mod, "_post_register", fake_post)
    args = SimpleNamespace(
        path=str(jsonl),
        task_url="http://stub",
        dry_run=False,
        strict=False,
        project=None,
        keep_project=False,
        reimport=False,
    )
    rc = cli_mod.cmd_ingest(args)
    assert rc == 0
    assert len(posted) == 1
    assert posted[0]["project"] == "magpie", f"got {posted[0]['project']!r}, expected 'magpie'"


def test_task_id_prefix_fallback(tmp_path, monkeypatch):
    """When context.cwd is absent, first segment of task_id is used as project."""
    rows = [
        {"kind": "todo", "project": "ai-journalism-scouting",
         "content": "A task without cwd",
         "context": {"task_id": "magpie-ajs-0.1"}},
    ]
    jsonl = tmp_path / "plan.todos.jsonl"
    jsonl.write_text(json.dumps(rows[0]) + "\n")

    posted: list = []

    def fake_post(_url, body):
        posted.append(body)
        return {"id": "01HX0000000000000000000001", "ts": "x"}

    monkeypatch.setattr(ingest_mod, "_post_register", fake_post)
    args = SimpleNamespace(
        path=str(jsonl),
        task_url="http://stub",
        dry_run=False,
        strict=False,
        project=None,
        keep_project=False,
        reimport=False,
    )
    rc = cli_mod.cmd_ingest(args)
    assert rc == 0
    assert posted[0]["project"] == "magpie"


def test_explicit_project_override(jsonl_path, monkeypatch, tmp_path):
    """--project NAME wins over context.cwd and task_id inference."""
    monkeypatch.chdir(tmp_path)

    posted: list = []
    rc = _run_cli(jsonl_path, monkeypatch, posted_capture=posted, project="weaver")
    assert rc == 0
    todos = [b for b in posted if b.get("kind") == "todo"]
    assert all(t["project"] == "weaver" for t in todos)


def test_keep_project_preserves_original(jsonl_path, monkeypatch, tmp_path):
    """--keep-project disables the rewrite — entries keep whatever they had."""
    monkeypatch.chdir(tmp_path)

    posted: list = []
    rc = _run_cli(jsonl_path, monkeypatch, posted_capture=posted, keep_project=True)
    assert rc == 0
    todos = [b for b in posted if b.get("kind") == "todo"]
    # Original plan-slug-as-project preserved
    assert all(t["project"] == "ai-journalism-scouting" for t in todos)
    # No plan_slug in context — we didn't rewrite
    for t in todos:
        assert "plan_slug" not in (t.get("context") or {})


def test_concept_entries_skipped(jsonl_path, monkeypatch, tmp_path):
    """Concept entries don't have a project field; rewrite leaves them alone."""
    monkeypatch.chdir(tmp_path)

    posted: list = []
    _run_cli(jsonl_path, monkeypatch, posted_capture=posted)
    concepts = [b for b in posted if b.get("kind") == "idea"]
    assert len(concepts) == 1
    assert "project" not in concepts[0]
    assert concepts[0]["concept"] == "story-as-notebook"


def test_idempotency_skips_on_rerun(jsonl_path, monkeypatch, tmp_path):
    """A second ingest without --reimport skips already-ingested task_ids."""
    monkeypatch.chdir(tmp_path)
    posted: list = []
    call_count = [0]

    def fake_post(_url, body):
        call_count[0] += 1
        posted.append(body)
        return {"id": f"01HX{call_count[0]:022d}", "ts": "x"}

    monkeypatch.setattr(ingest_mod, "_post_register", fake_post)

    def run(reimport=False):
        posted.clear()
        args = SimpleNamespace(
            path=str(jsonl_path),
            task_url="http://stub",
            dry_run=False,
            strict=False,
            project=None,
            keep_project=False,
            reimport=reimport,
        )
        return cli_mod.cmd_ingest(args)

    # First run: all entries POSTed
    rc1 = run()
    assert rc1 == 0
    first_posted = len(posted)
    assert first_posted == 3  # 2 todos + 1 concept

    # Second run without --reimport: nothing new should be POSTed
    rc2 = run()
    assert rc2 == 0
    assert len(posted) == 0, f"expected 0 new POSTs on second run, got {len(posted)}"


def test_reimport_flag_reposts(jsonl_path, monkeypatch, tmp_path):
    """--reimport forces re-ingestion even if sidecar exists."""
    monkeypatch.chdir(tmp_path)
    posted: list = []
    call_count = [0]

    def fake_post(_url, body):
        call_count[0] += 1
        posted.append(body)
        return {"id": f"01HX{call_count[0]:022d}", "ts": "x"}

    monkeypatch.setattr(ingest_mod, "_post_register", fake_post)

    def run(reimport=False):
        posted.clear()
        args = SimpleNamespace(
            path=str(jsonl_path),
            task_url="http://stub",
            dry_run=False,
            strict=False,
            project=None,
            keep_project=False,
            reimport=reimport,
        )
        return cli_mod.cmd_ingest(args)

    # First run creates the sidecar
    rc1 = run()
    assert rc1 == 0
    assert len(posted) == 3

    # Second run with --reimport should POST again
    rc2 = run(reimport=True)
    assert rc2 == 0
    assert len(posted) == 3, f"expected 3 re-POSTs with --reimport, got {len(posted)}"


def test_sidecar_written_next_to_jsonl(jsonl_path, monkeypatch, tmp_path):
    """After a successful ingest, the .ingested.json sidecar is written."""
    monkeypatch.chdir(tmp_path)
    call_count = [0]

    def fake_post(_url, body):
        call_count[0] += 1
        return {"id": f"01HX{call_count[0]:022d}", "ts": "x"}

    monkeypatch.setattr(ingest_mod, "_post_register", fake_post)
    args = SimpleNamespace(
        path=str(jsonl_path),
        task_url="http://stub",
        dry_run=False,
        strict=False,
        project=None,
        keep_project=False,
        reimport=False,
    )
    cli_mod.cmd_ingest(args)

    sidecar = jsonl_path.with_name(jsonl_path.stem + ".ingested.json")
    assert sidecar.exists(), "sidecar .ingested.json should be written after ingest"
    data = json.loads(sidecar.read_text())
    # Both todo task_ids should be recorded; concept (_anon_ or explicit id)
    # tracked task_ids should not include _anon_ prefixes
    assert "ajs-0.1" in data
    assert "ajs-0.2" in data
