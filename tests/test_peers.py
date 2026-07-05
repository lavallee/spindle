"""Tests for spindle.peers — list_peers, add, remove, get using active.source_dir()."""

from __future__ import annotations

import spindle.peers as peers_mod
import spindle.active as active_mod


def test_list_peers_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    assert peers_mod.list_peers() == []


def test_add_and_list(tmp_path, monkeypatch):
    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    ok = peers_mod.add(slug="alpha", name="Alpha", url="https://example.com/alpha")
    assert ok is True
    peers = peers_mod.list_peers()
    assert len(peers) == 1
    assert peers[0]["slug"] == "alpha"
    assert peers[0]["url"] == "https://example.com/alpha"


def test_add_duplicate_returns_false(tmp_path, monkeypatch):
    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    peers_mod.add(slug="dup", name="Dup", url="https://example.com")
    ok = peers_mod.add(slug="dup", name="Dup2", url="https://example.com/2")
    assert ok is False
    assert len(peers_mod.list_peers()) == 1


def test_remove_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    peers_mod.add(slug="beta", name="Beta", url="https://example.com/beta")
    ok = peers_mod.remove("beta")
    assert ok is True
    assert peers_mod.list_peers() == []


def test_remove_missing_returns_false(tmp_path, monkeypatch):
    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    assert peers_mod.remove("nonexistent") is False


def test_get_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    peers_mod.add(slug="gamma", name="Gamma", url="https://example.com/gamma")
    p = peers_mod.get("gamma")
    assert p is not None
    assert p["name"] == "Gamma"


def test_get_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    assert peers_mod.get("nope") is None


def test_peers_file_path(tmp_path, monkeypatch):
    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    assert peers_mod._peers_file() == tmp_path / "peers" / "peers.toml"


def test_touch_updates_last_seen(tmp_path, monkeypatch):
    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    peers_mod.add(slug="delta", name="Delta", url="https://example.com/d")
    assert peers_mod.touch("delta", when="2026-05-21") is True
    assert peers_mod.get("delta")["last_seen"] == "2026-05-21"


def test_touch_defaults_to_today(tmp_path, monkeypatch):
    from datetime import date
    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    peers_mod.add(slug="eps", name="Eps", url="https://example.com/e")
    assert peers_mod.touch("eps") is True
    assert peers_mod.get("eps")["last_seen"] == date.today().isoformat()


def test_touch_missing_peer_returns_false(tmp_path, monkeypatch):
    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    assert peers_mod.touch("ghost") is False


def test_touch_preserves_other_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    peers_mod.add(slug="zeta", name="Zeta", url="https://example.com/z",
                  our_take="keep this", notes="and this")
    peers_mod.touch("zeta", when="2026-01-01")
    p = peers_mod.get("zeta")
    assert p["our_take"] == "keep this"
    assert p["notes"] == "and this"
    assert p["name"] == "Zeta"
