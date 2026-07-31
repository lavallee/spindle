"""Read-only local candidate resolution and deterministic intent-card coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from spindle.intent import build_intent_card, resolve_local_candidate
from spindle.lifecycle import LifecycleError


def _skill(root: Path, name: str, body: str = "Review changes carefully.") -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Review risky migrations\n"
        "allowed-tools: Read,Grep\n---\n\n"
        f"{body}\n\nSee [checklist](references/checklist.md).\n",
        encoding="utf-8",
    )
    (skill / "references").mkdir()
    (skill / "references" / "checklist.md").write_text("Check rollback.\n")
    return skill


def test_intent_card_is_deterministic_and_keeps_facts_separate_from_fit(tmp_path):
    skill = _skill(tmp_path, "review")
    candidate = resolve_local_candidate(str(skill))

    first = build_intent_card(
        candidate,
        requested_intent="review this risky migration",
        effective_entries=(
            {"name": "ambient", "scope": "user", "state": "foreign", "path": "/x"},
        ),
    )
    second = build_intent_card(
        candidate,
        requested_intent="review this risky migration",
        effective_entries=(
            {"name": "ambient", "scope": "user", "state": "foreign", "path": "/x"},
        ),
    )

    assert first == second
    assert first.card_id == second.card_id
    payload = first.to_dict()
    assert payload["schema"] == "spindle.intent-card/v1"
    assert payload["package_facts"]["outcome"] == "Review risky migrations"
    assert payload["package_facts"]["requirements"]["missing_references"] == []
    assert payload["package_facts"]["authority"]["default_trial_posture"] == (
        "read-only"
    )
    assert payload["fit_analysis"]["model_assisted"] is False
    assert payload["fit_analysis"]["behavioral_fit"] == "unassessed"
    assert payload["fit_analysis"]["composition"] == "additive"


def test_inspection_does_not_execute_script_or_write_state(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("SPINDLE_HOME", str(state))
    skill = _skill(tmp_path / "candidate", "review")
    script = skill / "scripts" / "setup.sh"
    script.parent.mkdir()
    marker = tmp_path / "executed"
    script.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    script.chmod(0o755)

    card = build_intent_card(resolve_local_candidate(str(skill)))

    assert not marker.exists()
    assert not state.exists()
    authority = card.package_facts["authority"]
    assert authority["executable_resources"] == ["scripts/setup.sh"]
    assert authority["requires_explicit_expansion"] is True


def test_package_reference_requires_fragment_when_multiple_skills(tmp_path):
    package = tmp_path / "package"
    _skill(package / "skills", "review")
    _skill(package / "skills", "plan")

    with pytest.raises(LifecycleError, match="select one with #"):
        resolve_local_candidate(str(package))

    selected = resolve_local_candidate(f"{package}#review")
    assert selected.skill == "review"
    assert selected.revision.skill_digests[0][0] == "plan"


def test_outside_package_reference_is_reported_without_reading_it(tmp_path):
    secret = tmp_path / "secret.md"
    secret.write_text("do not inspect me\n", encoding="utf-8")
    skill = _skill(tmp_path / "candidate", "review")
    skill_md = skill / "SKILL.md"
    skill_md.write_text(
        skill_md.read_text(encoding="utf-8") + "\n[external](../../secret.md)\n",
        encoding="utf-8",
    )

    card = build_intent_card(resolve_local_candidate(str(skill)))
    references = card.package_facts["requirements"]["references"]

    assert {item["state"] for item in references} == {"present", "outside-package"}
