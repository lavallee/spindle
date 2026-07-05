"""Tests for spindle.verdicts — list_verdicts, get, write using active.source_dir()."""

from __future__ import annotations

import spindle.verdicts as verdicts_mod
import spindle.active as active_mod


def test_list_verdicts_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    assert verdicts_mod.list_verdicts() == []


def test_write_and_list(tmp_path, monkeypatch):
    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    p = verdicts_mod.write("cool-tool", source="gstack", url="https://example.com")
    assert p == tmp_path / "verdicts" / "cool-tool.md"
    items = verdicts_mod.list_verdicts()
    assert len(items) == 1
    assert items[0]["slug"] == "cool-tool"
    assert items[0]["source"] == "gstack"


def test_list_skips_underscore_files(tmp_path, monkeypatch):
    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    verdicts_mod.write("visible", source="peer-a")
    d = tmp_path / "verdicts"
    (d / "_candidate.md").write_text("---\nslug: _candidate\n---\nbody\n")
    items = verdicts_mod.list_verdicts()
    assert len(items) == 1
    assert items[0]["slug"] == "visible"


def test_get_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    verdicts_mod.write("my-idea", source="peer-b", verdict="borrow", body="details here")
    result = verdicts_mod.get("my-idea")
    assert result is not None
    fm, body = result
    assert fm["verdict"] == "borrow"
    assert "details here" in body


def test_get_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    assert verdicts_mod.get("nonexistent") is None


def test_verdicts_dir_path(tmp_path, monkeypatch):
    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    assert verdicts_mod._verdicts_dir() == tmp_path / "verdicts"


def test_write_creates_parent_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(active_mod, "source_dir", lambda: tmp_path)
    verdicts_mod.write("new-slug", source="peer-c")
    assert (tmp_path / "verdicts").is_dir()


def test_list_candidates_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(verdicts_mod._paths, "candidates_dir", lambda: tmp_path / "_candidates")
    assert verdicts_mod.list_candidates() == []


def test_list_candidates_reads_drafts(tmp_path, monkeypatch):
    cand = tmp_path / "_candidates"
    cand.mkdir()
    (cand / "gstack-thing.md").write_text(
        "---\nslug: gstack-thing\nsource: gstack\nverdict: try\n---\n# body\n"
    )
    monkeypatch.setattr(verdicts_mod._paths, "candidates_dir", lambda: cand)
    rows = verdicts_mod.list_candidates()
    assert len(rows) == 1
    assert rows[0]["slug"] == "gstack-thing"
    assert rows[0]["source"] == "gstack"
    assert rows[0]["_path"].endswith("gstack-thing.md")
