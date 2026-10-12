from __future__ import annotations

from pathlib import Path

from spindle.lifecycle import SkillRef, SurfaceLock, digest_path
from spindle.maintenance import (
    ADOPTION_RECORD_SCHEMA,
    AdoptionRecord,
    AdoptionStore,
    MaintenanceEvent,
    current_status,
    health_report,
    lock_with_adoption,
    projection_for_adoption,
    record_status,
)


def _adoption(tmp_path: Path, monkeypatch, version: str, previous=None):
    state = tmp_path / "state"
    monkeypatch.setenv("SPINDLE_HOME", str(state))
    staging = tmp_path / f"staging-{version}"
    skill = staging / "skills" / "review"
    skill.mkdir(parents=True)
    skill.joinpath("SKILL.md").write_text(
        f"---\nname: review\ndescription: Review.\n---\n\nReview {version}.\n",
        encoding="utf-8",
    )
    package_digest = digest_path(staging)
    skill_digest = digest_path(skill)
    cached = state / "cache" / "packages" / package_digest[7:] / "review-package"
    cached.parent.mkdir(parents=True)
    staging.rename(cached)
    source = SkillRef(
        provider="git",
        locator="https://example.test/review.git",
        revision=(version * 40)[:40],
        content_digest=package_digest,
        subpath="skills/review",
    )
    record = AdoptionRecord(
        skill="review",
        package_name="review-package",
        package_digest=package_digest,
        skill_digest=skill_digest,
        skill_subpath="skills/review",
        source=source,
        surface_id="sha256:" + "1" * 64,
        harness="codex",
        scope="repo",
        owner="team",
        adopted_at=f"2026-07-31T1{version}:00:00Z",
        update_reference="git+https://example.test/review.git@main#review",
        authority_ceiling="read-only",
        retirement_policy="manual",
        lease_id="sha256:" + version * 64,
        trial_run_receipt_id="sha256:" + version * 64,
        activation_receipt_id=version * 64,
        previous_adoption_id=previous,
        evidence_coordinate=(
            ("harness", "codex"),
            ("model", "gpt-old"),
            ("policy_digest", "sha256:" + "9" * 64),
        ),
    )
    return record


def _base(tmp_path: Path) -> SurfaceLock:
    return SurfaceLock(
        surface_id="sha256:" + "1" * 64,
        surface_name="repo",
        repo_path=str(tmp_path / "repo"),
        harness="codex",
        binding_coordinate="lease-only/v1",
        projections=(),
    )


def test_adoption_store_and_exact_rollback_restore_prior_lock(tmp_path, monkeypatch):
    first = _adoption(tmp_path, monkeypatch, "2")
    second = _adoption(tmp_path, monkeypatch, "3", previous=first.adoption_id)
    store = AdoptionStore()
    store.record(first)
    store.record(second)

    assert first.to_dict()["schema"] == ADOPTION_RECORD_SCHEMA
    assert store.get(first.adoption_id) == first
    first_projection = projection_for_adoption(
        first, tmp_path / "repo" / ".agents" / "skills" / "review"
    )
    first_lock = lock_with_adoption(_base(tmp_path), first, first_projection)
    second_projection = projection_for_adoption(
        second, tmp_path / "repo" / ".agents" / "skills" / "review"
    )
    second_lock = lock_with_adoption(
        first_lock,
        second,
        second_projection,
        replace_adoption_id=first.adoption_id,
    )
    rolled_back = lock_with_adoption(
        second_lock,
        first,
        first_projection,
        replace_adoption_id=second.adoption_id,
    )

    assert first_lock.lock_id != second_lock.lock_id
    assert rolled_back.lock_id == first_lock.lock_id
    assert rolled_back.projections == first_lock.projections


def test_status_history_and_health_coordinate_drift(tmp_path, monkeypatch):
    adoption = _adoption(tmp_path, monkeypatch, "4")
    AdoptionStore().record(adoption)
    projection = projection_for_adoption(
        adoption, tmp_path / "repo" / ".agents" / "skills" / "review"
    )
    lock = lock_with_adoption(_base(tmp_path), adoption, projection)
    event = MaintenanceEvent(
        operation="adopt",
        skill="review",
        surface_id=adoption.surface_id,
        adoption_id=adoption.adoption_id,
        previous_adoption_id=None,
        prior_lock_id=_base(tmp_path).lock_id,
        next_lock_id=lock.lock_id,
        reason="trial succeeded",
        actor="team",
        observed_at="2026-07-31T14:00:00Z",
        startup_receipt_id="sha256:" + "5" * 64,
    )
    record_status(event, "active")
    report = health_report(
        lock,
        surface_id=adoption.surface_id,
        inventory_id="sha256:" + "6" * 64,
        current_coordinate=(
            ("harness", "codex"),
            ("model", "gpt-new"),
            ("policy_digest", "sha256:" + "8" * 64),
        ),
    )

    assert current_status(adoption.surface_id, "review")["status"] == "active"
    assert report.skills[0]["evidence_drift"] == ["model", "policy_digest"]
    assert "behavioral-contribution-unassessed" in report.skills[0]["findings"]
    assert report.skills[0]["cache_state"] == "ok"
