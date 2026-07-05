"""The broker — the *how* for a cache-miss that needs an EXTERNAL skill.

The liaison owns the *what* (a ``WhatRequest``); the binder answers it from the
factory's own skills. When nothing internal fits, the broker is Spindle acting as a
**facade over the skill marketplace**: search the roster, rank candidates by fit,
and — critically — record the outcome so cross-program lessons accrue (concept:
"keep track of what works and what doesn't … cross-program lessons compound").

Three deliberate boundaries:

  - **Propose, don't auto-install** (doctrine P7/P8: flag for a decision, don't
    auto-close). ``broker()`` ranks; ``acquire()`` is the explicit act of bringing
    a candidate in, gated by autonomy mode at the call site.
  - **Transpose, don't copy** (the load-bearing word from the doctrine). Acquisition
    runs the candidate through an injectable ``transpose`` hook so an external skill
    lands as creole through Spindle's doctrine, not as a foreign body. The default hook
    is a pass-through stub; the real doctrine-rendering transpose wires in later.
  - **Scoring is pure + deterministic.** Keyword/tag overlap today; an LLM-judge
    layer can rank on top via an injected scorer, same as the dialect/llm seam.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import paths
from .liaison import WhatRequest
from .roster import SearchProvider, SkillCandidate, search_roster

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(*texts: str) -> set[str]:
    out: set[str] = set()
    for t in texts:
        out.update(_WORD_RE.findall(t.lower()))
    return out


# Very short, near-universal tokens carry no signal — don't let them inflate fit.
_STOP = frozenset({"a", "an", "the", "to", "of", "for", "and", "or", "with", "in",
                   "on", "is", "it", "skill", "that", "this", "i", "we", "need"})


def score_fit(request: WhatRequest, cand: SkillCandidate) -> float:
    """Deterministic fit in [0, 1]: Jaccard-ish overlap of the request's words
    (intent + outcomes + app-class tags) against the candidate's (title +
    description + tags), title/tag matches weighted up. Pure; no I/O."""
    req = _tokens(request.intent, *request.desired_outcomes,
                 *[str(v) for v in request.local_facts.get("tags", [])]) - _STOP
    strong = _tokens(cand.title, *cand.tags) - _STOP          # title/tags = strong signal
    weak = _tokens(cand.description) - _STOP
    if not req:
        return 0.0
    hits = len(req & strong) * 2 + len(req & weak)
    denom = len(req) * 2  # normalize against the strong-weighted ceiling
    return min(1.0, hits / denom) if denom else 0.0


@dataclass
class Acquisition:
    """A ranked external candidate for a what-request, with provenance + status."""

    request_surface: str
    request_intent: str
    candidate: SkillCandidate
    fit: float
    status: str = "proposed"        # proposed | acquired | rejected
    provenance: dict[str, Any] = field(default_factory=dict)
    ts: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["candidate"] = asdict(self.candidate)
        return d


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def broker(
    request: WhatRequest,
    *,
    providers: dict[str, SearchProvider],
    source_dir: Path | None = None,
    sources: list[dict] | None = None,
    limit: int = 3,
    min_fit: float = 0.0,
) -> list[Acquisition]:
    """Search the roster for the request, rank candidates by fit, return the top-N
    as *proposals* (status=proposed). Does NOT install — acquisition is a separate,
    explicit act (P7/P8). Deterministic order: fit desc, then candidate id."""
    cands = search_roster(request.intent, request.local_facts,
                          providers=providers, source_dir=source_dir, sources=sources)
    scored = [
        Acquisition(
            request_surface=request.surface,
            request_intent=request.intent,
            candidate=c,
            fit=round(score_fit(request, c), 4),
            provenance={"source": c.source, "install_ref": c.install_ref},
            ts=request.ts or _now_iso(),
        )
        for c in cands
    ]
    scored = [a for a in scored if a.fit >= min_fit]
    scored.sort(key=lambda a: (-a.fit, a.candidate.id))
    return scored[:limit]


# A transpose hook turns an external candidate into spindle-coherent material. Default is
# a recorded pass-through stub; the real doctrine-rendering transpose wires in later.
TransposeFn = Callable[[Acquisition], Acquisition]


def _identity_transpose(acq: Acquisition) -> Acquisition:
    acq.provenance = {**acq.provenance, "transposed": False, "transpose": "stub"}
    return acq


def acquire(
    acquisition: Acquisition,
    *,
    transpose: TransposeFn = _identity_transpose,
    record: bool = True,
) -> Acquisition:
    """Bring a proposed candidate in: transpose it through Spindle's idioms, mark it
    acquired, and record the outcome to the acquisitions ledger. Reversible by
    construction (a skill install can be unbound), so a self-evolving surface may do
    this within its guardrails; a deterministic one defers the decision upward."""
    acquisition = transpose(acquisition)
    acquisition.status = "acquired"
    acquisition.ts = _now_iso()
    if record:
        record_acquisition(acquisition)
    return acquisition


# ---- the outcome ledger (cross-program lessons accrue here) --------------

def acquisitions_log() -> Path:
    return paths.spindle_home() / "acquisitions.jsonl"


def record_acquisition(acquisition: Acquisition, *, worked: bool | None = None) -> Path:
    """Append an acquisition outcome to the ledger. ``worked`` is the after-the-fact
    signal (None until rated) — this is the "track what works" half of the facade, so
    a future request for the same intent can prefer what landed well."""
    p = acquisitions_log()
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = acquisition.to_dict()
    if worked is not None:
        rec["worked"] = worked
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return p


def read_acquisitions() -> list[dict]:
    """All recorded acquisition outcomes, oldest first."""
    p = acquisitions_log()
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out
