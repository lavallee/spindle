"""Tests for spindle.liaison — what-request gathering + the demand-stream log."""

from __future__ import annotations

import spindle.liaison as liaison


def _py_llm_repo(tmp_path):
    repo = tmp_path / "barn-owl"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "barn-owl"\ndependencies = ["anthropic", "fastapi"]\n'
    )
    return repo


def test_gather_request_populates_local_facts(tmp_path):
    repo = _py_llm_repo(tmp_path)
    req = liaison.gather_request(repo, "I need a skill for X",
                                 harness="claude", autonomy_mode="self_evolving",
                                 desired_outcomes=["faster X"], acceptance=["X passes"])
    assert req.surface == "barn-owl"
    assert req.intent == "I need a skill for X"
    assert req.autonomy_mode == "self_evolving"
    assert req.desired_outcomes == ["faster X"]
    # the liaison's self-knowledge: app-class derived locally
    assert req.local_facts["language"] == "python"
    assert req.local_facts["uses_llms"] is True
    assert req.local_facts["network_service"] is True
    assert "uses-llms" in req.local_facts["app_class"]
    assert req.ts  # timestamped


def test_log_and_read_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(liaison.paths, "spindle_home", lambda: tmp_path / "state")
    repo = _py_llm_repo(tmp_path)
    r1 = liaison.gather_request(repo, "first ask")
    r2 = liaison.gather_request(repo, "second ask")
    liaison.log_request(r1)
    liaison.log_request(r2)
    got = liaison.read_requests("barn-owl")
    assert [r.intent for r in got] == ["first ask", "second ask"]  # oldest first
    assert got[0].local_facts["language"] == "python"


def test_read_requests_empty_when_none(tmp_path, monkeypatch):
    monkeypatch.setattr(liaison.paths, "spindle_home", lambda: tmp_path / "state")
    assert liaison.read_requests("never") == []


def test_log_is_append_only_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr(liaison.paths, "spindle_home", lambda: tmp_path / "state")
    repo = _py_llm_repo(tmp_path)
    liaison.log_request(liaison.gather_request(repo, "a"))
    path = liaison.log_request(liaison.gather_request(repo, "b"))
    assert path.read_text().count("\n") == 2  # one JSON object per line


def test_what_request_dict_round_trip(tmp_path):
    repo = _py_llm_repo(tmp_path)
    req = liaison.gather_request(repo, "ask", acceptance=["ok"])
    again = liaison.WhatRequest.from_dict(req.to_dict())
    assert again == req


# ---- answer (the how-response loop) -------------------------------------

def test_answer_binds_surface_via_binder(tmp_path, monkeypatch):
    import spindle.binding as binding_mod
    from spindle.composition import ChannelLayer, ComposedSkill
    from spindle.doctrine import Doctrine
    monkeypatch.setattr(binding_mod.paths, "spindle_home", lambda: tmp_path / "state")

    repo = _py_llm_repo(tmp_path)
    # a skill source for the system channel
    src = tmp_path / "src" / "grill"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text("# grill\n")

    def provider(scope, name, harness):
        if scope == "system":
            return ChannelLayer(scope="system", name="system",
                                skills=[ComposedSkill("grill", "/grill", "system", source_dir=str(src))])
        return None

    req = liaison.gather_request(repo, "need a deploy skill", harness="claude")
    result = liaison.answer(req, repo, provider, Doctrine(version="0.1.0"))
    assert result.ok
    assert (repo / ".claude" / "skills" / "grill").is_symlink()
    # the request carried the surface's app-class through to the binder as a cluster
    assert result.surface == "barn-owl"
