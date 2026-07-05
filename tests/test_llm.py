"""Tests for spindle.llm — offline-safe env-based client construction."""

from __future__ import annotations

import sys
import types

import spindle.llm as llm


def test_from_env_none_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm.from_env() is None


def test_from_env_none_without_sdk(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    # simulate the SDK not being installed
    monkeypatch.setitem(sys.modules, "anthropic", None)
    assert llm.from_env() is None


def test_from_env_builds_callable_and_extracts_text(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    captured = {}

    class _Block:
        def __init__(self, text):
            self.type = "text"
            self.text = text

    class _Resp:
        content = [_Block("rewritten output")]

    class _Messages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _Resp()

    class _Client:
        def __init__(self, api_key=None):
            captured["api_key"] = api_key
            self.messages = _Messages()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Client
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    client = llm.from_env(model="claude-sonnet-4-6")
    assert client is not None
    out = client("rewrite this please", system="be terse")
    assert out == "rewritten output"
    assert captured["model"] == "claude-sonnet-4-6"
    assert captured["api_key"] == "sk-test"
    assert captured["messages"][0]["content"] == "rewrite this please"
    # system prefix sent as a cached block (prompt caching)
    assert captured["system"][0]["text"] == "be terse"
    assert captured["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_from_env_call_without_system_omits_it(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    captured = {}

    class _Resp:
        content = []

    class _Messages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _Resp()

    class _Client:
        def __init__(self, api_key=None):
            self.messages = _Messages()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Client
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    llm.from_env()("just user text")
    assert "system" not in captured  # no empty system block when none given
