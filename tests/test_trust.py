from __future__ import annotations

from pathlib import Path

import pytest

from spindle.intent import build_intent_card, resolve_local_candidate
from spindle.lifecycle import LifecycleError, digest_path
from spindle.trust import (
    assert_not_quarantined,
    load_attestations,
    preflight_candidate,
    quarantine_status,
    set_quarantine,
    write_preflight_report,
)


def _skill(root: Path, *, broken_reference: bool = False) -> Path:
    root.mkdir(parents=True)
    reference = "\n[missing](references/missing.md)\n" if broken_reference else ""
    root.joinpath("SKILL.md").write_text(
        "---\n"
        "name: remote-demo\n"
        "description: Review a migration.\n"
        "allowed-tools: Bash\n"
        "---\n\n"
        "# Review\n"
        "Use https://example.test and API_KEY when required.\n"
        + reference,
        encoding="utf-8",
    )
    scripts = root / "scripts"
    scripts.mkdir()
    script = scripts / "run.sh"
    script.write_text("#!/bin/sh\ncurl https://example.test\n", encoding="utf-8")
    script.chmod(0o755)
    root.joinpath("LICENSE").write_text("MIT fixture\n", encoding="utf-8")
    return root


def test_preflight_reports_static_risk_and_requires_explicit_authority(tmp_path):
    candidate = resolve_local_candidate(str(_skill(tmp_path / "candidate")))
    card = build_intent_card(candidate)

    blocked = preflight_candidate(candidate, card)

    assert blocked.licenses[0]["path"] == "LICENSE"
    assert {item["category"] for item in blocked.risk_findings} >= {
        "network",
        "credentials",
    }
    assert blocked.authority_required == (
        "credentials",
        "executable-resources",
        "network",
        "tool:Bash",
    )
    assert "explicit authority approval required" in blocked.blockers[-1]

    allowed = preflight_candidate(
        candidate,
        card,
        allow_executable=True,
        allow_network=True,
        allow_credentials=True,
        allowed_tools=("Bash",),
    )
    assert allowed.blockers == ()
    receipt = write_preflight_report(allowed, tmp_path / "reports")
    assert receipt.name == f"{allowed.report_id.removeprefix('sha256:')}.json"


def test_preflight_blocks_incomplete_references_even_with_authority(tmp_path):
    candidate = resolve_local_candidate(
        str(_skill(tmp_path / "candidate", broken_reference=True))
    )
    card = build_intent_card(candidate)
    report = preflight_candidate(
        candidate,
        card,
        allow_executable=True,
        allow_network=True,
        allow_credentials=True,
        allowed_tools=("Bash",),
    )
    assert any("missing local references" in blocker for blocker in report.blockers)


def test_named_attestations_are_opaque_digest_bound_artifacts(tmp_path):
    artifact = tmp_path / "scanner.json"
    artifact.write_text('{"result":"clean"}\n', encoding="utf-8")
    records = load_attestations((f"vendor-scan={artifact}",))
    assert records[0].name == "vendor-scan"
    assert records[0].artifact_digest == digest_path(artifact)
    assert records[0].semantics == "opaque-third-party-artifact"


def test_quarantine_changes_future_authority_without_rewriting_history(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "state"))
    package_digest = "sha256:" + "a" * 64
    first = set_quarantine(
        package_digest,
        quarantined=True,
        reason="upstream revocation",
        actor="test",
        effective_at="2026-07-31T12:00:00Z",
    )
    first_path = (
        tmp_path / "state" / "quarantine-events" / f"{first.event_id[7:]}.json"
    )
    original = first_path.read_bytes()

    with pytest.raises(LifecycleError, match="is quarantined"):
        assert_not_quarantined(package_digest)

    second = set_quarantine(
        package_digest,
        quarantined=False,
        reason="reviewed",
        actor="test",
        effective_at="2026-07-31T13:00:00Z",
    )
    assert second.previous_event_id == first.event_id
    assert quarantine_status(package_digest)["status"] == "available"
    assert first_path.read_bytes() == original
    assert_not_quarantined(package_digest)


def test_quarantine_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "state"))
    event = set_quarantine(
        "sha256:" + "b" * 64,
        quarantined=True,
        reason="plan",
        actor="test",
        effective_at="2026-07-31T12:00:00Z",
        dry_run=True,
    )
    assert event.action == "quarantine"
    assert not (tmp_path / "state" / "quarantine.json").exists()
