"""T9 migration: spindle-sample resolves as 'system for claude' through the binder.

This test covers the real shipped sample skills binding onto a claude surface
via the channel pipeline, end to end, with no distribution install required.
"""

from __future__ import annotations

from pathlib import Path

import spindle.binder as binder
import spindle.binding as binding_mod
import spindle.channels as channels
import spindle.skills as skills_mod
from spindle.channels import Surface
from spindle.doctrine import Doctrine

REPO = Path(__file__).resolve().parent.parent


def _sample_skill_index() -> dict[str, Path]:
    """Map skill name (frontmatter) -> dir, scanning the sample package directly
    (no install needed) — what skills.discover_skills would yield once installed."""
    index: dict[str, Path] = {}
    for md in (REPO / "examples" / "spindle-sample" / "packages").rglob("SKILL.md"):
        name = skills_mod._read_skill_name(md.parent)
        if name:
            index[name] = md.parent
    return index


def test_spindle_sample_resolves_as_system_for_claude(tmp_path, monkeypatch):
    monkeypatch.setattr(binding_mod.paths, "spindle_home", lambda: tmp_path / "state")
    index = _sample_skill_index()
    provider = channels.fs_provider(index, source_dir=REPO / "examples" / "spindle-sample")

    repo = tmp_path / "someproj"
    repo.mkdir()
    surface = Surface(name="someproj", harness="claude", autonomy_mode="deterministic")
    result = binder.bind(surface, repo, provider, Doctrine(version="0.1.0"))

    assert result.ok, result.problems
    linked = sorted(p.name for p in (repo / ".claude" / "skills").iterdir())
    # the full sample set landed as the system/claude channel
    assert linked == ["clarify", "design", "review", "tasks"]
    # and the binding was recorded for rollback
    assert binding_mod.current_binding("someproj").coordinate == result.coordinate


def test_no_clusters_or_repo_channel_still_binds_system(tmp_path, monkeypatch):
    # A bare surface (no cluster channels, no repo channel) still gets the system set.
    monkeypatch.setattr(binding_mod.paths, "spindle_home", lambda: tmp_path / "state")
    provider = channels.fs_provider(
        _sample_skill_index(), source_dir=REPO / "examples" / "spindle-sample"
    )
    repo = tmp_path / "bare"
    repo.mkdir()
    surface = Surface(name="bare", harness="claude", autonomy_mode="deterministic",
                      clusters=("lang:python",))  # cluster has no channel → skipped
    result = binder.bind(surface, repo, provider, Doctrine(version="0.1.0"))
    assert result.ok
    assert len(list((repo / ".claude" / "skills").iterdir())) == 4
