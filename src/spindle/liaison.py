"""The liaison — a surface's standing voice for its own *what*.

Per concept §6b: composition reaches surfaces two ways. The *advance team*
precomputes the common case (the binder, run ahead of time). The *liaison* is the
in-repo edge presence that handles the long tail — the incipient, ad-hoc request no
precompute anticipated. It is thin by design: it owns the **what** (it knows its
own system and can articulate a need + desired outcomes) and defers the **how**
(the actual composition) to Spindle (doctrine P9: consumer owns the what, Spindle owns the
how).

A request the liaison emits is a structured *what-request*: intent + outcomes +
acceptance + the local facts only the in-repo presence can see (its app-class,
language, …). Crucially, every request is logged to a per-surface stream — this is
the **demand signal that feeds the advance team**: today's ad-hoc request becomes
tomorrow's precomputed skill. That stream is the concrete mechanism behind "Spindle
knows the customer better than they do" — it learns from what the liaison had to
handle.

This module gathers + logs. Answering the request (the *how*) is the binder /
advance team; the request is its input.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import appclass as appclass_mod
from . import paths


@dataclass
class WhatRequest:
    """A surface's articulated need. The liaison fills the 'what'; Spindle answers the 'how'."""

    surface: str
    harness: str
    autonomy_mode: str
    intent: str                                     # the ask, in the consumer's words
    desired_outcomes: list[str] = field(default_factory=list)
    acceptance: list[str] = field(default_factory=list)
    local_facts: dict[str, Any] = field(default_factory=dict)  # liaison's self-knowledge
    ts: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WhatRequest":
        return cls(**d)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gather_request(
    repo_path: str | Path,
    intent: str,
    *,
    harness: str = "claude",
    autonomy_mode: str = "deterministic",
    name: str | None = None,
    desired_outcomes: list[str] | None = None,
    acceptance: list[str] | None = None,
    registry_kind: str | None = None,
) -> WhatRequest:
    """Build a what-request, populating local_facts from what the liaison can see
    in-repo (its app-class — the self-knowledge that makes it good at the *what*)."""
    repo_path = Path(repo_path)
    sig = appclass_mod.signal_from_repo(repo_path, registry_kind=registry_kind)
    cls = appclass_mod.classify(sig)
    local_facts = {
        "app_class": cls.cluster_key(),
        "language": cls.language,
        "tags": cls.tags,
        "uses_llms": cls.uses_llms,
        "network_service": cls.network_service,
        "frontend": cls.frontend,
    }
    return WhatRequest(
        surface=name or repo_path.name,
        harness=harness,
        autonomy_mode=autonomy_mode,
        intent=intent.strip(),
        desired_outcomes=list(desired_outcomes or []),
        acceptance=list(acceptance or []),
        local_facts=local_facts,
        ts=_now_iso(),
    )


def gather_agent_request(
    agent_id: str,
    intent: str,
    *,
    harness: str = "claude",
    autonomy_mode: str = "self_evolving",
    desired_outcomes: list[str] | None = None,
    acceptance: list[str] | None = None,
    facts: dict[str, Any] | None = None,
) -> WhatRequest:
    """Build a what-request for an *individual agent* — a surface that isn't a repo.

    The liaison generalizes from repos to agents (concept: "Spindle can/should help
    individual agents acquire skills to perform tasks"). An agent — one of Astrid's
    team, a Collagen persona — owns the same *what* (a task it can't yet do, the
    outcome it needs) but has no repo to classify, so it supplies its own self-
    knowledge directly in ``facts`` instead of ``gather_request`` reading a checkout.
    Agents default to ``self_evolving`` autonomy (they adapt). The resulting
    WhatRequest flows through the identical demand stream + broker as a repo's."""
    return WhatRequest(
        surface=agent_id,
        harness=harness,
        autonomy_mode=autonomy_mode,
        intent=intent.strip(),
        desired_outcomes=list(desired_outcomes or []),
        acceptance=list(acceptance or []),
        local_facts=dict(facts or {}),
        ts=_now_iso(),
    )


def _request_log(surface: str) -> Path:
    return paths.spindle_home() / "requests" / f"{surface}.jsonl"


def log_request(request: WhatRequest) -> Path:
    """Append a what-request to the surface's demand stream (the miss-log that
    feeds the advance team). Append-only JSONL. Returns the log path."""
    p = _request_log(request.surface)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(request.to_dict()) + "\n")
    return p


def read_requests(surface: str) -> list[WhatRequest]:
    """The surface's logged what-requests, oldest first."""
    p = _request_log(surface)
    if not p.exists():
        return []
    out: list[WhatRequest] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(WhatRequest.from_dict(json.loads(line)))
    return out


def answer(request: WhatRequest, repo_path: str | Path, provider, doctrine,
           *, render=None, force: bool = False, dry_run: bool = False):
    """The *how* for a what-request: compose the surface's best current skills.

    The liaison articulates the what; this hands it to Spindle (the binder) to produce
    the how — a coherent, materialized composition for the surface. Note this gives
    the surface its current best set; *synthesizing a new skill* to satisfy a novel
    intent is the advance team's job downstream (the request stays in the demand
    stream for it). Returns the binder's BindResult.
    """
    from . import binder as binder_mod  # local import keeps the edge module light
    from .channels import Surface

    app_class = request.local_facts.get("app_class")
    surface = Surface(
        name=request.surface,
        harness=request.harness,
        autonomy_mode=request.autonomy_mode,
        clusters=(app_class,) if app_class else (),
    )
    kwargs: dict[str, Any] = {"force": force, "dry_run": dry_run}
    if render is not None:
        kwargs["render"] = render
    return binder_mod.bind(surface, repo_path, provider, doctrine, **kwargs)
