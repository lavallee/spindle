"""Tests for `spindle ingest`.

The unit tests use an injected task sink to verify that an itemized-plan JSONL
flows through ingest correctly, including topo ordering and edge resolution.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from spindle import ingest as ingest_mod
from spindle.ingest import (
    IngestResult,
    IngestRow,
    _resolve_edges,
    parse_jsonl,
    topological_order,
)


# ---- parse_jsonl --------------------------------------------------------

def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


def test_parse_basic(tmp_path):
    p = _write_jsonl(tmp_path / "p.jsonl", [
        {"kind": "todo", "project": "weaver", "content": "rewrite intro",
         "context": {"task_id": "weaver-A-0.1"}},
    ])
    rows = parse_jsonl(p)
    assert len(rows) == 1
    assert rows[0].task_id == "weaver-A-0.1"
    assert rows[0].edges_raw == []


def test_parse_skips_blank_lines_and_comments(tmp_path):
    p = tmp_path / "p.jsonl"
    p.write_text(
        '{"kind":"todo","project":"x","content":"a","context":{"task_id":"a"}}\n'
        "\n"
        "// a comment\n"
        '{"kind":"todo","project":"x","content":"b","context":{"task_id":"b"}}\n'
    )
    rows = parse_jsonl(p)
    assert [r.task_id for r in rows] == ["a", "b"]


def test_parse_rejects_missing_content(tmp_path):
    p = _write_jsonl(tmp_path / "p.jsonl", [
        {"kind": "todo", "project": "x", "content": ""},
    ])
    with pytest.raises(ValueError, match="missing/empty 'content'"):
        parse_jsonl(p)


def test_parse_rejects_bad_edge_shape(tmp_path):
    p = _write_jsonl(tmp_path / "p.jsonl", [
        {"kind": "todo", "project": "x", "content": "a",
         "context": {"task_id": "a"}, "edges": ["not-a-dict"]},
    ])
    with pytest.raises(ValueError, match="each edge needs"):
        parse_jsonl(p)


def test_parse_rejects_duplicate_task_id(tmp_path):
    p = _write_jsonl(tmp_path / "p.jsonl", [
        {"kind": "todo", "project": "x", "content": "a", "context": {"task_id": "dup"}},
        {"kind": "todo", "project": "x", "content": "b", "context": {"task_id": "dup"}},
    ])
    with pytest.raises(ValueError, match="duplicate task_id"):
        parse_jsonl(p)


# ---- topological_order --------------------------------------------------

def _row(task_id, *, edges=None, project="p") -> IngestRow:
    return IngestRow(
        task_id=task_id,
        payload={"kind": "todo", "project": project, "content": task_id,
                 "context": {"task_id": task_id}, "edges": edges or []},
        edges_raw=list(edges or []),
        line_no=1,
    )


def test_topo_no_deps_keeps_input_order():
    rows = [_row("a"), _row("b"), _row("c")]
    out = topological_order(rows)
    assert [r.task_id for r in out] == ["a", "b", "c"]


def test_topo_blocks_orders_blocker_before_target():
    """`A.blocks(B)` (spindle-itemize convention) → A must come before B."""
    rows = [
        _row("A", edges=[{"type": "blocks", "target": "B"}]),
        _row("B"),
    ]
    out = topological_order(rows)
    assert [r.task_id for r in out] == ["A", "B"]


def test_topo_depends_on_orders_target_before_dependent():
    """`B.depends_on(A)` → A must come before B (inverse of blocks)."""
    rows = [
        _row("B", edges=[{"type": "depends_on", "target": "A"}]),
        _row("A"),
    ]
    out = topological_order(rows)
    assert [r.task_id for r in out] == ["A", "B"]


def test_topo_blocks_and_depends_on_express_same_graph():
    """The same A→B ordering can be expressed either way and must produce
    the same topo result."""
    expressed_with_blocks = topological_order([
        _row("A", edges=[{"type": "blocks", "target": "B"}]),
        _row("B"),
    ])
    expressed_with_depends_on = topological_order([
        _row("B", edges=[{"type": "depends_on", "target": "A"}]),
        _row("A"),
    ])
    assert [r.task_id for r in expressed_with_blocks] == ["A", "B"]
    assert [r.task_id for r in expressed_with_depends_on] == ["A", "B"]


def test_topo_chain_via_blocks():
    """A→B→C→D chain expressed via the blocks edge: each row blocks the next."""
    rows = [
        _row("A", edges=[{"type": "blocks", "target": "B"}]),
        _row("B", edges=[{"type": "blocks", "target": "C"}]),
        _row("C", edges=[{"type": "blocks", "target": "D"}]),
        _row("D"),
    ]
    out = topological_order(rows)
    assert [r.task_id for r in out] == ["A", "B", "C", "D"]


def test_topo_chain_via_depends_on():
    rows = [
        _row("D", edges=[{"type": "depends_on", "target": "C"}]),
        _row("C", edges=[{"type": "depends_on", "target": "B"}]),
        _row("B", edges=[{"type": "depends_on", "target": "A"}]),
        _row("A"),
    ]
    out = topological_order(rows)
    assert [r.task_id for r in out] == ["A", "B", "C", "D"]


def test_topo_relates_to_is_not_a_dependency():
    """relates_to is symmetric; doesn't impose ordering."""
    rows = [
        _row("B", edges=[{"type": "relates_to", "target": "A"}]),
        _row("A"),
    ]
    out = topological_order(rows)
    # No dependency means input order preserved
    assert [r.task_id for r in out] == ["B", "A"]


def test_topo_existing_ulid_target_is_not_a_dependency():
    """Edges to existing sink IDs don't induce ordering on this batch."""
    rows = [
        _row("B", edges=[{"type": "blocks", "target": "01HXY3KZAB12345678ABCDEFGH"}]),
        _row("A"),
    ]
    out = topological_order(rows)
    assert [r.task_id for r in out] == ["B", "A"]


def test_topo_unresolved_target_is_not_a_dependency():
    """A reference to a task_id not in this plan shouldn't block ordering."""
    rows = [
        _row("A", edges=[{"type": "blocks", "target": "MISSING"}]),
        _row("B"),
    ]
    out = topological_order(rows)
    assert {r.task_id for r in out} == {"A", "B"}


def test_topo_detects_cycle_via_depends_on():
    rows = [
        _row("A", edges=[{"type": "depends_on", "target": "B"}]),
        _row("B", edges=[{"type": "depends_on", "target": "A"}]),
    ]
    with pytest.raises(ValueError, match="cycle"):
        topological_order(rows)


def test_topo_detects_cycle_via_blocks():
    """A.blocks(B) and B.blocks(A) is also a cycle."""
    rows = [
        _row("A", edges=[{"type": "blocks", "target": "B"}]),
        _row("B", edges=[{"type": "blocks", "target": "A"}]),
    ]
    with pytest.raises(ValueError, match="cycle"):
        topological_order(rows)


def test_topo_detects_cycle_mixed_edge_types():
    """A.blocks(B) and B.depends_on(A) point the same way (no cycle).
    Verify that A.blocks(B) + A.depends_on(B) IS a cycle though."""
    cycle_rows = [
        _row("A", edges=[
            {"type": "blocks", "target": "B"},      # A before B
            {"type": "depends_on", "target": "B"},  # B before A — cycle
        ]),
        _row("B"),
    ]
    with pytest.raises(ValueError, match="cycle"):
        topological_order(cycle_rows)


# ---- edge resolution ----------------------------------------------------

def test_resolve_edges_remaps_task_ids_to_entry_ids():
    edges = [
        {"type": "blocks", "target": "A"},
        {"type": "relates_to", "target": "01HXY3KZAB12345678ABCDEFGH"},  # ULID passthrough
    ]
    id_map = {"A": "01HXAAAAAAAAAAAAAAAAAAAAAA"}
    resolved, warns = _resolve_edges(edges, id_map, line_no=1)
    assert warns == []
    assert resolved == [
        {"type": "blocks", "target": "01HXAAAAAAAAAAAAAAAAAAAAAA"},
        {"type": "relates_to", "target": "01HXY3KZAB12345678ABCDEFGH"},
    ]


def test_resolve_edges_warns_on_unresolved_target():
    edges = [{"type": "blocks", "target": "MISSING_TASK"}]
    id_map: dict[str, str] = {}
    resolved, warns = _resolve_edges(edges, id_map, line_no=42)
    assert resolved == []
    assert len(warns) == 1
    assert "line 42" in warns[0]
    assert "MISSING_TASK" in warns[0]


# ---- ingest with injected sink -----------------------------------------

class _FakeTaskSink:
    """Stand-in for a pluggable task sink."""

    def __init__(self):
        self.posted: list[dict] = []
        self._counter = 0
        self.fail_for: set[str] = set()  # task_ids that should error

    def __call__(self, body: dict) -> dict:
        ctx = body.get("context") or {}
        task_id = ctx.get("task_id")
        if task_id in self.fail_for:
            import urllib.error
            raise urllib.error.URLError("simulated failure")
        self._counter += 1
        eid = f"01HX{self._counter:022d}"  # fake but ULID-shaped
        self.posted.append(body)
        return {"id": eid, "ts": "2026-04-30T00:00:00Z", "path": "/tmp/fake"}


def test_ingest_rewrites_blocks_to_depends_on(monkeypatch):
    """A.blocks(B) at ingest time should:
      1. Rewrite as B.depends_on(A) (edge moves from blocker to dependent)
      2. Post A first, B second (topo order)
      3. B's depends_on edge resolves to A's entry-ULID (already posted)
    """
    fake = _FakeTaskSink()

    rows = [
        _row("A", edges=[{"type": "blocks", "target": "B"}]),
        _row("B"),
    ]
    res = ingest_mod.ingest(rows, log=False, sink=fake)
    assert res.posted == 2
    assert res.failed == 0

    # Order: A first, then B
    assert ctx_task_id(fake.posted[0]) == "A"
    assert ctx_task_id(fake.posted[1]) == "B"

    # A's blocks-edge was rewritten away
    a_edges = fake.posted[0].get("edges") or []
    assert a_edges == []

    # B got a depends_on referencing A's resolved entry ULID
    b_edges = fake.posted[1].get("edges") or []
    assert b_edges == [{"type": "depends_on", "target": res.id_map["A"]}]


def test_rewrite_blocks_idempotent_for_external_targets():
    """Blocks edges to ULIDs (external entries) must NOT be rewritten;
    the target isn't in this batch."""
    rows = [
        _row("A", edges=[
            {"type": "blocks", "target": "01HAAAAAAAAAAAAAAAAAAAAAAA"},
        ]),
    ]
    ingest_mod.rewrite_blocks_to_depends_on(rows)
    # External blocks edges stay on the blocker (A)
    assert rows[0].edges_raw == [
        {"type": "blocks", "target": "01HAAAAAAAAAAAAAAAAAAAAAAA"}
    ]


def test_rewrite_blocks_chain():
    """A.blocks(B), B.blocks(C) → after rewrite: B.depends_on(A), C.depends_on(B)."""
    rows = [
        _row("A", edges=[{"type": "blocks", "target": "B"}]),
        _row("B", edges=[{"type": "blocks", "target": "C"}]),
        _row("C"),
    ]
    ingest_mod.rewrite_blocks_to_depends_on(rows)
    by_task = {r.task_id: r for r in rows}
    assert by_task["A"].edges_raw == []
    assert by_task["B"].edges_raw == [{"type": "depends_on", "target": "A"}]
    assert by_task["C"].edges_raw == [{"type": "depends_on", "target": "B"}]


def test_ingest_dry_run_does_not_post(monkeypatch):
    called = {"n": 0}

    def boom(*a, **kw):
        called["n"] += 1
        raise AssertionError("should not POST in dry-run")

    monkeypatch.setattr(ingest_mod, "_post_register", boom)
    rows = [_row("A"), _row("B", edges=[{"type": "blocks", "target": "A"}])]
    res = ingest_mod.ingest(rows, dry_run=True, log=False)
    assert res.posted == 0
    assert res.skipped == 2
    assert called["n"] == 0
    # Dry-run still produces a usable id_map (with placeholder ids)
    assert "A" in res.id_map and "B" in res.id_map


def test_ingest_continues_past_failure_by_default(monkeypatch):
    fake = _FakeTaskSink()
    fake.fail_for = {"B"}

    rows = [_row("A"), _row("B"), _row("C")]
    res = ingest_mod.ingest(rows, log=False, sink=fake)
    assert res.posted == 2
    assert res.failed == 1
    assert len(res.errors) == 1
    # A and C should still have entry ids; B should not
    assert "A" in res.id_map
    assert "C" in res.id_map
    assert "B" not in res.id_map


def test_ingest_strict_mode_aborts_on_failure(monkeypatch):
    fake = _FakeTaskSink()
    fake.fail_for = {"A"}
    rows = [_row("A"), _row("B")]
    with pytest.raises(RuntimeError, match="task sink failed"):
        ingest_mod.ingest(rows, strict=True, log=False, sink=fake)


def test_ingest_tags_with_provenance(monkeypatch):
    fake = _FakeTaskSink()
    rows = [_row("A")]
    ingest_mod.ingest(rows, log=False, sink=fake)
    assert "spindle-ingest" in fake.posted[0].get("tags", [])
    assert fake.posted[0].get("session") == "spindle-ingest"


def ctx_task_id(body: dict) -> str:
    return (body.get("context") or {}).get("task_id", "")
