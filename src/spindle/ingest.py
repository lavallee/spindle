"""Ingest an itemized-plan JSONL sidecar into a pluggable task sink.

The shape of `plans/{slug}/itemized-plan.todos.jsonl` (per
`skills/itemize/SKILL.md`):

  {"kind":"todo","project":"<slug>","content":"...",
   "context":{"cwd":"...","assignee":"runner",
              "epic_id":"<epic-id>","task_id":"<task-id>",
              "priority":"P1","labels":[...]},
   "edges":[{"type":"blocks","target":"<other-task-id>"}]}

`task_id` is hierarchical (e.g. `cub-048A-0.1`) — it is **not** a
task entry ID. Edges target task_ids of other entries in the
same plan, so we ingest in dependency order and rewrite each
entry's edges to use the entry-IDs returned by the previous POSTs.

Usage:

  spindle ingest plans/cub-048A/itemized-plan.todos.jsonl
  spindle ingest --dry-run …            # parse + plan, don't POST
  spindle ingest --strict …             # abort on first error
  spindle ingest --task-url URL …       # POST to an external sink

Without ``--task-url`` / ``SPINDLE_TASK_URL``, Spindle writes a local JSONL queue
to ``SPINDLE_TASK_QUEUE`` or ``$SPINDLE_HOME/tasks.jsonl``. Private layers can
provide a task service by passing a URL or by injecting ``sink`` in tests/tools.
"""

from __future__ import annotations

import json
import os
import re
import uuid
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths

DEFAULT_TASK_URL = os.environ.get("SPINDLE_TASK_URL", "")

# 26-char Crockford ULID. Used to distinguish "this edge target is an existing
# entry ID" from "this is a task_id that needs resolving".
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


# ---- data model --------------------------------------------------------

@dataclass
class IngestRow:
    """One row from the JSONL, with the parts we route on lifted out."""
    task_id: str             # from context.task_id (hierarchical)
    payload: dict[str, Any]  # the full row, edges still task_id-shaped
    edges_raw: list[dict[str, str]] = field(default_factory=list)
    line_no: int = 0         # 1-based line in the source file

    @property
    def edge_task_targets(self) -> list[str]:
        """task_id targets in this row's edges (not pre-existing entry IDs)."""
        return [e["target"] for e in self.edges_raw if not _ULID_RE.match(e.get("target", ""))]


@dataclass
class IngestResult:
    posted: int = 0
    skipped: int = 0
    failed: int = 0
    id_map: dict[str, str] = field(default_factory=dict)   # task_id → entry_id
    errors: list[tuple[int, str]] = field(default_factory=list)  # (line_no, msg)


# ---- parse + validate --------------------------------------------------

def parse_jsonl(path: Path) -> list[IngestRow]:
    """Load and validate the JSONL. Raises ValueError with line context on bad rows."""
    rows: list[IngestRow] = []
    with open(path, encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw or raw.startswith("//"):
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as e:
                raise ValueError(f"line {line_no}: invalid JSON: {e}") from None
            if not isinstance(obj, dict):
                raise ValueError(f"line {line_no}: row must be a JSON object")

            # Minimum fields a portable task sink needs.
            if not obj.get("kind"):
                raise ValueError(f"line {line_no}: missing 'kind'")
            if not (obj.get("content") or "").strip():
                raise ValueError(f"line {line_no}: missing/empty 'content'")
            if not (obj.get("project") or obj.get("concept")):
                raise ValueError(f"line {line_no}: must have 'project' xor 'concept'")

            ctx = obj.get("context") or {}
            task_id = ctx.get("task_id") or obj.get("task_id") or f"_anon_{line_no}"
            edges = obj.get("edges") or []
            if not isinstance(edges, list):
                raise ValueError(f"line {line_no}: 'edges' must be a list")
            for e in edges:
                if not isinstance(e, dict) or "type" not in e or "target" not in e:
                    raise ValueError(
                        f"line {line_no}: each edge needs {{type, target}}"
                    )

            rows.append(
                IngestRow(
                    task_id=str(task_id),
                    payload=obj,
                    edges_raw=list(edges),
                    line_no=line_no,
                )
            )

    # Detect duplicate task_ids; ambiguous edge resolution otherwise
    seen: dict[str, int] = {}
    for r in rows:
        if r.task_id in seen and not r.task_id.startswith("_anon_"):
            raise ValueError(
                f"duplicate task_id {r.task_id!r} on lines "
                f"{seen[r.task_id]} and {r.line_no}"
            )
        seen[r.task_id] = r.line_no

    return rows


# ---- pre-topo rewrite --------------------------------------------------

def rewrite_blocks_to_depends_on(rows: list[IngestRow]) -> None:
    """In-place: rewrite each row's `blocks` edges as `depends_on` on the
    target row.

    Why: ingest posts in topo order, so by the time a downstream entry
    is posted, every entry it depends on is already in `id_map` and
    resolves cleanly. Edges that point FORWARD (from upstream to
    downstream) can't be resolved at post time because the downstream
    entry doesn't exist yet. Rewriting `blocks` → `depends_on` flips
    the direction so every dependency edge points BACKWARD.

    Edges to entries outside this batch (ULID targets, or task_ids not in the
    plan) are left as-is — they reference entries already in the sink (or are
    unresolved and will warn at ingest time).

    After this pass, the only edge types that affect topo are
    `depends_on`, `discovered_from`, and `supersedes` — all of which
    point backward.
    """
    by_task = {r.task_id: r for r in rows}
    for r in rows:
        kept: list[dict[str, str]] = []
        for e in r.edges_raw:
            if e.get("type") == "blocks":
                target = e.get("target", "")
                if target in by_task:
                    # In-batch: move as depends_on onto the target row
                    dependent = by_task[target]
                    new_edge = {"type": "depends_on", "target": r.task_id}
                    if new_edge not in dependent.edges_raw:
                        dependent.edges_raw.append(new_edge)
                        payload_edges = list(dependent.payload.get("edges") or [])
                        payload_edges.append(new_edge)
                        dependent.payload["edges"] = payload_edges
                    continue  # don't keep on the blocker
                # External target (ULID or unresolved): leave the blocks
                # edge in place — it expresses a relationship to an entry
                # outside this ingest batch.
            kept.append(e)
        r.edges_raw = kept
        if kept:
            r.payload["edges"] = kept
        else:
            r.payload.pop("edges", None)


# ---- topological sort --------------------------------------------------

def topological_order(rows: list[IngestRow]) -> list[IngestRow]:
    """Return rows ordered so each row's dependencies appear earlier.

    Edge directions (matters!):

      `blocks`        — row.blocks(target): row must come BEFORE target.
                        Note: `ingest()` calls `rewrite_blocks_to_depends_on`
                        before this so blocks edges between in-batch rows
                        have already been flipped. Cross-batch blocks
                        (target is a ULID or unresolved) impose no in-batch
                        ordering.
      `depends_on`    — row.depends_on(target): target must come BEFORE row.
                        After rewrite this is the canonical dependency edge.
      `discovered_from` — target older, target first.
      `supersedes`    — target was the prior version, target first.
      `relates_to`    — symmetric; not ordering.

    Targets that look like ULIDs or aren't in this batch impose no
    ordering — they're already past or out of scope.

    Raises ValueError on a cycle (with the cycle members listed).
    """
    by_task = {r.task_id: r for r in rows}
    in_deg: dict[str, int] = defaultdict(int)
    out_edges: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        for e in r.edges_raw:
            etype = e.get("type")
            target = e.get("target", "")
            if _ULID_RE.match(target):
                continue
            if target not in by_task:
                continue
            if etype == "blocks":
                # Defensive: only fires if rewrite_blocks_to_depends_on
                # wasn't run. Direction: row before target.
                out_edges[r.task_id].append(target)
                in_deg[target] += 1
            elif etype in {"depends_on", "discovered_from", "supersedes"}:
                out_edges[target].append(r.task_id)
                in_deg[r.task_id] += 1
            # relates_to and any unknown type: no ordering imposed
    # Seed in append order so insertion order is stable for ties.
    ready = [r.task_id for r in rows if in_deg[r.task_id] == 0]
    ordered: list[str] = []
    i = 0
    while i < len(ready):
        cur = ready[i]
        i += 1
        ordered.append(cur)
        for child in out_edges.get(cur, []):
            in_deg[child] -= 1
            if in_deg[child] == 0:
                ready.append(child)
    if len(ordered) < len(rows):
        unresolved = [r.task_id for r in rows if r.task_id not in ordered]
        raise ValueError(
            f"cycle detected; cannot order tasks: {unresolved[:6]}"
            + (f" (and {len(unresolved) - 6} more)" if len(unresolved) > 6 else "")
        )
    return [by_task[t] for t in ordered]


# ---- HTTP --------------------------------------------------------------

def _post_register(task_url: str, body: dict) -> dict:
    url = task_url.rstrip("/") + "/register"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _queue_task(body: dict) -> dict:
    p = paths.task_queue_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    entry_id = uuid.uuid4().hex
    rec = {"id": entry_id, **body}
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return {"id": entry_id, "path": str(p)}


def _resolve_edges(
    edges_raw: list[dict[str, str]],
    id_map: dict[str, str],
    *,
    line_no: int,
) -> tuple[list[dict[str, str]], list[str]]:
    """Map task_id targets to entry_id targets using id_map. Pre-existing
    ULIDs pass through unchanged. Returns (resolved_edges, warnings)."""
    resolved: list[dict[str, str]] = []
    warns: list[str] = []
    for e in edges_raw:
        target = e.get("target", "")
        etype = e.get("type")
        if _ULID_RE.match(target):
            resolved.append({"type": etype, "target": target})
            continue
        mapped = id_map.get(target)
        if mapped:
            resolved.append({"type": etype, "target": mapped})
        else:
            warns.append(
                f"line {line_no}: edge target {target!r} not found in plan or as ULID; dropped"
            )
    return resolved, warns


# ---- ingest -----------------------------------------------------------

def ingest(
    rows: list[IngestRow],
    *,
    task_url: str = DEFAULT_TASK_URL,
    dry_run: bool = False,
    strict: bool = False,
    log: bool = True,
    sink=None,
) -> IngestResult:
    """Walk the topo-ordered rows and write each to the configured task sink.

    Returns an IngestResult. On `strict=True`, raises RuntimeError on the
    first sink failure; otherwise records the error and continues.
    """
    rewrite_blocks_to_depends_on(rows)
    ordered = topological_order(rows)
    result = IngestResult()

    for r in ordered:
        edges, warns = _resolve_edges(r.edges_raw, result.id_map, line_no=r.line_no)
        for w in warns:
            if log:
                print(f"[spindle ingest] warn: {w}")

        body = dict(r.payload)
        if edges:
            body["edges"] = edges
        else:
            body.pop("edges", None)
        # Provenance tag — useful for tracing back from a task sink to the plan.
        tags = list(body.get("tags") or [])
        if "spindle-ingest" not in tags:
            tags.append("spindle-ingest")
        body["tags"] = tags
        body.setdefault("session", "spindle-ingest")

        if dry_run:
            if log:
                print(f"[spindle ingest] dry-run line {r.line_no}: would post task_id={r.task_id!r}")
            result.skipped += 1
            # Pretend an entry id so downstream edge resolution can still run
            result.id_map[r.task_id] = f"DRYRUN_{r.line_no:04d}"
            continue

        try:
            if sink is not None:
                resp = sink(body)
            elif task_url:
                resp = _post_register(task_url, body)
            else:
                resp = _queue_task(body)
        except urllib.error.URLError as e:
            msg = f"line {r.line_no}: task sink failed for task_id {r.task_id!r}: {e}"
            result.errors.append((r.line_no, msg))
            result.failed += 1
            if log:
                print(f"[spindle ingest] error: {msg}")
            if strict:
                raise RuntimeError(msg) from e
            continue

        entry_id = resp.get("id")
        if not entry_id:
            msg = f"line {r.line_no}: task sink returned no id; resp={resp!r}"
            result.errors.append((r.line_no, msg))
            result.failed += 1
            if log:
                print(f"[spindle ingest] error: {msg}")
            if strict:
                raise RuntimeError(msg)
            continue

        result.id_map[r.task_id] = entry_id
        result.posted += 1
        if log:
            print(
                f"[spindle ingest] posted line {r.line_no}: task_id={r.task_id!r} → "
                f"entry_id={entry_id} project={body.get('project') or body.get('concept')}"
            )

    return result
