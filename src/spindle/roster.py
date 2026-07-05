"""The roster — the marketplace facade's source list.

When a what-request is a *cache miss* that no internal composition answers, the
right skill may live OUTSIDE the factory: a published pack on ``npx skills``, an
open-source skill someone shipped last week, a community technique. The roster is
the registry of those upstream *sources* and the search seam over them (concept:
"Spindle as a facade for services like npx skills — pull from a roster of upstream
capabilities that fit the bill, and keep track of what works").

Shape mirrors ``peers.py``: one hand-editable TOML
(``<source_dir>/roster/sources.toml``) with a flat list of ``[[source]]`` entries.
Searching a source is delegated to an **injectable provider** keyed by the source's
``kind`` — so the network/subprocess lives behind a seam (offline tests inject a
fake; the CLI wires the live ``npx``/``find-skills`` providers). A source with no
provider, or one that errors, simply yields no candidates — never breaks the search.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from . import active as active_mod


@dataclass(frozen=True)
class SkillCandidate:
    """One upstream skill the roster surfaced for a query."""

    id: str                                   # stable-ish id within its source
    source: str                               # roster source slug
    title: str
    description: str = ""
    install_ref: str = ""                     # how to fetch (npx pkg, git url, …)
    tags: tuple[str, ...] = ()


# A provider searches ONE source for a query: (query, local_facts, source) -> cands.
SearchProvider = Callable[[str, dict, dict], list[SkillCandidate]]


def sources_file(source_dir: Path | None = None) -> Path:
    root = Path(source_dir) if source_dir is not None else active_mod.source_dir()
    return root / "roster" / "sources.toml"


def list_sources(source_dir: Path | None = None, *, enabled_only: bool = False) -> list[dict]:
    """The roster's source entries (dicts: slug, name, kind, command/url, enabled, notes)."""
    p = sources_file(source_dir)
    if not p.exists():
        return []
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    out = list(data.get("source", []))
    if enabled_only:
        out = [s for s in out if s.get("enabled", False)]
    return out


def search_roster(
    query: str,
    local_facts: dict | None = None,
    *,
    providers: dict[str, SearchProvider],
    source_dir: Path | None = None,
    sources: list[dict] | None = None,
) -> list[SkillCandidate]:
    """Search every enabled source whose ``kind`` has a provider; concat the results.

    ``providers`` maps a source ``kind`` to its search provider — injected, so the
    search is offline by default (empty providers → no candidates) and the live
    subprocess providers are supplied by the caller. A provider that raises is
    swallowed (the source yields nothing); one bad source never fails the search.
    """
    local_facts = local_facts or {}
    srcs = sources if sources is not None else list_sources(source_dir, enabled_only=True)
    out: list[SkillCandidate] = []
    for src in srcs:
        provider = providers.get(str(src.get("kind", "")))
        if provider is None:
            continue
        try:
            out.extend(provider(query, local_facts, src))
        except Exception:
            # A flaky/missing upstream source must not break acquisition. (A2-aligned:
            # we don't fabricate results; we just report none from this source.)
            continue
    return out


# ---- live providers (wired by the CLI; not exercised by offline tests) ----

def _run_json(cmd: list[str], *, timeout: int = 30) -> Optional[object]:
    """Run a command and parse stdout as JSON; None on any failure (fail-safe)."""
    try:  # pragma: no cover - subprocess seam, fake-tested via injection
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        return json.loads(proc.stdout)
    except Exception:
        return None


def npx_skills_provider(query: str, local_facts: dict, source: dict) -> list[SkillCandidate]:  # pragma: no cover
    """Search ``npx skills`` (or the command in the source). Fail-safe: [] on error."""
    base = str(source.get("command", "npx skills")).split()
    data = _run_json(base + ["search", query, "--json"])
    if not isinstance(data, list):
        return []
    cands: list[SkillCandidate] = []
    for d in data:
        if not isinstance(d, dict):
            continue
        cands.append(SkillCandidate(
            id=str(d.get("id") or d.get("name", "")),
            source=str(source.get("slug", "npx")),
            title=str(d.get("name") or d.get("title", "")),
            description=str(d.get("description", "")),
            install_ref=str(d.get("install") or d.get("ref", "")),
            tags=tuple(str(t) for t in d.get("tags", [])),
        ))
    return cands


def live_providers() -> dict[str, SearchProvider]:  # pragma: no cover - wiring only
    """The default live provider registry the CLI supplies to ``search_roster``."""
    return {"npx": npx_skills_provider}
