"""Organization lifecycle-policy parsing, enforcement, and audit coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spindle.cli import main
from spindle.lifecycle import LifecycleError, SkillRef
from spindle.maintenance import AdoptionRecord
from spindle.policy import (
    assert_adoption_allowed,
    assert_candidate_allowed,
    audit_policy,
    load_policy,
)


def _policy(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    policy = repo / ".spindle" / "policy.toml"
    policy.parent.mkdir()
    policy.write_text(
        '''schema = "spindle.organization-policy/v1"

[sources]
allowed_providers = ["git"]

[authority]
ceiling = "read-only"

[hooks]
required_scopes = []

[evidence]
required_attestations = []
require_certified_adapter = false

[adapters]
codex = ["0.146.0"]
''',
        encoding="utf-8",
    )
    return repo


def _adoption() -> AdoptionRecord:
    return AdoptionRecord(
        skill="review",
        package_name="review",
        package_digest="sha256:" + "1" * 64,
        skill_digest="sha256:" + "2" * 64,
        skill_subpath=".",
        source=SkillRef(
            provider="git",
            locator="https://example.test/review.git",
            revision="3" * 40,
            content_digest="sha256:" + "1" * 64,
        ),
        surface_id="sha256:" + "4" * 64,
        harness="codex",
        scope="repo",
        owner="team",
        adopted_at="2026-07-31T12:00:00Z",
        update_reference="manual",
        authority_ceiling="read-only",
        retirement_policy="manual",
        lease_id="sha256:" + "5" * 64,
        trial_run_receipt_id="sha256:" + "6" * 64,
        activation_receipt_id="7" * 64,
    )


def test_policy_fails_closed_on_provider_authority_and_build(tmp_path):
    policy = load_policy(_policy(tmp_path))
    assert policy is not None
    assert_candidate_allowed(policy, provider="git", posture="read-only")
    with pytest.raises(LifecycleError, match="disallows source provider"):
        assert_candidate_allowed(policy, provider="local", posture="read-only")
    with pytest.raises(LifecycleError, match="authority ceiling"):
        assert_candidate_allowed(policy, provider="git", posture="sandboxed")
    with pytest.raises(LifecycleError, match="allowed codex build"):
        assert_adoption_allowed(policy, _adoption(), harness_build="0.147.0")
    assert_adoption_allowed(policy, _adoption(), harness_build="0.146.0")


def test_policy_cli_and_audit_name_missing_build_without_mutation(
    tmp_path, monkeypatch, capsys
):
    repo = _policy(tmp_path)
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()

    assert main(["policy", "show", "--repo", str(repo), "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["policy"]["authority_ceiling"] == "read-only"

    assert (
        main(
            [
                "policy",
                "check",
                "--repo",
                str(repo),
                "--harness",
                "codex",
                "--json",
            ]
        )
        == 2
    )
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["audit"]["findings"][0]["kind"] == "adapter-build"
    assert not (tmp_path / "state").exists()

    policy = load_policy(repo)
    assert policy is not None
    audit = audit_policy(policy, repo, "codex", harness_build="0.146.0")
    assert audit["decision"] == "pass"
