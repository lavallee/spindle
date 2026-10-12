"""Runtime realization: one installed package, session-local evaluated overlays."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from spindle.realization import (
    RealizationError,
    SessionProfile,
    load_profiles,
    realize_skill,
    resolve_profile,
)

CORE = """\
---
name: sample-review
description: Review a change.
---

# Review

Inspect the change and report material findings.
"""


def _skill(tmp_path: Path, manifest: str | None = None) -> Path:
    root = tmp_path / "sample-review"
    root.mkdir()
    (root / "SKILL.md").write_text(CORE)
    references = root / "references"
    references.mkdir()
    (references / "rubric.md").write_text("Check correctness.\n")
    if manifest is not None:
        (root / "spindle-realization.toml").write_text(manifest)
    return root


def _manifest(*profiles: str) -> str:
    return "schema_version = 1\n\n" + "\n\n".join(profiles) + "\n"


SOL = """\
[[profile]]
id = "codex-sol-review"
overlay = "overlays/codex-sol-review.md"

[profile.match]
harness = "codex"
model = "gpt-sol"
effort = "high"
role = "reviewer"
"""

TERRA = """\
[[profile]]
id = "codex-terra-explore"
overlay = "overlays/codex-terra-explore.md"

[profile.match]
harness = "codex"
model = "gpt-terra"
effort = "medium"
role = "explorer"
"""


def _runtime_skill(tmp_path: Path) -> Path:
    root = _skill(tmp_path, _manifest(SOL, TERRA))
    overlays = root / "overlays"
    overlays.mkdir()
    (overlays / "codex-sol-review.md").write_text(
        "Prioritize subtle correctness risks.\n"
    )
    (overlays / "codex-terra-explore.md").write_text(
        "Map relevant files before reporting.\n"
    )
    return root


def _session(**changes) -> SessionProfile:
    values = {
        "session_id": "session-1",
        "harness": "codex",
        "requested_model": "gpt-sol",
        "served_model": "gpt-sol",
        "effort": "high",
        "role": "reviewer",
    }
    values.update(changes)
    return SessionProfile(**values)


def test_matched_profile_adds_only_selected_overlay_and_writes_receipt(tmp_path):
    root = _runtime_skill(tmp_path)
    source_before = (root / "SKILL.md").read_text()

    result = realize_skill(
        root,
        _session(),
        store_root=tmp_path / "store",
        receipt_root=tmp_path / "receipts",
    )

    assert result.status == "matched"
    assert result.tuned is True
    assert result.profile_id == "codex-sol-review"
    assert result.overlay == "overlays/codex-sol-review.md"
    assert result.overlay_digest is not None
    realized = (result.path / "SKILL.md").read_text()
    assert "Prioritize subtle correctness risks." in realized
    assert "Map relevant files before reporting." not in realized
    assert not (result.path / "overlays").exists()
    assert not (result.path / "spindle-realization.toml").exists()
    assert (
        result.path / "references" / "rubric.md"
    ).read_text() == "Check correctness.\n"
    assert (root / "SKILL.md").read_text() == source_before

    receipt = json.loads(result.receipt_path.read_text())
    assert receipt["receipt_id"] == result.receipt_id
    assert receipt["session"]["requested_model"] == "gpt-sol"
    assert receipt["session"]["served_model"] == "gpt-sol"
    assert receipt["resolution"]["profile_id"] == "codex-sol-review"
    assert receipt["resolution"]["overlay"] == "overlays/codex-sol-review.md"
    assert receipt["resolution"]["overlay_digest"] == result.overlay_digest
    assert receipt["resolution"]["tuned"] is True


def test_no_manifest_realizes_invariant_core_without_tuned_claim(tmp_path):
    root = _skill(tmp_path)
    result = realize_skill(
        root,
        _session(),
        store_root=tmp_path / "store",
        receipt_root=tmp_path / "receipts",
    )
    assert result.status == "core"
    assert result.reason == "no-runtime-manifest"
    assert result.tuned is False
    assert (result.path / "SKILL.md").read_text() == CORE


def test_unknown_profile_falls_back_to_core(tmp_path):
    root = _runtime_skill(tmp_path)
    result = realize_skill(
        root,
        _session(served_model="unknown", requested_model="unknown"),
        store_root=tmp_path / "store",
        receipt_root=tmp_path / "receipts",
    )
    assert result.status == "unresolved"
    assert result.reason == "no-matching-profile"
    assert result.profile_id is None
    assert (result.path / "SKILL.md").read_text() == CORE


def test_requested_served_mismatch_falls_back_to_core(tmp_path):
    root = _runtime_skill(tmp_path)
    result = realize_skill(
        root,
        _session(requested_model="gpt-sol", served_model="gpt-terra"),
        store_root=tmp_path / "store",
        receipt_root=tmp_path / "receipts",
    )
    assert result.status == "unresolved"
    assert result.reason == "requested-served-model-mismatch"
    assert (result.path / "SKILL.md").read_text() == CORE


def test_requested_model_alone_does_not_prove_model_match(tmp_path):
    root = _runtime_skill(tmp_path)
    resolution = resolve_profile(root, _session(served_model=None))
    assert resolution.status == "unresolved"
    assert resolution.reason == "no-matching-profile"


def test_child_profile_resolves_independently_from_parent(tmp_path):
    root = _runtime_skill(tmp_path)
    parent = realize_skill(
        root,
        _session(session_id="parent"),
        store_root=tmp_path / "store",
        receipt_root=tmp_path / "receipts",
    )
    child = realize_skill(
        root,
        _session(
            session_id="child",
            requested_model="gpt-terra",
            served_model="gpt-terra",
            effort="medium",
            role="explorer",
        ),
        store_root=tmp_path / "store",
        receipt_root=tmp_path / "receipts",
    )
    assert parent.profile_id == "codex-sol-review"
    assert child.profile_id == "codex-terra-explore"
    assert parent.path != child.path


def test_concurrent_agents_do_not_mutate_shared_package(tmp_path):
    root = _runtime_skill(tmp_path)
    source_before = (root / "SKILL.md").read_text()
    sessions = [
        _session(session_id=f"review-{i}")
        if i % 2 == 0
        else _session(
            session_id=f"explore-{i}",
            requested_model="gpt-terra",
            served_model="gpt-terra",
            effort="medium",
            role="explorer",
        )
        for i in range(12)
    ]

    def run(session):
        return realize_skill(
            root,
            session,
            store_root=tmp_path / "store",
            receipt_root=tmp_path / "receipts",
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(run, sessions))

    assert {result.profile_id for result in results} == {
        "codex-sol-review",
        "codex-terra-explore",
    }
    assert len({result.path for result in results}) == 2
    assert (root / "SKILL.md").read_text() == source_before
    assert len(list((tmp_path / "receipts").glob("*.json"))) == len(sessions)


def test_more_specific_profile_wins_before_priority(tmp_path):
    generic = """\
[[profile]]
id = "codex-generic"
priority = 99

[profile.match]
harness = "codex"
"""
    exact = """\
[[profile]]
id = "codex-exact"

[profile.match]
harness = "codex"
model = "gpt-sol"
role = "reviewer"
"""
    root = _skill(tmp_path, _manifest(generic, exact))
    resolution = resolve_profile(root, _session())
    assert resolution.profile is not None
    assert resolution.profile.id == "codex-exact"


def test_priority_breaks_tie_between_equally_specific_profiles(tmp_path):
    low = """\
[[profile]]
id = "low"
priority = 1

[profile.match]
harness = "codex"
model = "gpt-sol"
"""
    high = """\
[[profile]]
id = "high"
priority = 2

[profile.match]
harness = "codex"
model = "gpt-sol"
"""
    root = _skill(tmp_path, _manifest(low, high))
    resolution = resolve_profile(root, _session())
    assert resolution.profile is not None
    assert resolution.profile.id == "high"


def test_unresolved_tie_is_visible_and_uses_core(tmp_path):
    first = """\
[[profile]]
id = "first"
[profile.match]
harness = "codex"
model = "gpt-sol"
"""
    second = """\
[[profile]]
id = "second"
[profile.match]
harness = "codex"
model = "gpt-sol"
"""
    root = _skill(tmp_path, _manifest(first, second))
    resolution = resolve_profile(root, _session())
    assert resolution.status == "unresolved"
    assert resolution.reason == "ambiguous-profiles:first,second"


def test_profile_without_overlay_is_an_evaluated_empty_delta(tmp_path):
    core_only = """\
[[profile]]
id = "codex-core-is-enough"
[profile.match]
harness = "codex"
model = "gpt-sol"
"""
    root = _skill(tmp_path, _manifest(core_only))
    result = realize_skill(
        root,
        _session(),
        store_root=tmp_path / "store",
        receipt_root=tmp_path / "receipts",
    )
    assert result.status == "matched"
    assert result.tuned is True
    assert result.profile_id == "codex-core-is-enough"
    assert (result.path / "SKILL.md").read_text() == CORE


def test_invalid_overlay_escape_is_rejected(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("escape\n")
    profile = """\
[[profile]]
id = "escape"
overlay = "../outside.md"
[profile.match]
harness = "codex"
"""
    root = _skill(tmp_path, _manifest(profile))
    with pytest.raises(RealizationError, match="escapes"):
        load_profiles(root)


def test_invalid_match_field_is_rejected(tmp_path):
    profile = """\
[[profile]]
id = "typo"
[profile.match]
harness = "codex"
modle = "gpt-sol"
"""
    root = _skill(tmp_path, _manifest(profile))
    with pytest.raises(RealizationError, match="unknown match fields: modle"):
        load_profiles(root)


def test_unsafe_frontmatter_name_cannot_escape_realization_store(tmp_path):
    root = _skill(tmp_path)
    (root / "SKILL.md").write_text("---\nname: ../../escape\n---\n")

    with pytest.raises(RealizationError, match="unsafe skill name"):
        realize_skill(
            root,
            _session(),
            store_root=tmp_path / "store",
            receipt_root=tmp_path / "receipts",
        )
