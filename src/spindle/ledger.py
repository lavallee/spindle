"""Append-only event ledger + materialized state for spindle.

Layout under spindle_home() (~/.claude/spindle-state/):
  events.jsonl  — one JSON object per line; never modified, only appended
  state.json    — materialized fold of events.jsonl; rebuilt on demand
  machine.id    — stable UUID for this machine, created on first access
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import InstalledDistributionState, LedgerEvent, MaterializedState
from .paths import events_file, machine_id_file, state_file


def machine_id() -> str:
    """Return the stable UUID for this machine, creating it on first call."""
    mid_path = machine_id_file()
    mid_path.parent.mkdir(parents=True, exist_ok=True)
    if mid_path.exists():
        return mid_path.read_text().strip()
    new_id = str(uuid.uuid4())
    mid_path.write_text(new_id + "\n")
    return new_id


def log_event(kind: str, **payload: Any) -> None:
    """Append a JSON line to events.jsonl."""
    ef = events_file()
    ef.parent.mkdir(parents=True, exist_ok=True)
    event = LedgerEvent(
        ts=datetime.now(timezone.utc).isoformat(),
        machine=machine_id(),
        kind=kind,
        payload=payload,
    )
    line = json.dumps(
        {"ts": event.ts, "machine": event.machine, "kind": event.kind, **event.payload}
    )
    with ef.open("a") as f:
        f.write(line + "\n")


def materialize() -> MaterializedState:
    """Fold events.jsonl into a MaterializedState and persist to state.json."""
    ef = events_file()
    mid = machine_id()
    distributions: dict[str, InstalledDistributionState] = {}
    preempted_by: str | None = None

    if ef.exists():
        for raw_line in ef.read_text().splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                ev = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            kind = ev.get("kind", "")
            if kind == "dist_install":
                name = ev.get("distribution", "")
                if name:
                    distributions[name] = InstalledDistributionState(
                        version=ev.get("version", ""),
                        installed_at=ev.get("ts", ""),
                        packages=ev.get("packages", {}),
                        skills_linked=ev.get("skills_linked", []),
                    )
            elif kind == "dist_uninstall":
                name = ev.get("distribution", "")
                distributions.pop(name, None)
            elif kind == "preempt":
                action = ev.get("action", "")
                dist = ev.get("distribution", "")
                if action == "add":
                    preempted_by = dist
                elif action == "remove":
                    preempted_by = None

    state = MaterializedState(
        machine_id=mid,
        rebuilt_at=datetime.now(timezone.utc).isoformat(),
        distributions=distributions,
        preempted_by=preempted_by,
    )
    _persist_state(state)
    return state


def _persist_state(state: MaterializedState) -> None:
    sf = state_file()
    sf.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "machine_id": state.machine_id,
        "rebuilt_at": state.rebuilt_at,
        "distributions": {
            name: {
                "version": ds.version,
                "installed_at": ds.installed_at,
                "packages": ds.packages,
                "skills_linked": ds.skills_linked,
            }
            for name, ds in state.distributions.items()
        },
        "preempted_by": state.preempted_by,
    }
    sf.write_text(json.dumps(data, indent=2) + "\n")


def show_state() -> MaterializedState:
    """Return materialized state; prefer cached state.json, rebuild if absent."""
    sf = state_file()
    ef = events_file()

    if sf.exists():
        try:
            data = json.loads(sf.read_text())
            state_mtime = sf.stat().st_mtime
            events_mtime = ef.stat().st_mtime if ef.exists() else 0
            if state_mtime >= events_mtime:
                distributions = {
                    name: InstalledDistributionState(
                        version=ds["version"],
                        installed_at=ds["installed_at"],
                        packages=ds.get("packages", {}),
                        skills_linked=ds.get("skills_linked", []),
                    )
                    for name, ds in data.get("distributions", {}).items()
                }
                return MaterializedState(
                    machine_id=data["machine_id"],
                    rebuilt_at=data["rebuilt_at"],
                    distributions=distributions,
                    preempted_by=data.get("preempted_by"),
                )
        except (json.JSONDecodeError, KeyError):
            pass

    return materialize()
