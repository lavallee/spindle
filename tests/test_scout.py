"""Tests for spindle.scout — extract_verdicts, write_candidate, apply_results, emit_scout_jobs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import spindle.scout_results as scout_mod
import spindle.scout as scout_ivy_mod
from spindle.cli import main


# ---- extract_verdicts ---------------------------------------------------

SINGLE_VERDICT_REPORT = """\
# Scout pass: gstack

## Summary

Found one new skill worth tracking.

## Candidate verdicts

```markdown
---
slug: gstack-new-review-skill
source: gstack
url: https://github.com/garrytan/gstack/blob/main/skills/review.md
first_seen: 2026-05-13
verdict: tracking
status: candidate
last_reviewed: 2026-05-13
---

# gstack new-review-skill

## What it is

A new review pattern added to gstack.

## Why it might matter for spindle

Could inform spindle-review chain improvements.

## Risk / cost of adopting

Low — existing skill, no deep integration needed.

## Recommended next step

Keep watching.
```

## Notes

Nothing urgent.
"""

MULTI_VERDICT_REPORT = """\
```markdown
---
slug: peer-alpha
source: alpha
url: https://example.com/alpha
first_seen: 2026-05-13
verdict: borrow
status: candidate
last_reviewed: 2026-05-13
---

# Alpha

Body.
```

```markdown
---
slug: peer-beta
source: beta
url: https://example.com/beta
first_seen: 2026-05-13
verdict: tracking
status: candidate
last_reviewed: 2026-05-13
---

# Beta

Body.
```
"""

NO_VERDICT_REPORT = """\
# Scout pass: quiet-peer

## Summary

Nothing notable this week.

## Notes

Checked all recent commits; no meaningful changes.
"""


def test_extract_single_verdict():
    results = scout_mod.extract_verdicts(SINGLE_VERDICT_REPORT)
    assert len(results) == 1
    slug, content = results[0]
    assert slug == "gstack-new-review-skill"
    assert "status: candidate" in content


def test_extract_multiple_verdicts():
    results = scout_mod.extract_verdicts(MULTI_VERDICT_REPORT)
    assert len(results) == 2
    slugs = [s for s, _ in results]
    assert "peer-alpha" in slugs
    assert "peer-beta" in slugs


def test_extract_no_verdicts():
    results = scout_mod.extract_verdicts(NO_VERDICT_REPORT)
    assert results == []


def test_extract_ignores_blocks_without_slug():
    report = "```markdown\n---\nsource: foo\n---\n\nno slug here\n```\n"
    assert scout_mod.extract_verdicts(report) == []


# ---- write_candidate ----------------------------------------------------

def test_write_candidate_creates_file(tmp_path):
    content = "---\nslug: test-slug\nstatus: candidate\n---\n\n# Test\n"
    p = scout_mod.write_candidate("test-slug", content, dest_dir=tmp_path)
    assert p == tmp_path / "test-slug.md"
    assert p.exists()
    assert "status: candidate" in p.read_text()


def test_write_candidate_creates_parent_dirs(tmp_path):
    dest = tmp_path / "a" / "b" / "_candidates"
    content = "---\nslug: nested\nstatus: candidate\n---\n"
    p = scout_mod.write_candidate("nested", content, dest_dir=dest)
    assert p.exists()


def test_write_candidate_trailing_newline(tmp_path):
    p = scout_mod.write_candidate("x", "body", dest_dir=tmp_path)
    assert p.read_text().endswith("\n")


# ---- apply_results ------------------------------------------------------

def _make_result_file(tmp_path: Path, report: str, as_json: bool = False) -> Path:
    p = tmp_path / "result.json"
    if as_json:
        p.write_text(json.dumps({"output": report}), encoding="utf-8")
    else:
        p.write_text(report, encoding="utf-8")
    return p


def test_apply_results_from_markdown(tmp_path):
    result_file = _make_result_file(tmp_path, SINGLE_VERDICT_REPORT)
    dest = tmp_path / "_candidates"
    written = scout_mod.apply_results(result_file, dest_dir=dest)
    assert len(written) == 1
    assert (dest / "gstack-new-review-skill.md").exists()


def test_apply_results_from_json(tmp_path):
    result_file = _make_result_file(tmp_path, MULTI_VERDICT_REPORT, as_json=True)
    dest = tmp_path / "_candidates"
    written = scout_mod.apply_results(result_file, dest_dir=dest)
    assert len(written) == 2
    assert (dest / "peer-alpha.md").exists()
    assert (dest / "peer-beta.md").exists()


def test_apply_results_no_verdicts(tmp_path):
    result_file = _make_result_file(tmp_path, NO_VERDICT_REPORT)
    dest = tmp_path / "_candidates"
    written = scout_mod.apply_results(result_file, dest_dir=dest)
    assert written == []
    assert not dest.exists()


# ---- emit_scout_jobs ----------------------------------------------------

def test_emit_scout_jobs_basic(tmp_path, monkeypatch):
    scout_d = tmp_path / "scout"
    scout_d.mkdir()
    (scout_d / "scout-pass.md").write_text("# scout\n")
    import spindle.active as active_mod_local
    monkeypatch.setattr(active_mod_local, "source_dir", lambda: tmp_path)
    import spindle.peers as peers_mod_local
    monkeypatch.setattr(peers_mod_local, "list_peers", lambda: [
        {"slug": "gstack", "url": "https://github.com/garrytan/gstack", "last_seen": "2026-05-01"},
    ])
    cmds = scout_ivy_mod.emit_scout_jobs()
    assert len(cmds) == 1
    assert "gstack" in cmds[0]
    assert "--apply-results" not in cmds[0]


def test_emit_scout_jobs_slug_filter(tmp_path, monkeypatch):
    scout_d = tmp_path / "scout"
    scout_d.mkdir()
    (scout_d / "scout-pass.md").write_text("# scout\n")
    import spindle.active as active_mod_local
    monkeypatch.setattr(active_mod_local, "source_dir", lambda: tmp_path)
    import spindle.peers as peers_mod_local
    monkeypatch.setattr(peers_mod_local, "list_peers", lambda: [
        {"slug": "gstack", "url": "https://github.com/garrytan/gstack", "last_seen": "2026-05-01"},
        {"slug": "other", "url": "https://example.com", "last_seen": "2026-05-01"},
    ])
    cmds = scout_ivy_mod.emit_scout_jobs(slug="gstack")
    assert len(cmds) == 1
    assert "gstack" in cmds[0]


def test_emit_scout_jobs_missing_slug_raises(tmp_path, monkeypatch):
    scout_d = tmp_path / "scout"
    scout_d.mkdir()
    (scout_d / "scout-pass.md").write_text("# scout\n")
    import spindle.active as active_mod_local
    monkeypatch.setattr(active_mod_local, "source_dir", lambda: tmp_path)
    import spindle.peers as peers_mod_local
    monkeypatch.setattr(peers_mod_local, "list_peers", lambda: [])
    with pytest.raises(ValueError, match="no peer"):
        scout_ivy_mod.emit_scout_jobs(slug="nonexistent")


def test_emit_scout_jobs_missing_pass_raises(tmp_path, monkeypatch):
    import spindle.active as active_mod_local
    monkeypatch.setattr(active_mod_local, "source_dir", lambda: tmp_path)
    with pytest.raises(FileNotFoundError, match="missing"):
        scout_ivy_mod.emit_scout_jobs()


def test_emit_scout_jobs_write_candidates(tmp_path, monkeypatch):
    scout_d = tmp_path / "scout"
    scout_d.mkdir()
    (scout_d / "scout-pass.md").write_text("# scout\n")
    import spindle.active as active_mod_local
    monkeypatch.setattr(active_mod_local, "source_dir", lambda: tmp_path)
    import spindle.peers as peers_mod_local
    monkeypatch.setattr(peers_mod_local, "list_peers", lambda: [
        {"slug": "gstack", "url": "https://github.com/garrytan/gstack", "last_seen": "2026-05-01"},
    ])
    cmds = scout_ivy_mod.emit_scout_jobs(write_candidates=True)
    assert len(cmds) == 1
    assert "--apply-results" in cmds[0]


# ---- CLI: spindle scout --apply-results -------------------------------------

def test_cli_apply_results(tmp_path, monkeypatch):
    import spindle.paths as paths_mod
    monkeypatch.setattr(paths_mod, "candidates_dir", lambda: tmp_path / "_candidates")
    result_file = _make_result_file(tmp_path, SINGLE_VERDICT_REPORT)
    rc = main(["scout", "--apply-results", str(result_file)])
    assert rc == 0
    assert (tmp_path / "_candidates" / "gstack-new-review-skill.md").exists()


def test_cli_apply_results_missing_file(tmp_path, capsys):
    rc = main(["scout", "--apply-results", str(tmp_path / "nope.json")])
    assert rc != 0
    assert "no such file" in capsys.readouterr().err


# ---- CLI: spindle scout --write-candidates ----------------------------------

def test_cli_write_candidates_flag(tmp_path, monkeypatch, capsys):
    """--write-candidates wires notify to spindle scout --apply-results."""
    monkeypatch.chdir(tmp_path)
    # Provide a minimal scout-pass.md so the command doesn't bail early
    scout_d = tmp_path / "scout"
    scout_d.mkdir()
    (scout_d / "scout-pass.md").write_text("# scout\n")
    import spindle.scout as scout_ivy
    import spindle.active as active_mod_local
    monkeypatch.setattr(active_mod_local, "source_dir", lambda: tmp_path)
    import spindle.peers as peers_mod_local
    monkeypatch.setattr(peers_mod_local, "list_peers", lambda: [
        {"slug": "gstack", "url": "https://github.com/garrytan/gstack", "last_seen": "2026-05-01"},
    ])
    rc = main(["scout", "--write-candidates"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "--apply-results" in out
    assert "gstack" in out
