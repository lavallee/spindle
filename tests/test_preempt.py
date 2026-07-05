"""Tests for spindle.preempt — _load_snippet and preempt/unpreempt lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest

import spindle.preempt as preempt_mod
from spindle.preempt import _BEGIN, _END, _load_snippet, is_preempted, preempt, unpreempt
from spindle.models import DistributionMetadata
from spindle.active import ANONYMOUS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_meta(name: str, source_dir: Path, snippet_path: Path | None = None) -> DistributionMetadata:
    return DistributionMetadata(
        name=name,
        version="0.1.0",
        display_name=name,
        description="",
        source_dir=source_dir,
        preempt_snippet=snippet_path,
        home_url=None,
        packages=[],
    )


@pytest.fixture(autouse=True)
def isolated_spindle_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "spindle-state"))
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_DIR", raising=False)
    monkeypatch.delenv("SPINDLE_ACTIVE_DIST_NAME", raising=False)


@pytest.fixture
def dist_with_snippet(tmp_path, monkeypatch):
    """Set up an active distribution whose preempt_snippet file exists."""
    snippet_file = tmp_path / "preempt.md"
    snippet_file.write_text("# Hello from distribution\n")
    meta = _make_meta("test-dist", tmp_path, snippet_path=snippet_file)

    monkeypatch.setattr(preempt_mod.active, "active_distribution", lambda: "test-dist")
    monkeypatch.setattr(
        preempt_mod, "read_distribution_metadata",
        lambda n: meta if n == "test-dist" else None,
    )
    return meta


# ---------------------------------------------------------------------------
# _load_snippet
# ---------------------------------------------------------------------------

def test_load_snippet_wraps_content_with_delimiters(dist_with_snippet):
    snippet = _load_snippet()
    assert snippet.startswith(_BEGIN)
    assert _END in snippet
    assert "Hello from distribution" in snippet


def test_load_snippet_strips_trailing_newlines_from_file(dist_with_snippet, tmp_path):
    (tmp_path / "preempt.md").write_text("body line\n\n\n")
    snippet = _load_snippet()
    # content between delimiters should not end with blank lines
    inner = snippet[len(_BEGIN):snippet.index(_END)]
    assert not inner.endswith("\n\n")


def test_load_snippet_anonymous_dist_raises(monkeypatch):
    monkeypatch.setattr(preempt_mod.active, "active_distribution", lambda: ANONYMOUS)
    with pytest.raises(RuntimeError, match="anonymous"):
        _load_snippet()


def test_load_snippet_no_snippet_configured_raises(monkeypatch):
    meta = _make_meta("bare-dist", Path("/fake"), snippet_path=None)
    monkeypatch.setattr(preempt_mod.active, "active_distribution", lambda: "bare-dist")
    monkeypatch.setattr(
        preempt_mod, "read_distribution_metadata",
        lambda n: meta if n == "bare-dist" else None,
    )
    with pytest.raises(RuntimeError, match="no `preempt_snippet`"):
        _load_snippet()


def test_load_snippet_meta_not_found_raises(monkeypatch):
    monkeypatch.setattr(preempt_mod.active, "active_distribution", lambda: "ghost-dist")
    monkeypatch.setattr(preempt_mod, "read_distribution_metadata", lambda n: None)
    with pytest.raises(RuntimeError, match="not found"):
        _load_snippet()


# ---------------------------------------------------------------------------
# preempt / unpreempt lifecycle
# ---------------------------------------------------------------------------

@pytest.fixture
def claude_md(tmp_path, monkeypatch, dist_with_snippet):
    md = tmp_path / "CLAUDE.md"
    monkeypatch.setenv("CLAUDE_MD_PATH", str(md))
    return md


def test_preempt_creates_file_when_absent(claude_md):
    result = preempt()
    assert result == "added"
    assert claude_md.exists()
    text = claude_md.read_text()
    assert _BEGIN in text
    assert _END in text


def test_preempt_idempotent(claude_md):
    preempt()
    result = preempt()
    assert result == "already-present"


def test_preempt_appends_to_existing_file(claude_md):
    claude_md.write_text("existing content\n")
    preempt()
    text = claude_md.read_text()
    assert "existing content" in text
    assert _BEGIN in text


def test_is_preempted_true_after_preempt(claude_md):
    preempt()
    assert is_preempted()


def test_is_preempted_false_before_preempt(claude_md):
    assert not is_preempted()


def test_unpreempt_removes_block(claude_md):
    preempt()
    result = unpreempt()
    assert result == "removed"
    text = claude_md.read_text() if claude_md.exists() else ""
    assert _BEGIN not in text
    assert _END not in text


def test_unpreempt_not_present_returns_not_present(claude_md):
    result = unpreempt()
    assert result == "not-present"


def test_unpreempt_preserves_surrounding_content(claude_md):
    claude_md.write_text("before\n")
    preempt()
    claude_md.write_text(claude_md.read_text() + "after\n")
    unpreempt()
    text = claude_md.read_text()
    assert "before" in text
    assert "after" in text


def test_unpreempt_deletes_file_if_only_snippet(claude_md):
    preempt()
    # File contains only the snippet — unpreempt should delete it
    text = claude_md.read_text().strip()
    # Verify the file is only the snippet block
    assert text.startswith(_BEGIN)
    assert text.endswith(_END)
    unpreempt()
    assert not claude_md.exists()
