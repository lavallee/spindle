"""Tests for spindle.active — resolution order and integration with peers/verdicts/scout."""

from __future__ import annotations

from pathlib import Path

import pytest

import spindle.active as active_mod
from spindle.active import ANONYMOUS, ActiveDistributionError
from spindle.models import DistributionMetadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_meta(name: str, source_dir: Path) -> DistributionMetadata:
    return DistributionMetadata(
        name=name,
        version="0.1.0",
        display_name=name,
        description="",
        source_dir=source_dir,
        preempt_snippet=None,
        home_url=None,
        packages=[],
    )


# ---------------------------------------------------------------------------
# Priority 1: SPINDLE_ACTIVE_DIST_DIR env var
# ---------------------------------------------------------------------------

def test_dist_dir_env_returns_anonymous(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLE_ACTIVE_DIST_DIR", str(tmp_path))
    assert active_mod.active_distribution() == ANONYMOUS


def test_dist_dir_env_source_dir_returns_path(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLE_ACTIVE_DIST_DIR", str(tmp_path))
    assert active_mod.source_dir() == tmp_path


def test_dist_dir_env_beats_name_env(tmp_path, monkeypatch):
    """SPINDLE_ACTIVE_DIST_DIR wins even when SPINDLE_ACTIVE_DIST_NAME is also set."""
    monkeypatch.setenv("SPINDLE_ACTIVE_DIST_DIR", str(tmp_path))
    monkeypatch.setenv("SPINDLE_ACTIVE_DIST_NAME", "some-dist")
    assert active_mod.active_distribution() == ANONYMOUS


# ---------------------------------------------------------------------------
# Priority 2: SPINDLE_ACTIVE_DIST_NAME env var
# ---------------------------------------------------------------------------

def test_dist_name_env_returns_name(tmp_path, monkeypatch):
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_DIR", raising=False)
    monkeypatch.setenv("SPINDLE_ACTIVE_DIST_NAME", "my-dist")
    meta = _make_meta("my-dist", tmp_path)
    monkeypatch.setattr(active_mod, "read_distribution_metadata", lambda n: meta if n == "my-dist" else None)
    assert active_mod.active_distribution() == "my-dist"


def test_dist_name_env_not_installed_raises(monkeypatch):
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_DIR", raising=False)
    monkeypatch.setenv("SPINDLE_ACTIVE_DIST_NAME", "missing-dist")
    monkeypatch.setattr(active_mod, "read_distribution_metadata", lambda n: None)
    with pytest.raises(ActiveDistributionError, match="not an installed distribution"):
        active_mod.active_distribution()


def test_dist_name_env_beats_pointer(tmp_path, monkeypatch):
    """SPINDLE_ACTIVE_DIST_NAME wins over the pointer file."""
    # Set up a pointer file pointing to "other-dist"
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path))
    pointer = tmp_path / "active"
    pointer.write_text("other-dist\n")

    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_DIR", raising=False)
    monkeypatch.setenv("SPINDLE_ACTIVE_DIST_NAME", "env-dist")
    meta = _make_meta("env-dist", tmp_path)
    monkeypatch.setattr(active_mod, "read_distribution_metadata", lambda n: meta if n == "env-dist" else None)
    assert active_mod.active_distribution() == "env-dist"


# ---------------------------------------------------------------------------
# Priority 3: pointer file
# ---------------------------------------------------------------------------

def test_pointer_file_returns_name(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path))
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_DIR", raising=False)
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_NAME", raising=False)

    pointer = tmp_path / "active"
    pointer.write_text("pointer-dist\n")
    meta = _make_meta("pointer-dist", tmp_path / "src")
    monkeypatch.setattr(active_mod, "read_distribution_metadata", lambda n: meta if n == "pointer-dist" else None)
    assert active_mod.active_distribution() == "pointer-dist"


def test_pointer_file_stale_name_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path))
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_DIR", raising=False)
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_NAME", raising=False)

    pointer = tmp_path / "active"
    pointer.write_text("gone-dist\n")
    monkeypatch.setattr(active_mod, "read_distribution_metadata", lambda n: None)
    with pytest.raises(ActiveDistributionError, match="not an installed distribution"):
        active_mod.active_distribution()


def test_pointer_file_empty_falls_through(tmp_path, monkeypatch):
    """Empty pointer file is treated as absent — falls through to next priority."""
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path))
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_DIR", raising=False)
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_NAME", raising=False)

    pointer = tmp_path / "active"
    pointer.write_text("   \n")  # only whitespace

    meta = _make_meta("solo-dist", tmp_path / "src")
    monkeypatch.setattr(active_mod, "list_installed_distributions", lambda: [meta])
    monkeypatch.setattr(active_mod, "read_distribution_metadata", lambda n: meta if n == "solo-dist" else None)
    assert active_mod.active_distribution() == "solo-dist"


# ---------------------------------------------------------------------------
# Priority 4: only-installed fallback
# ---------------------------------------------------------------------------

def test_single_installed_dist_used_as_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path))
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_DIR", raising=False)
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_NAME", raising=False)

    meta = _make_meta("only-dist", tmp_path / "src")
    monkeypatch.setattr(active_mod, "list_installed_distributions", lambda: [meta])
    assert active_mod.active_distribution() == "only-dist"


def test_single_installed_source_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path))
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_DIR", raising=False)
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_NAME", raising=False)

    src = tmp_path / "src"
    meta = _make_meta("only-dist", src)
    monkeypatch.setattr(active_mod, "list_installed_distributions", lambda: [meta])
    monkeypatch.setattr(active_mod, "read_distribution_metadata", lambda n: meta if n == "only-dist" else None)
    assert active_mod.source_dir() == src


# ---------------------------------------------------------------------------
# Priority 5: error cases
# ---------------------------------------------------------------------------

def test_no_installed_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path))
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_DIR", raising=False)
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_NAME", raising=False)
    monkeypatch.setattr(active_mod, "list_installed_distributions", lambda: [])
    with pytest.raises(ActiveDistributionError, match="no spindle distributions"):
        active_mod.active_distribution()


def test_multiple_installed_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path))
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_DIR", raising=False)
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_NAME", raising=False)

    metas = [_make_meta("dist-a", tmp_path / "a"), _make_meta("dist-b", tmp_path / "b")]
    monkeypatch.setattr(active_mod, "list_installed_distributions", lambda: metas)
    with pytest.raises(ActiveDistributionError, match="multiple distributions"):
        active_mod.active_distribution()


# ---------------------------------------------------------------------------
# set_active
# ---------------------------------------------------------------------------

def test_set_active_writes_pointer(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path))
    meta = _make_meta("target-dist", tmp_path / "src")
    monkeypatch.setattr(active_mod, "read_distribution_metadata", lambda n: meta if n == "target-dist" else None)

    active_mod.set_active("target-dist")

    pointer = tmp_path / "active"
    assert pointer.exists()
    assert pointer.read_text(encoding="utf-8").strip() == "target-dist"


def test_set_active_nonexistent_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path))
    monkeypatch.setattr(active_mod, "read_distribution_metadata", lambda n: None)
    with pytest.raises(ActiveDistributionError, match="not an installed distribution"):
        active_mod.set_active("ghost-dist")


def test_set_active_creates_parent_dirs(tmp_path, monkeypatch):
    nested = tmp_path / "a" / "b" / "spindle-state"
    monkeypatch.setenv("SPINDLE_HOME", str(nested))
    meta = _make_meta("my-dist", tmp_path / "src")
    monkeypatch.setattr(active_mod, "read_distribution_metadata", lambda n: meta if n == "my-dist" else None)

    active_mod.set_active("my-dist")
    assert (nested / "active").exists()


# ---------------------------------------------------------------------------
# Integration: peers/verdicts/scout use active.source_dir()
# ---------------------------------------------------------------------------

def test_peers_uses_active_source_dir(tmp_path, monkeypatch):
    """peers module routes through active.source_dir() for file location."""
    import spindle.peers as peers_mod

    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    peers_mod.add(slug="check", name="Check", url="https://example.com")
    assert (tmp_path / "peers" / "peers.toml").exists()


def test_verdicts_uses_active_source_dir(tmp_path, monkeypatch):
    """verdicts module routes through active.source_dir() for file location."""
    import spindle.verdicts as verdicts_mod

    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    verdicts_mod.write("chk", source="peer-x")
    assert (tmp_path / "verdicts" / "chk.md").exists()


def test_scout_jobs_use_active_source_dir(tmp_path, monkeypatch):
    """emit_scout_jobs() reads scout-pass.md from active.source_dir() / scout."""
    import spindle.scout as scout_mod
    import spindle.peers as peers_mod

    scout_d = tmp_path / "scout"
    scout_d.mkdir()
    (scout_d / "scout-pass.md").write_text("# scout\n")

    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    monkeypatch.setattr(peers_mod, "list_peers", lambda: [
        {"slug": "tpeer", "url": "https://example.com", "last_seen": "2026-01-01"},
    ])
    cmds = scout_mod.emit_scout_jobs()
    assert len(cmds) == 1
    assert "tpeer" in cmds[0]
