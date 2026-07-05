"""End-to-end: SPINDLE_ACTIVE_DIST_DIR override swaps active distribution content.

Checkpoint B verification:
  - /tmp/stub-dist is created with fake peers and verdicts.
  - Setting SPINDLE_ACTIVE_DIST_DIR routes peers/verdicts reads to the stub.
  - Unsetting the var returns resolution to the sample distribution.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import spindle.active as active_mod
import spindle.peers as peers_mod
import spindle.verdicts as verdicts_mod

STUB_DIST = Path("/tmp/stub-dist")

_PEERS_TOML = """\
# stub peer registry — e2e test fixture
[[peer]]
slug = "stub-peer"
name = "Stub Peer"
url = "https://stub.example.com"
kind = "github"
last_seen = "2026-01-01"
our_take = "test fixture only"
notes = ""
"""

_VERDICT_MD = """\
---
slug: stub-verdict
source: stub-peer
url: https://stub.example.com
first_seen: 2026-01-01
verdict: tracking
status: candidate
last_reviewed: 2026-01-01
---

# stub-verdict

Fake verdict for e2e tests.
"""


@pytest.fixture(scope="module")
def stub_dist():
    """Create /tmp/stub-dist with fake peers and verdicts; clean up after."""
    (STUB_DIST / "peers").mkdir(parents=True, exist_ok=True)
    (STUB_DIST / "peers" / "peers.toml").write_text(_PEERS_TOML)

    (STUB_DIST / "verdicts").mkdir(parents=True, exist_ok=True)
    (STUB_DIST / "verdicts" / "stub-verdict.md").write_text(_VERDICT_MD)

    (STUB_DIST / "scout").mkdir(parents=True, exist_ok=True)
    (STUB_DIST / "scout" / "scout-pass.md").write_text("# stub scout pass\n")

    yield STUB_DIST

    shutil.rmtree(STUB_DIST, ignore_errors=True)


# ---------------------------------------------------------------------------
# Stub dist layout
# ---------------------------------------------------------------------------

def test_stub_dist_peers_toml_exists(stub_dist):
    assert (STUB_DIST / "peers" / "peers.toml").exists()


def test_stub_dist_verdict_exists(stub_dist):
    assert (STUB_DIST / "verdicts" / "stub-verdict.md").exists()


# ---------------------------------------------------------------------------
# SPINDLE_ACTIVE_DIST_DIR override routes reads to stub-dist
# ---------------------------------------------------------------------------

def test_override_peers_reads_stub(stub_dist, monkeypatch):
    """SPINDLE_ACTIVE_DIST_DIR routes peers.list_peers() to stub-dist content."""
    monkeypatch.setenv("SPINDLE_ACTIVE_DIST_DIR", str(STUB_DIST))
    peers = peers_mod.list_peers()
    assert any(p["slug"] == "stub-peer" for p in peers)


def test_override_verdicts_reads_stub(stub_dist, monkeypatch):
    """SPINDLE_ACTIVE_DIST_DIR routes verdicts.list_verdicts() to stub-dist content."""
    monkeypatch.setenv("SPINDLE_ACTIVE_DIST_DIR", str(STUB_DIST))
    verdicts = verdicts_mod.list_verdicts()
    assert any(v.get("slug") == "stub-verdict" for v in verdicts)


def test_override_source_dir_is_stub(stub_dist, monkeypatch):
    """SPINDLE_ACTIVE_DIST_DIR makes active.source_dir() return the stub path."""
    monkeypatch.setenv("SPINDLE_ACTIVE_DIST_DIR", str(STUB_DIST))
    assert active_mod.source_dir() == STUB_DIST


def test_override_active_distribution_is_anonymous(stub_dist, monkeypatch):
    """SPINDLE_ACTIVE_DIST_DIR yields the 'anonymous' distribution name."""
    monkeypatch.setenv("SPINDLE_ACTIVE_DIST_DIR", str(STUB_DIST))
    assert active_mod.active_distribution() == active_mod.ANONYMOUS


# ---------------------------------------------------------------------------
# Unset env var returns to the sample distribution
# ---------------------------------------------------------------------------

def test_unset_returns_to_spindle_sample_source_dir(tmp_path, monkeypatch):
    """Without SPINDLE_ACTIVE_DIST_DIR, source_dir resolves to the sample source."""
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path))  # no pointer file
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_DIR", raising=False)
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_NAME", raising=False)

    from spindle.distributions import read_distribution_metadata
    sample_meta = read_distribution_metadata("spindle-sample")
    assert sample_meta is not None, "spindle-sample must be installed"

    assert active_mod.source_dir() == sample_meta.source_dir


def test_unset_stub_peer_not_visible(tmp_path, stub_dist, monkeypatch):
    """Without the env override, stub peers are absent from list_peers()."""
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path))
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_DIR", raising=False)
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_NAME", raising=False)

    slugs = [p["slug"] for p in peers_mod.list_peers()]
    assert "stub-peer" not in slugs


def test_unset_stub_verdict_not_visible(tmp_path, stub_dist, monkeypatch):
    """Without the env override, stub verdicts are absent from list_verdicts()."""
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path))
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_DIR", raising=False)
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_NAME", raising=False)

    slugs = [v.get("slug") for v in verdicts_mod.list_verdicts()]
    assert "stub-verdict" not in slugs
