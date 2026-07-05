"""File doctrine decision gates into a pluggable queue.

When the ingest dialectic diverges on a relevant change, the adjudicator
pre-digests it into {crux, doctrine diff, pilot}. Spindle records that as a
decision gate for a human to ratify/reject.

The public reference implementation writes JSONL to ``SPINDLE_GATE_QUEUE`` or
``$SPINDLE_HOME/gates.jsonl``. Private deployments can inject a different
``SinkFn`` that forwards the same body to their own task or steering system.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, Callable
from datetime import datetime, timezone

from . import paths

STEERING_TAG = "needs:human"
GATE_TAG = "spindle:doctrine"

SinkFn = Callable[[dict], dict]


def build_gate_body(
    *,
    crux: str,
    proposed_diff: str = "",
    pilot: str = "",
    source: str = "",
    project: str = "spindle",
) -> dict[str, Any]:
    """Assemble the portable decision-gate body.

    The crux is the headline (`content`); the diff/pilot/source ride in `context`
    so a human queue gets the whole ratifiable decision in one place.
    """
    content = crux.strip() or "(doctrine adjudication — no crux given)"
    context: dict[str, Any] = {"gate": True}
    if proposed_diff:
        context["proposed_diff"] = proposed_diff
    if pilot:
        context["pilot"] = pilot
    if source:
        context["source"] = source
    return {
        "kind": "decision",
        "project": project,
        "content": content,
        "tags": [STEERING_TAG, GATE_TAG],
        "context": context,
        "session": "spindle-dialectic",
    }


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_jsonl(body: dict) -> dict:
    p = paths.gate_queue_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"id": uuid.uuid4().hex, "ts": _now_iso(), **body}
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return {"id": rec["id"], "path": str(p)}


_YAML_BLOCK_RE = re.compile(r"```ya?ml\s*\n(.*?)```", re.DOTALL)
_ADJUDICATION_KEYS = ("crux", "proposed_diff", "pilot", "recommendation", "source")


def parse_adjudication(text: str) -> dict[str, str]:
    """Extract {crux, proposed_diff, pilot, …} from an adjudicate-pass report.

    Accepts a fenced ```yaml block (the adjudicate-pass output footer) or loose
    ``key: value`` lines. Returns only the keys it found.
    """
    m = _YAML_BLOCK_RE.search(text)
    body = m.group(1) if m else text
    fields: dict[str, str] = {}
    for line in body.splitlines():
        stripped = line.strip()
        for key in _ADJUDICATION_KEYS:
            if stripped.startswith(key + ":"):
                fields[key] = stripped.split(":", 1)[1].strip().strip('"').strip("'")
    return fields


def file_from_result(
    result_file: str | Path,
    *,
    dry_run: bool = False,
    sink: SinkFn | None = None,
) -> dict[str, Any]:
    """Parse an adjudicate-pass result file (JSON or plain md) and file the gate.

    Mirrors ``scout --apply-results``: the file is JSON ``{"output": "<report>"}``
    or plain markdown. Returns ``{"error": ...}`` if no crux is found.
    """
    raw = Path(result_file).read_text(encoding="utf-8")
    try:
        obj = json.loads(raw)
        report = obj.get("output") or obj.get("result") or raw
    except (json.JSONDecodeError, TypeError):
        report = raw
    fields = parse_adjudication(report)
    if not fields.get("crux"):
        return {"error": "no crux found in adjudication result"}
    return file_gate(
        crux=fields["crux"],
        proposed_diff=fields.get("proposed_diff", ""),
        pilot=fields.get("pilot", ""),
        source=fields.get("source", ""),
        dry_run=dry_run, sink=sink,
    )


def file_gate(
    *,
    crux: str,
    proposed_diff: str = "",
    pilot: str = "",
    source: str = "",
    dry_run: bool = False,
    sink: SinkFn | None = None,
) -> dict[str, Any]:
    """File a doctrine gate.

    ``sink`` is injectable so private layers can forward the same portable body to
    a service. The default public sink appends JSONL locally.
    """
    body = build_gate_body(crux=crux, proposed_diff=proposed_diff, pilot=pilot, source=source)
    if dry_run:
        return {"dry_run": body}
    writer = sink or _write_jsonl
    return writer(body)
