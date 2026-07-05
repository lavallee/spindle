"""Tests for the marketplace facade — roster search, broker ranking, acquisition
ledger, and the agent-generalized liaison. All offline: providers are injected
fakes, so no subprocess/network runs."""

from __future__ import annotations

from pathlib import Path

import spindle.broker as broker
import spindle.liaison as liaison
import spindle.roster as roster
from spindle.roster import SkillCandidate


# ---- fixtures: a fake roster + provider ---------------------------------

SOURCES = [
    {"slug": "npx-skills", "name": "npx skills", "kind": "npx", "enabled": True},
    {"slug": "disabled", "name": "off", "kind": "npx", "enabled": False},
]

CATALOG = [
    SkillCandidate(id="pg-migrate", source="npx-skills", title="Postgres migration helper",
                   description="run and verify database migrations", install_ref="npx:pgm",
                   tags=("postgres", "migration", "database")),
    SkillCandidate(id="lint-fix", source="npx-skills", title="Lint autofixer",
                   description="format and fix lint", install_ref="npx:lf", tags=("lint",)),
]


def fake_provider(query, local_facts, source):
    # naive substring search over title/description/tags — stands in for `npx skills`
    q = query.lower()
    return [c for c in CATALOG
            if q in c.title.lower() or q in c.description.lower()
            or any(q in t for t in c.tags)
            or any(w in (c.title + c.description + " ".join(c.tags)).lower()
                   for w in q.split())]


PROVIDERS = {"npx": fake_provider}


def _req(intent, outcomes=None, tags=None):
    return liaison.WhatRequest(
        surface="barn-owl", harness="claude", autonomy_mode="self_evolving",
        intent=intent, desired_outcomes=outcomes or [],
        local_facts={"tags": tags or []}, ts="2026-06-11T00:00:00Z",
    )


# ---- roster search ------------------------------------------------------

def test_search_roster_uses_only_enabled_sources():
    # both sources are kind=npx, but the search is given the full list incl. disabled;
    # passing enabled-only sources is the loader's job — here we pass explicit sources
    cands = roster.search_roster("migration", providers=PROVIDERS,
                                 sources=[s for s in SOURCES if s["enabled"]])
    assert any(c.id == "pg-migrate" for c in cands)


def test_search_roster_swallows_provider_errors():
    def boom(q, f, s):
        raise RuntimeError("upstream down")
    cands = roster.search_roster("x", providers={"npx": boom}, sources=SOURCES[:1])
    assert cands == []  # one bad source never breaks the search


def test_search_roster_skips_kinds_without_provider():
    cands = roster.search_roster("migration", providers={}, sources=SOURCES[:1])
    assert cands == []


def test_list_sources_reads_shipped_roster():
    sample = Path(__file__).resolve().parents[1] / "examples" / "spindle-sample"
    srcs = roster.list_sources(source_dir=sample)
    slugs = {s["slug"] for s in srcs}
    assert slugs == {"local"}
    # shipped sources are disabled by default (live = opt-in)
    assert roster.list_sources(source_dir=sample, enabled_only=True) == []


# ---- fit scoring --------------------------------------------------------

def test_score_fit_ranks_relevant_higher():
    req = _req("help me run a postgres migration", tags=["database"])
    good = broker.score_fit(req, CATALOG[0])   # migration helper
    bad = broker.score_fit(req, CATALOG[1])    # lint
    assert good > bad
    assert 0.0 <= bad <= good <= 1.0


def test_score_fit_zero_when_no_request_words():
    req = _req("")  # nothing to match
    assert broker.score_fit(req, CATALOG[0]) == 0.0


def test_score_fit_ignores_stopwords():
    # an all-stopword request shouldn't spuriously match
    req = _req("i need a skill to the for")
    assert broker.score_fit(req, CATALOG[1]) == 0.0


# ---- broker ranking -----------------------------------------------------

def test_broker_proposes_ranked_not_installed():
    req = _req("postgres migration", tags=["database"])
    props = broker.broker(req, providers=PROVIDERS, sources=SOURCES[:1])
    assert props, "expected at least one proposal"
    assert props[0].candidate.id == "pg-migrate"
    assert all(p.status == "proposed" for p in props)        # never auto-installs
    # deterministic order: fit desc
    fits = [p.fit for p in props]
    assert fits == sorted(fits, reverse=True)


def test_broker_min_fit_filters():
    req = _req("postgres migration", tags=["database"])
    # fit is capped at 1.0, so an above-ceiling bar drops everything
    high = broker.broker(req, providers=PROVIDERS, sources=SOURCES[:1], min_fit=1.1)
    assert high == []
    # and the same request with no floor returns the strong match
    assert broker.broker(req, providers=PROVIDERS, sources=SOURCES[:1])[0].fit == 1.0


def test_broker_limit_caps_results():
    req = _req("fix lint and run migration")
    props = broker.broker(req, providers=PROVIDERS, sources=SOURCES[:1], limit=1)
    assert len(props) == 1


# ---- acquisition + the outcome ledger -----------------------------------

def test_acquire_records_and_marks(tmp_path, monkeypatch):
    monkeypatch.setattr(broker.paths, "spindle_home", lambda: tmp_path)
    req = _req("postgres migration", tags=["database"])
    prop = broker.broker(req, providers=PROVIDERS, sources=SOURCES[:1])[0]
    acq = broker.acquire(prop)
    assert acq.status == "acquired"
    assert acq.provenance.get("transposed") is False        # stub transpose
    recs = broker.read_acquisitions()
    assert len(recs) == 1
    assert recs[0]["candidate"]["id"] == "pg-migrate"
    assert recs[0]["status"] == "acquired"


def test_record_acquisition_carries_worked_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(broker.paths, "spindle_home", lambda: tmp_path)
    req = _req("lint")
    prop = broker.broker(req, providers=PROVIDERS, sources=SOURCES[:1])[0]
    broker.record_acquisition(prop, worked=True)
    recs = broker.read_acquisitions()
    assert recs[0]["worked"] is True


def test_custom_transpose_hook_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(broker.paths, "spindle_home", lambda: tmp_path)
    req = _req("postgres migration", tags=["database"])
    prop = broker.broker(req, providers=PROVIDERS, sources=SOURCES[:1])[0]

    def transpose(a):
        a.provenance = {**a.provenance, "transposed": True, "transpose": "doctrine-v0"}
        return a

    acq = broker.acquire(prop, transpose=transpose)
    assert acq.provenance["transposed"] is True
    assert broker.read_acquisitions()[0]["provenance"]["transpose"] == "doctrine-v0"


# ---- the agent-generalized liaison --------------------------------------

def test_gather_agent_request_no_repo():
    req = liaison.gather_agent_request(
        "astrid-managing-editor", "I need to grade research provenance",
        facts={"role": "managing-editor", "tags": ["editorial"]},
    )
    assert req.surface == "astrid-managing-editor"
    assert req.autonomy_mode == "self_evolving"              # agents adapt by default
    assert req.local_facts["role"] == "managing-editor"
    assert req.ts  # stamped


def test_agent_request_flows_through_broker():
    # an individual agent's what-request brokers identically to a repo's
    req = liaison.gather_agent_request(
        "collagen-vera", "find a postgres migration skill",
        facts={"tags": ["database"]},
    )
    props = broker.broker(req, providers=PROVIDERS, sources=SOURCES[:1])
    assert props and props[0].candidate.id == "pg-migrate"
