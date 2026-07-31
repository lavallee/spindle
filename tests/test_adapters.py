"""Harness-neutral projection, activation, and delegation receipts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spindle.adapters import (
    ACTIVATION_RECEIPT_SCHEMA,
    CLAUDE_CODE_ADAPTER,
    CODEX_ADAPTER,
    DELEGATION_RECEIPT_SCHEMA,
    ActivationEvidence,
    AdapterDescriptor,
    AdapterError,
    EvidenceAuthority,
    EvidenceFact,
    PermissionDenial,
    ProjectionMode,
    ProjectionPlan,
    RealizationReference,
    write_activation_receipt,
    write_delegation_receipt,
)
from spindle.realization import SessionProfile, realize_skill

CORE = """\
---
name: vault-review
description: Inspect a vault.
---

# Vault review

Inspect the requested vault evidence.
"""

MANIFEST = """\
schema_version = 1

[[profile]]
id = "claude-opus-review"
overlay = "overlays/claude-opus-review.md"

[profile.match]
harness = "claude"
model = "claude-opus-5"
role = "reviewer"

[[profile]]
id = "claude-sonnet-explore"

[profile.match]
harness = "claude"
model = "claude-sonnet-5"
role = "explorer"
"""


def _skill(tmp_path: Path) -> Path:
    root = tmp_path / "vault-review"
    (root / "overlays").mkdir(parents=True)
    (root / "SKILL.md").write_text(CORE)
    (root / "spindle-realization.toml").write_text(MANIFEST)
    (root / "overlays" / "claude-opus-review.md").write_text(
        "Use vault tools rather than filesystem tools.\n"
    )
    return root


def _realize_pair(tmp_path: Path):
    root = _skill(tmp_path)
    parent = realize_skill(
        root,
        SessionProfile(
            session_id="session-1",
            harness="claude",
            requested_model="claude-opus-5",
            served_model="claude-opus-5",
            role="reviewer",
        ),
        store_root=tmp_path / "realizations",
        receipt_root=tmp_path / "realization-receipts",
    )
    child = realize_skill(
        root,
        SessionProfile(
            session_id="session-1",
            harness="claude",
            requested_model="claude-sonnet-5",
            served_model="claude-sonnet-5",
            role="explorer",
        ),
        store_root=tmp_path / "realizations",
        receipt_root=tmp_path / "realization-receipts",
    )
    return parent, child


def _fact(value, authority: EvidenceAuthority, source: str) -> EvidenceFact:
    return EvidenceFact(value=value, authority=authority, source=source)


def _plan(result, *, agent_id: str, model: str, parent_agent_id: str | None = None):
    return ProjectionPlan(
        session_id="session-1",
        agent_id=agent_id,
        parent_agent_id=parent_agent_id,
        harness="claude",
        adapter_id=CLAUDE_CODE_ADAPTER.id,
        mode=(
            ProjectionMode.SKILL_PATH
            if parent_agent_id is None
            else ProjectionMode.AGENT_INSTRUCTIONS
        ),
        target="agent-local-skill" if parent_agent_id is None else "agent-prompt",
        realization=RealizationReference.from_result(result),
        requested_model=_fact(model, EvidenceAuthority.REQUESTED, "task-router"),
        configured_model=_fact(model, EvidenceAuthority.CONFIGURED, "agent-definition"),
        configured_harness_build=_fact(
            "2.1.220", EvidenceAuthority.CONFIGURED, "adapter-environment"
        ),
        configured_role=_fact(
            "reviewer" if parent_agent_id is None else "explorer",
            EvidenceAuthority.CONFIGURED,
            "agent-definition",
        ),
        configured_tools=_fact(
            ("Agent",) if parent_agent_id is None else ("eno_search", "eno_get_note"),
            EvidenceAuthority.CONFIGURED,
            "agent-definition",
        ),
        configured_policy=_fact(
            "read-only", EvidenceAuthority.CONFIGURED, "agent-definition"
        ),
    )


def _evidence(
    raw_model: str,
    canonical_model: str,
    *,
    tools: tuple[str, ...],
    denials: tuple[PermissionDenial, ...] = (),
) -> ActivationEvidence:
    return ActivationEvidence(
        projection_loaded=_fact(True, EvidenceAuthority.OBSERVED, "route-marker"),
        served_model_raw=_fact(
            raw_model, EvidenceAuthority.OBSERVED, "agent-result.resolvedModel"
        ),
        served_model_canonical=_fact(
            canonical_model, EvidenceAuthority.DERIVED, "adapter:model-canonicalizer/v1"
        ),
        observed_harness_build=_fact(
            "2.1.220", EvidenceAuthority.OBSERVED, "session-init"
        ),
        effective_tools=_fact(tools, EvidenceAuthority.OBSERVED, "tool-events"),
        effective_policy=_fact(
            "read-only", EvidenceAuthority.OBSERVED, "permission-events"
        ),
        permission_denials=denials,
    )


def test_activation_receipt_separates_plan_from_runtime_evidence(tmp_path):
    parent_result, _ = _realize_pair(tmp_path)
    plan = _plan(parent_result, agent_id="parent", model="claude-opus-5")
    evidence = _evidence(
        "claude-opus-5[1m]",
        "claude-opus-5",
        tools=("Agent",),
    )

    receipt = write_activation_receipt(
        plan, evidence, receipt_root=tmp_path / "activation-receipts"
    )
    payload = json.loads(receipt.receipt_path.read_text())

    assert payload["schema"] == ACTIVATION_RECEIPT_SCHEMA
    assert payload["projection_plan"]["plan_id"] == plan.plan_id
    assert payload["projection_plan"]["model"]["requested"] == {
        "authority": "requested",
        "source": "task-router",
        "value": "claude-opus-5",
    }
    assert payload["projection_plan"]["model"]["configured"]["authority"] == (
        "configured"
    )
    assert (
        payload["projection_plan"]["configured"]["harness_build"]["authority"]
        == "configured"
    )
    assert payload["activation_evidence"]["harness"]["build"]["authority"] == (
        "observed"
    )
    observed = payload["activation_evidence"]["model"]
    assert observed["served_raw"] == {
        "authority": "observed",
        "source": "agent-result.resolvedModel",
        "value": "claude-opus-5[1m]",
    }
    assert observed["served_canonical"] == {
        "authority": "derived",
        "source": "adapter:model-canonicalizer/v1",
        "value": "claude-opus-5",
    }
    assert payload["projection_plan"]["realization"]["realization_receipt_id"] == (
        parent_result.receipt_id
    )
    assert payload["projection_plan"]["realization"]["package_digest"] == (
        parent_result.package_digest
    )


def test_identical_activation_is_content_addressed_and_never_rewritten(tmp_path):
    parent_result, _ = _realize_pair(tmp_path)
    plan = _plan(parent_result, agent_id="parent", model="claude-opus-5")
    evidence = _evidence("claude-opus-5", "claude-opus-5", tools=("Agent",))
    root = tmp_path / "activation-receipts"

    first = write_activation_receipt(plan, evidence, receipt_root=root)
    content = first.receipt_path.read_text()
    second = write_activation_receipt(plan, evidence, receipt_root=root)

    assert first.receipt_id == second.receipt_id
    assert first.receipt_path == second.receipt_path
    assert second.receipt_path.read_text() == content
    assert len(list(root.glob("*.json"))) == 1


def test_changed_runtime_observation_gets_a_different_receipt(tmp_path):
    parent_result, _ = _realize_pair(tmp_path)
    plan = _plan(parent_result, agent_id="parent", model="claude-opus-5")
    root = tmp_path / "activation-receipts"

    without_denial = write_activation_receipt(
        plan,
        _evidence("claude-opus-5", "claude-opus-5", tools=("Agent",)),
        receipt_root=root,
    )
    denial = PermissionDenial(
        capability="eno_search",
        reason="not allowed by session policy",
        evidence=_fact(True, EvidenceAuthority.OBSERVED, "permission-denial-event"),
    )
    with_denial = write_activation_receipt(
        plan,
        _evidence(
            "claude-opus-5",
            "claude-opus-5",
            tools=("Agent",),
            denials=(denial,),
        ),
        receipt_root=root,
    )

    assert without_denial.receipt_id != with_denial.receipt_id
    payload = json.loads(with_denial.receipt_path.read_text())
    assert (
        payload["activation_evidence"]["permission_denials"][0]["capability"]
        == "eno_search"
    )


def test_existing_receipt_tampering_fails_closed(tmp_path):
    parent_result, _ = _realize_pair(tmp_path)
    plan = _plan(parent_result, agent_id="parent", model="claude-opus-5")
    evidence = _evidence("claude-opus-5", "claude-opus-5", tools=("Agent",))
    root = tmp_path / "activation-receipts"
    receipt = write_activation_receipt(plan, evidence, receipt_root=root)
    payload = json.loads(receipt.receipt_path.read_text())
    payload["activation_evidence"]["projection_loaded"]["value"] = False
    receipt.receipt_path.write_text(json.dumps(payload))

    with pytest.raises(AdapterError, match="receipt store collision"):
        write_activation_receipt(plan, evidence, receipt_root=root)


def test_delegation_links_independent_parent_and_child_realizations(tmp_path):
    parent_result, child_result = _realize_pair(tmp_path)
    assert parent_result.package_digest == child_result.package_digest
    assert parent_result.realization_digest != child_result.realization_digest

    activation_root = tmp_path / "activation-receipts"
    parent = write_activation_receipt(
        _plan(parent_result, agent_id="parent", model="claude-opus-5"),
        _evidence("claude-opus-5[1m]", "claude-opus-5", tools=("Agent",)),
        receipt_root=activation_root,
    )
    child = write_activation_receipt(
        _plan(
            child_result,
            agent_id="child",
            parent_agent_id="parent",
            model="claude-sonnet-5",
        ),
        _evidence(
            "claude-sonnet-5",
            "claude-sonnet-5",
            tools=("eno_search", "eno_get_note"),
        ),
        receipt_root=activation_root,
    )

    delegation = write_delegation_receipt(
        "delegation-1",
        parent,
        [child],
        receipt_root=tmp_path / "delegation-receipts",
    )
    payload = json.loads(delegation.receipt_path.read_text())

    assert payload["schema"] == DELEGATION_RECEIPT_SCHEMA
    assert payload["parent"]["activation_receipt_id"] == parent.receipt_id
    assert payload["parent"]["realization_receipt_id"] == parent_result.receipt_id
    assert payload["children"][0]["activation_receipt_id"] == child.receipt_id
    assert payload["children"][0]["realization_receipt_id"] == child_result.receipt_id
    assert (
        payload["parent"]["package_digest"] == payload["children"][0]["package_digest"]
    )
    assert payload["parent"]["served_model_raw"]["value"] == "claude-opus-5[1m]"
    assert payload["children"][0]["served_model_canonical"]["value"] == (
        "claude-sonnet-5"
    )


def test_delegation_rejects_child_attached_to_another_parent(tmp_path):
    parent_result, child_result = _realize_pair(tmp_path)
    root = tmp_path / "activation-receipts"
    parent = write_activation_receipt(
        _plan(parent_result, agent_id="parent", model="claude-opus-5"),
        _evidence("claude-opus-5", "claude-opus-5", tools=("Agent",)),
        receipt_root=root,
    )
    child = write_activation_receipt(
        _plan(
            child_result,
            agent_id="child",
            parent_agent_id="someone-else",
            model="claude-sonnet-5",
        ),
        _evidence("claude-sonnet-5", "claude-sonnet-5", tools=("eno_search",)),
        receipt_root=root,
    )

    with pytest.raises(AdapterError, match="does not name parent"):
        write_delegation_receipt("bad", parent, [child], receipt_root=tmp_path / "d")


def test_plan_rejects_observation_masquerading_as_configuration(tmp_path):
    parent_result, _ = _realize_pair(tmp_path)
    with pytest.raises(AdapterError, match="configured_model evidence authority"):
        ProjectionPlan(
            session_id="session-1",
            agent_id="parent",
            harness="claude",
            adapter_id=CLAUDE_CODE_ADAPTER.id,
            mode=ProjectionMode.SKILL_PATH,
            target="agent-local-skill",
            realization=RealizationReference.from_result(parent_result),
            configured_model=_fact(
                "claude-opus-5", EvidenceAuthority.OBSERVED, "runtime-event"
            ),
        )


def test_activation_rejects_configured_fact_masquerading_as_observation():
    with pytest.raises(AdapterError, match="served_model_raw evidence"):
        ActivationEvidence(
            projection_loaded=_fact(True, EvidenceAuthority.OBSERVED, "route-marker"),
            served_model_raw=_fact(
                "claude-opus-5", EvidenceAuthority.CONFIGURED, "agent-definition"
            ),
        )


def test_descriptor_rejects_an_unsupported_projection_mode(tmp_path):
    _, child_result = _realize_pair(tmp_path)
    plan = _plan(
        child_result,
        agent_id="child",
        parent_agent_id="parent",
        model="claude-sonnet-5",
    )
    descriptor = AdapterDescriptor(
        id=CLAUDE_CODE_ADAPTER.id,
        harness="claude",
        projection_modes=(ProjectionMode.SKILL_PATH,),
        runtime_evidence=("served-model",),
    )

    with pytest.raises(AdapterError, match="does not support"):
        descriptor.validate_plan(plan)


def test_reference_descriptors_are_capability_contracts_not_launch_commands():
    assert CLAUDE_CODE_ADAPTER.harness == "claude"
    assert CODEX_ADAPTER.harness == "codex"
    assert set(CLAUDE_CODE_ADAPTER.projection_modes) == {
        ProjectionMode.SKILL_PATH,
        ProjectionMode.AGENT_INSTRUCTIONS,
    }
    assert set(CODEX_ADAPTER.projection_modes) == {
        ProjectionMode.SKILL_PATH,
        ProjectionMode.AGENT_INSTRUCTIONS,
    }
    assert all("--" not in item for item in CLAUDE_CODE_ADAPTER.runtime_evidence)
    assert all("--" not in item for item in CODEX_ADAPTER.runtime_evidence)
