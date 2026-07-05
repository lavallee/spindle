"""Doctrine — the coherent first-principles set, as a versioned artifact.

The doctrine is what skills are generated from and checked against (see
``plans/spindle-evolution/concept.md``). It lives as a structured TOML under the
active distribution (``<source_dir>/doctrine/doctrine.toml``) so it is
hand-editable, version-controlled, and machine-readable. This module is the
platform reader: parse → validate → query → version-coordinate. Pure of network
and subprocess; reads one file.

Shape (FC-1: absoluteness is a spectrum across scopes):
  preference     — "favor X over Y", scoped, with provenance
  absolute       — ALWAYS/NEVER, scoped, rare; density highest at `system`
  meta_principle — governs how other principles are written (M1, M2)
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from . import active as active_mod

SCOPES = ("system", "cluster", "repo")
MODES = ("ALWAYS", "NEVER")


@dataclass(frozen=True)
class Preference:
    id: str
    scope: str
    favor: str
    over: str
    note: str = ""
    provenance: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Absolute:
    id: str
    scope: str
    mode: str  # ALWAYS | NEVER
    statement: str
    provenance: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MetaPrinciple:
    id: str
    statement: str


@dataclass
class Doctrine:
    version: str
    preferences: list[Preference] = field(default_factory=list)
    absolutes: list[Absolute] = field(default_factory=list)
    meta_principles: list[MetaPrinciple] = field(default_factory=list)
    source_hash: str = ""  # sha256 of the raw doctrine.toml — the version coordinate

    # ---- queries -------------------------------------------------------

    def get(self, entry_id: str) -> Preference | Absolute | MetaPrinciple | None:
        for coll in (self.preferences, self.absolutes, self.meta_principles):
            for e in coll:
                if e.id == entry_id:
                    return e
        return None

    def preferences_for_scope(self, scope: str) -> list[Preference]:
        return [p for p in self.preferences if p.scope == scope]

    def absolutes_for_scope(self, scope: str) -> list[Absolute]:
        return [a for a in self.absolutes if a.scope == scope]

    def coordinate(self) -> str:
        """Resolvable version coordinate: ``<version>+<short-hash>``.

        Pairs a human semver with a content hash so a binding can pin an exact
        doctrine and a rollback can re-fetch it (concept §6 version-coordinate).
        """
        short = self.source_hash[:12] if self.source_hash else "nohash"
        return f"{self.version}+{short}"


def doctrine_file() -> Path:
    return active_mod.source_dir() / "doctrine" / "doctrine.toml"


def _coerce_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    return [str(x) for x in v]


def load(path: Path | None = None) -> Doctrine:
    """Load and structure the doctrine. Does not validate — call ``validate``.

    Raises FileNotFoundError if the doctrine file is absent.
    """
    p = path or doctrine_file()
    raw = p.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    source_hash = hashlib.sha256(raw).hexdigest()

    prefs = [
        Preference(
            id=str(d.get("id", "")),
            scope=str(d.get("scope", "")),
            favor=str(d.get("favor", "")),
            over=str(d.get("over", "")),
            note=str(d.get("note", "")),
            provenance=_coerce_list(d.get("provenance")),
        )
        for d in data.get("preference", [])
    ]
    absos = [
        Absolute(
            id=str(d.get("id", "")),
            scope=str(d.get("scope", "")),
            mode=str(d.get("mode", "")),
            statement=str(d.get("statement", "")),
            provenance=_coerce_list(d.get("provenance")),
        )
        for d in data.get("absolute", [])
    ]
    metas = [
        MetaPrinciple(id=str(d.get("id", "")), statement=str(d.get("statement", "")))
        for d in data.get("meta_principle", [])
    ]
    return Doctrine(
        version=str(data.get("version", "")),
        preferences=prefs,
        absolutes=absos,
        meta_principles=metas,
        source_hash=source_hash,
    )


def validate(doc: Doctrine) -> list[str]:
    """Return a list of problems; empty means the doctrine is well-formed.

    Checks: a version is present; ids are globally unique; scopes and absolute
    modes are from the controlled vocabulary; preferences/absolutes carry their
    required text. This is the compose-time gate's first cousin — a doctrine that
    doesn't pass here should never render into skills.
    """
    problems: list[str] = []
    if not doc.version:
        problems.append("missing version")

    seen: dict[str, str] = {}
    everything = (
        [("preference", p.id) for p in doc.preferences]
        + [("absolute", a.id) for a in doc.absolutes]
        + [("meta_principle", m.id) for m in doc.meta_principles]
    )
    for kind, eid in everything:
        if not eid:
            problems.append(f"{kind}: entry with empty id")
            continue
        if eid in seen:
            problems.append(f"duplicate id {eid!r} ({seen[eid]} and {kind})")
        seen[eid] = kind

    for p in doc.preferences:
        if p.scope not in SCOPES:
            problems.append(f"{p.id}: bad scope {p.scope!r} (want one of {SCOPES})")
        if not p.favor or not p.over:
            problems.append(f"{p.id}: preference needs both 'favor' and 'over'")
    for a in doc.absolutes:
        if a.scope not in SCOPES:
            problems.append(f"{a.id}: bad scope {a.scope!r} (want one of {SCOPES})")
        if a.mode not in MODES:
            problems.append(f"{a.id}: bad mode {a.mode!r} (want one of {MODES})")
        if not a.statement:
            problems.append(f"{a.id}: absolute needs a 'statement'")
    for m in doc.meta_principles:
        if not m.statement:
            problems.append(f"{m.id}: meta_principle needs a 'statement'")
    return problems
