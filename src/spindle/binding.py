"""Per-surface binding record + version coordinate — the rollback substrate.

A *binding* is "what is currently composed onto this surface": the resolved
skills, the doctrine + channel versions that produced them, and a coordinate that
identifies the exact composition. Recording it is the prerequisite for rollback
(eng-review #7): to roll a surface back you re-bind it to a prior coordinate, so
there must be a per-surface store of what was bound and when.

Stored as one JSON file per surface under ``spindle_home()/bindings/<surface>.json``,
append-friendly: each bind writes a new record and keeps the prior ones as history
so a rollback target is always retrievable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import paths
from .composition import Composition


@dataclass(frozen=True)
class BindingRecord:
    surface: str
    coordinate: str            # the composition coordinate (see compute_coordinate)
    doctrine_coordinate: str   # doctrine version+hash this bind used
    skills: list[str]          # skill names materialized, sorted
    channel_versions: dict[str, str]  # channel id -> version that fed this bind
    bound_at: str              # ISO 8601 UTC
    evaluation_receipt_id: str | None = None
    origin: dict[str, str] | None = None
    evaluation_tuple: dict[str, str] | None = None
    baseline_tuple: dict[str, str] | None = None


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_coordinate(comp: Composition, *, doctrine_coordinate: str,
                       channel_versions: dict[str, str]) -> str:
    """A stable coordinate identifying this exact composition.

    Hashes the resolved skill set + the doctrine coordinate + per-channel versions,
    so the same inputs always yield the same coordinate (a rebind is a no-op) and
    any change (new skill, bumped channel, doctrine edit) yields a new one. Form:
    ``<short-hash>`` — the resolvable address a rollback re-pins to.
    """
    payload = {
        "skills": sorted(s.name for s in comp.skills),
        "doctrine": doctrine_coordinate,
        "channels": dict(sorted(channel_versions.items())),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def _binding_file(surface: str) -> Path:
    return paths.spindle_home() / "bindings" / f"{surface}.json"


def record_binding(comp: Composition, *, doctrine_coordinate: str,
                   channel_versions: dict[str, str],
                   evaluation_receipt_id: str | None = None,
                   origin: dict[str, str] | None = None,
                   evaluation_tuple: dict[str, str] | None = None,
                   baseline_tuple: dict[str, str] | None = None) -> BindingRecord:
    """Append a binding record for ``comp.surface`` and return it.

    History is preserved (prior records kept) so any earlier coordinate stays a
    valid rollback target.
    """
    coord = compute_coordinate(comp, doctrine_coordinate=doctrine_coordinate,
                               channel_versions=channel_versions)
    rec = BindingRecord(
        surface=comp.surface,
        coordinate=coord,
        doctrine_coordinate=doctrine_coordinate,
        skills=sorted(s.name for s in comp.skills),
        channel_versions=dict(channel_versions),
        bound_at=_now_iso(),
        evaluation_receipt_id=evaluation_receipt_id,
        origin=dict(origin) if origin is not None else None,
        evaluation_tuple=dict(evaluation_tuple) if evaluation_tuple is not None else None,
        baseline_tuple=dict(baseline_tuple) if baseline_tuple is not None else None,
    )
    p = _binding_file(comp.surface)
    p.parent.mkdir(parents=True, exist_ok=True)
    history = _read_history(comp.surface)
    history.append(rec)
    p.write_text(json.dumps([asdict(r) for r in history], indent=2) + "\n", encoding="utf-8")
    return rec


def record_evaluated_binding(
    comp: Composition,
    *,
    doctrine_coordinate: str,
    channel_versions: dict[str, str],
    evaluation_receipt: dict,
) -> BindingRecord:
    """Bind an eligible procedure while preserving its exact evaluation custody."""

    promotion = evaluation_receipt.get("promotion")
    if not isinstance(promotion, dict) or promotion.get("eligible") is not True:
        raise ValueError("evaluated binding requires an eligible promotion decision")
    receipt_id = evaluation_receipt.get("receipt_id")
    origin = evaluation_receipt.get("origin")
    evaluation_tuple = evaluation_receipt.get("evaluation_tuple")
    baseline_tuple = evaluation_receipt.get("baseline_tuple")
    if not isinstance(receipt_id, str) or not receipt_id:
        raise ValueError("evaluated binding requires an evaluation receipt id")
    if not all(isinstance(value, dict) and value for value in (
        origin, evaluation_tuple, baseline_tuple
    )):
        raise ValueError("evaluated binding requires origin and exact baseline/variant tuples")
    return record_binding(
        comp,
        doctrine_coordinate=doctrine_coordinate,
        channel_versions=channel_versions,
        evaluation_receipt_id=receipt_id,
        origin=origin,
        evaluation_tuple=evaluation_tuple,
        baseline_tuple=baseline_tuple,
    )


def _read_history(surface: str) -> list[BindingRecord]:
    p = _binding_file(surface)
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    return [BindingRecord(**r) for r in raw]


def current_binding(surface: str) -> BindingRecord | None:
    """The most recent binding for a surface, or None if never bound."""
    history = _read_history(surface)
    return history[-1] if history else None


def find_coordinate(surface: str, coordinate: str) -> BindingRecord | None:
    """Look up a prior binding by coordinate — the rollback target lookup."""
    for rec in reversed(_read_history(surface)):
        if rec.coordinate == coordinate:
            return rec
    return None
