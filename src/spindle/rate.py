"""Skill rating — append feedback log + ledger event.

Feedback is stored as append-only markdown under the Spindle state directory.
Every rating also appends a JSON event line to the machine ledger so the machine
can aggregate thumbs-up/down signals across skills over time.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .paths import feedback_dir, ledger_path


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def append_feedback(skill: str, thumbs: str, note: str, *, ts: str | None = None) -> Path:
    """Append one entry to feedback/<skill>.md. Returns the file path."""
    ts = ts or _now_iso()
    direction = "thumbs-up" if thumbs == "up" else "thumbs-down"
    lines = [
        f"## {_today()} — {direction}",
        "",
    ]
    if note:
        lines += [f"> {note}", ""]
    lines += ["---", ""]

    p = feedback_dir() / f"{skill}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return p


def append_ledger(skill: str, thumbs: str, note: str, *, ts: str | None = None) -> Path:
    """Append one rate event to the machine ledger. Returns the file path."""
    ts = ts or _now_iso()
    event = {
        "event": "rate",
        "skill": skill,
        "thumbs": thumbs,
        "note": note,
        "ts": ts,
    }
    p = ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")
    return p


def rate(skill: str, thumbs: str, note: str) -> tuple[Path, Path]:
    """Rate a skill. Returns (feedback_path, ledger_path).

    thumbs must be 'up' or 'down'.
    """
    if thumbs not in ("up", "down"):
        raise ValueError(f"thumbs must be 'up' or 'down', got {thumbs!r}")
    ts = _now_iso()
    fb = append_feedback(skill, thumbs, note, ts=ts)
    ld = append_ledger(skill, thumbs, note, ts=ts)
    return fb, ld
