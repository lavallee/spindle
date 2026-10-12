"""Deterministic receipt-calibration runner for the outcome-UAT example."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


REQUIRED_GATES = (
    "task_closed",
    "facts_correct",
    "accessibility",
    "no_harm",
    "earned_interaction",
    "critic_bounded",
    "critic_repair",
    "responsive_layout",
    "delivery_budget",
)
OUTCOME_FIELDS = ("purpose", "answer", "proof_target", "next_action")
STATE_FIELDS = {"id", "route", "visible", "signals", "foreground", "material_claims"}
INTERACTION_FIELDS = {"id", "from_state", "to_state", "new"}
JOURNEY_FIELDS = {
    "executor",
    "entry_state",
    "events",
    "terminal_state",
    "foreground_target",
}
EVENT_FIELDS = {
    "id",
    "interaction_id",
    "from_state",
    "to_state",
    "action",
    "result",
}
CLAIM_FIELDS = {"artifact_id", "text", "source", "kind"}
CRITIC_FIELDS = {
    "rounds",
    "actor_id",
    "role",
    "behavior_basis",
    "input_capture_hashes",
    "findings",
}
FINDING_FIELDS = {
    "id",
    "artifact_id",
    "locator",
    "risk",
    "evidence",
    "postcondition",
}
POSTCONDITION_FIELDS = {"type", "value"}


def obj(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def seq(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def closed_fields(
    value: dict[str, Any],
    *,
    required: set[str],
    allowed: set[str],
    name: str,
) -> None:
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - allowed)
    if missing:
        raise ValueError(f"{name} missing field(s): {', '.join(missing)}")
    if unknown:
        raise ValueError(f"{name} unknown field(s): {', '.join(unknown)}")


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def parse_states(
    raw_states: Any,
    name: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, str]]:
    states = seq(raw_states, name)
    if not states:
        raise ValueError(f"{name} must not be empty")
    by_id: dict[str, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    for index, raw in enumerate(states, 1):
        state = obj(raw, f"{name}[{index}]")
        closed_fields(
            state,
            required=STATE_FIELDS,
            allowed=STATE_FIELDS | {"outcome"},
            name=f"{name}[{index}]",
        )
        state_id = text(state.get("id"), f"{name}[{index}].id")
        if state_id in by_id:
            raise ValueError(f"duplicate state id: {state_id}")
        text(state.get("route"), f"{name}[{index}].route")
        visible = seq(state.get("visible"), f"{name}[{index}].visible")
        if not visible or not all(
            isinstance(item, str) and item.strip() for item in visible
        ):
            raise ValueError(f"{name}[{index}].visible must contain text")
        for field in ("signals", "foreground", "material_claims"):
            values = seq(state.get(field, []), f"{name}[{index}].{field}")
            if not all(isinstance(item, str) and item.strip() for item in values):
                raise ValueError(f"{name}[{index}].{field} must contain text")
        visible_text = "\n".join(visible)
        for claim in state.get("material_claims", []):
            if claim not in visible_text:
                raise ValueError(
                    f"{name}[{index}] material claim is not visible: {claim}"
                )
        outcome = state.get("outcome")
        if outcome is not None:
            outcome = obj(outcome, f"{name}[{index}].outcome")
            closed_fields(
                outcome,
                required=set(OUTCOME_FIELDS),
                allowed=set(OUTCOME_FIELDS),
                name=f"{name}[{index}].outcome",
            )
            for field in OUTCOME_FIELDS:
                text(outcome.get(field), f"{name}[{index}].outcome.{field}")
        by_id[state_id] = state
        hashes[state_id] = canonical_sha256(state)
    return states, by_id, hashes


def parse_interactions(
    raw_interactions: Any,
    name: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    interactions = seq(raw_interactions, name)
    by_id: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(interactions, 1):
        interaction = obj(raw, f"{name}[{index}]")
        closed_fields(
            interaction,
            required=INTERACTION_FIELDS,
            allowed=INTERACTION_FIELDS | {"claimed_purpose"},
            name=f"{name}[{index}]",
        )
        interaction_id = text(interaction.get("id"), f"{name}[{index}].id")
        if interaction_id in by_id:
            raise ValueError(f"duplicate interaction id: {interaction_id}")
        text(interaction.get("from_state"), f"{name}[{index}].from_state")
        text(interaction.get("to_state"), f"{name}[{index}].to_state")
        if not isinstance(interaction.get("new"), bool):
            raise ValueError(f"{name}[{index}].new must be boolean")
        if "claimed_purpose" in interaction:
            text(
                interaction.get("claimed_purpose"),
                f"{name}[{index}].claimed_purpose",
            )
        by_id[interaction_id] = interaction
    return interactions, by_id


def journey_result(
    raw_journey: Any,
    *,
    states_by_id: dict[str, dict[str, Any]],
    state_hashes: dict[str, str],
    interactions_by_id: dict[str, dict[str, Any]],
    entry_route: str,
    completion_signal: str,
    name: str,
) -> tuple[bool, dict[str, Any], set[str]]:
    journey = obj(raw_journey, name)
    closed_fields(
        journey,
        required=JOURNEY_FIELDS,
        allowed=JOURNEY_FIELDS,
        name=name,
    )
    violations: list[str] = []
    executor = journey.get("executor")
    if executor not in {"scripted-browser", "product-harness"}:
        violations.append("executor must be scripted-browser or product-harness")
    entry_state = text(journey.get("entry_state"), f"{name}.entry_state")
    terminal_state = text(journey.get("terminal_state"), f"{name}.terminal_state")
    foreground_target = text(
        journey.get("foreground_target"), f"{name}.foreground_target"
    )
    if entry_state not in states_by_id:
        violations.append(f"entry state does not exist: {entry_state}")
    elif states_by_id[entry_state]["route"] != entry_route:
        violations.append(
            f"entry route is {states_by_id[entry_state]['route']!r}, "
            f"expected {entry_route!r}"
        )
    current = entry_state
    visited = [entry_state]
    event_ids: set[str] = set()
    successful_interaction_ids: set[str] = set()
    events = seq(journey.get("events"), f"{name}.events")
    for index, raw in enumerate(events, 1):
        event = obj(raw, f"{name}.events[{index}]")
        closed_fields(
            event,
            required=EVENT_FIELDS,
            allowed=EVENT_FIELDS,
            name=f"{name}.events[{index}]",
        )
        event_id = text(event.get("id"), f"{name}.events[{index}].id")
        event_valid = True
        if event_id in event_ids:
            violations.append(f"duplicate event id: {event_id}")
            event_valid = False
        event_ids.add(event_id)
        interaction_id = text(
            event.get("interaction_id"),
            f"{name}.events[{index}].interaction_id",
        )
        from_state = text(event.get("from_state"), f"{name}.events[{index}].from_state")
        to_state = text(event.get("to_state"), f"{name}.events[{index}].to_state")
        text(event.get("action"), f"{name}.events[{index}].action")
        if from_state != current:
            violations.append(
                f"event {event_id} starts at {from_state}, current state is {current}"
            )
            event_valid = False
        if event.get("result") != "succeeded":
            violations.append(f"event {event_id} did not succeed")
            event_valid = False
        interaction = interactions_by_id.get(interaction_id)
        if interaction is None:
            violations.append(
                f"event {event_id} references missing interaction {interaction_id}"
            )
            event_valid = False
        elif (
            interaction["from_state"] != from_state
            or interaction["to_state"] != to_state
        ):
            violations.append(
                f"event {event_id} does not match interaction {interaction_id}"
            )
            event_valid = False
        if to_state not in states_by_id:
            violations.append(f"event {event_id} reaches missing state {to_state}")
            event_valid = False
        if event_valid:
            successful_interaction_ids.add(interaction_id)
        current = to_state
        visited.append(to_state)
    credited_interactions = {
        interaction_id
        for interaction_id, interaction in interactions_by_id.items()
        if interaction.get("new") is True
    }
    if not events and credited_interactions:
        violations.append(
            "zero-event journey cannot close while new interactions claim credit"
        )
    if terminal_state != current:
        violations.append(
            f"declared terminal {terminal_state} is not executed terminal {current}"
        )
    terminal = states_by_id.get(terminal_state)
    if terminal is None:
        violations.append(f"terminal state does not exist: {terminal_state}")
        terminal_hash = None
    else:
        terminal_hash = state_hashes[terminal_state]
        if completion_signal not in terminal.get("signals", []):
            violations.append(
                f"terminal state lacks completion signal {completion_signal}"
            )
        if foreground_target not in terminal.get("foreground", []):
            violations.append(f"terminal state does not foreground {foreground_target}")
    evidence = {
        "recorded_executor_claim": executor,
        "entry_route": entry_route,
        "visited_states": visited,
        "terminal_state": terminal_state,
        "terminal_capture_sha256": terminal_hash,
        "foreground_target": foreground_target,
        "trace_sha256": canonical_sha256(journey),
        "successful_interaction_ids": sorted(successful_interaction_ids),
        "violations": violations,
    }
    return not violations, evidence, successful_interaction_ids


def semantic_result(
    candidate: dict[str, Any],
    *,
    states_by_id: dict[str, dict[str, Any]],
    source_semantics: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    semantic_hash = canonical_sha256(source_semantics)
    supported: dict[str, set[str]] = {}
    failures: list[dict[str, str]] = []
    for source, raw in source_semantics.items():
        semantics = obj(raw, f"task.source_semantics.{source}")
        kinds = seq(semantics.get("supports"), f"{source}.supports")
        if semantics.get("sealed") is not True:
            raise ValueError(f"source semantics must be sealed: {source}")
        if not kinds or not all(
            isinstance(kind, str) and kind.strip() for kind in kinds
        ):
            raise ValueError(
                f"source semantics must list supported claim kinds: {source}"
            )
        supported[source] = set(kinds)

    required = {
        (state_id, claim)
        for state_id, state in states_by_id.items()
        for claim in state.get("material_claims", [])
    }
    covered: list[tuple[str, str]] = []
    claims = seq(candidate.get("claims"), "claims")
    for index, raw in enumerate(claims, 1):
        claim = obj(raw, f"claims[{index}]")
        closed_fields(
            claim,
            required=CLAIM_FIELDS,
            allowed=CLAIM_FIELDS,
            name=f"claims[{index}]",
        )
        artifact_id = text(claim.get("artifact_id"), f"claims[{index}].artifact_id")
        claim_text = text(claim.get("text"), f"claims[{index}].text")
        source = text(claim.get("source"), f"claims[{index}].source")
        kind = text(claim.get("kind"), f"claims[{index}].kind")
        key = (artifact_id, claim_text)
        covered.append(key)
        state = states_by_id.get(artifact_id)
        if state is None:
            failures.append({"claim": claim_text, "reason": "capture is missing"})
        elif claim_text not in "\n".join(state["visible"]):
            failures.append({"claim": claim_text, "reason": "claim is not visible"})
        elif state.get("outcome") and source != state["outcome"]["proof_target"]:
            failures.append(
                {
                    "claim": claim_text,
                    "reason": (
                        f"claim source {source} does not match outcome proof target "
                        f"{state['outcome']['proof_target']}"
                    ),
                }
            )
        if source not in supported:
            failures.append({"claim": claim_text, "reason": "source is not sealed"})
        elif kind not in supported[source]:
            failures.append(
                {
                    "claim": claim_text,
                    "reason": f"{source} does not support claim kind {kind}",
                }
            )
    covered_set = set(covered)
    for artifact_id, claim_text in sorted(required - covered_set):
        failures.append(
            {
                "claim": claim_text,
                "reason": f"material claim in {artifact_id} is uncovered",
            }
        )
    for artifact_id, claim_text in sorted(covered_set - required):
        failures.append(
            {
                "claim": claim_text,
                "reason": f"claim is not declared material in {artifact_id}",
            }
        )
    if len(covered) != len(covered_set):
        failures.append(
            {"claim": "duplicate", "reason": "claim coverage is duplicated"}
        )
    return not failures, {
        "source_semantics_sha256": semantic_hash,
        "material_claims": len(required),
        "claims_checked": len(claims),
        "failures": failures,
    }


fixture = obj(
    json.loads(Path(os.environ["SPINDLE_EVAL_FIXTURE"]).read_text(encoding="utf-8")),
    "fixture",
)
if fixture.get("schema_version") != 2:
    raise ValueError("fixture schema_version must be 2")
arm = os.environ["SPINDLE_EVAL_ARM"]
task = obj(fixture.get("task"), "task")
baseline = obj(fixture.get("baseline"), "baseline")
candidate = obj(fixture.get(arm), arm)
task_id = text(task.get("id"), "task.id")
task_name = text(task.get("name"), "task.name")
entry_route = text(task.get("entry_route"), "task.entry_route")
completion_signal = text(task.get("completion_signal"), "task.completion_signal")
source_semantics = obj(task.get("source_semantics"), "task.source_semantics")
producer_id = text(candidate.get("producer_id"), f"{arm}.producer_id")

states, states_by_id, state_hashes = parse_states(candidate.get("states"), "states")
interactions, interactions_by_id = parse_interactions(
    candidate.get("interactions"), "interactions"
)
journey_passed, journey_evidence, successful_interaction_ids = journey_result(
    candidate.get("journey"),
    states_by_id=states_by_id,
    state_hashes=state_hashes,
    interactions_by_id=interactions_by_id,
    entry_route=entry_route,
    completion_signal=completion_signal,
    name="journey",
)

same_task = candidate.get("task_id") == task_id
baseline_states = seq(baseline.get("states"), "baseline.states")
baseline_surface = text(baseline.get("surface_id"), "baseline.surface_id")
surface = text(candidate.get("surface_id"), f"{arm}.surface_id")
real_replacement = None
if arm == "variant":
    real_replacement = (
        candidate.get("replacement_for") == baseline_surface
        and surface != baseline_surface
        and states != baseline_states
    )

_, baseline_states_by_id, baseline_state_hashes = parse_states(
    baseline_states, "baseline.states"
)
baseline_interactions, baseline_interactions_by_id = parse_interactions(
    baseline.get("interactions"), "baseline.interactions"
)
baseline_journey_passed, _, _ = journey_result(
    baseline.get("journey"),
    states_by_id=baseline_states_by_id,
    state_hashes=baseline_state_hashes,
    interactions_by_id=baseline_interactions_by_id,
    entry_route=entry_route,
    completion_signal=completion_signal,
    name="baseline.journey",
)

facts_passed, facts_evidence = semantic_result(
    candidate,
    states_by_id=states_by_id,
    source_semantics=source_semantics,
)

access = obj(candidate.get("accessibility"), "accessibility")
serious = seq(access.get("serious_violations"), "accessibility.serious_violations")
harm = obj(candidate.get("harm"), "harm")
misleading = seq(harm.get("misleading_claims"), "harm.misleading_claims")
chart_crimes = seq(
    harm.get("invalid_visual_encodings"), "harm.invalid_visual_encodings"
)

new_interactions: list[dict[str, Any]] = []
invalid_interactions: list[str] = []
purposes: list[str] = []
outcomes: list[dict[str, str]] = []
for interaction in interactions:
    interaction_id = interaction["id"]
    from_state = interaction["from_state"]
    to_state = interaction["to_state"]
    if from_state not in states_by_id or to_state not in states_by_id:
        invalid_interactions.append(interaction_id)
    if interaction.get("new") is True:
        new_interactions.append(interaction)
        purpose = interaction.get("claimed_purpose")
        destination = states_by_id.get(to_state, {})
        outcome = destination.get("outcome")
        if (
            not isinstance(purpose, str)
            or not purpose.strip()
            or not isinstance(outcome, dict)
        ):
            invalid_interactions.append(interaction_id)
            continue
        try:
            normalized = {
                field: text(outcome.get(field), f"{to_state}.outcome.{field}")
                for field in OUTCOME_FIELDS
            }
        except ValueError:
            invalid_interactions.append(interaction_id)
            continue
        purposes.append(purpose.strip())
        outcomes.append(normalized)
unexecuted_new_interactions = sorted(
    interaction["id"]
    for interaction in new_interactions
    if interaction["id"] not in successful_interaction_ids
)
outcome_signatures = [json.dumps(outcome, sort_keys=True) for outcome in outcomes]
added_action_burden = max(0, len(interactions) - len(baseline_interactions))
added_burden_earned = added_action_burden == 0 or not baseline_journey_passed

responsive = obj(candidate.get("responsive_layout"), "responsive_layout")
desktop = obj(responsive.get("desktop"), "responsive_layout.desktop")
mobile = obj(responsive.get("mobile"), "responsive_layout.mobile")
responsive_passed = (
    desktop.get("contained") is True
    and desktop.get("horizontal_overflow_px") == 0
    and desktop.get("required_fields_visible_without_undisclosed_action") is True
    and mobile.get("contained") is True
    and mobile.get("horizontal_overflow_px") == 0
    and mobile.get("required_fields_visible_without_undisclosed_action") is True
    and responsive.get("reflow_observed") is True
    and responsive.get("task_order_preserved") is True
)

budget = obj(task.get("delivery_budget"), "task.delivery_budget")
delivery = obj(candidate.get("delivery"), "delivery")
max_transfer = budget.get("max_transferred_bytes")
max_render = budget.get("max_rendered_bytes")
transferred = delivery.get("transferred_bytes")
rendered = delivery.get("rendered_bytes")
for value, name in (
    (max_transfer, "max_transferred_bytes"),
    (max_render, "max_rendered_bytes"),
    (transferred, "transferred_bytes"),
    (rendered, "rendered_bytes"),
):
    value = integer(value, name)
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
delivery_passed = transferred <= max_transfer and rendered <= max_render

loop = obj(candidate.get("loop"), "loop")
critic = obj(loop.get("critic"), "loop.critic")
critic_violations: list[str] = []
unknown_critic_fields = sorted(set(critic) - CRITIC_FIELDS)
if unknown_critic_fields:
    critic_violations.append(
        "forbidden critic fields: " + ", ".join(unknown_critic_fields)
    )
rounds = integer(critic.get("rounds"), "loop.critic.rounds")
expected_rounds = 1 if arm == "variant" else 0
if rounds != expected_rounds:
    critic_violations.append(f"expected {expected_rounds} round, observed {rounds}")
critic_actor_id = text(critic.get("actor_id"), "loop.critic.actor_id")
if arm == "variant" and critic_actor_id == producer_id:
    critic_violations.append("critic is not independent of producer")
if critic.get("role") != "risk-finder-only":
    critic_violations.append("critic role exceeded risk-finder-only")
expected_basis = "simulated-not-observed" if arm == "variant" else "not-run"
if critic.get("behavior_basis") != expected_basis:
    critic_violations.append(f"behavior_basis must be {expected_basis}")

repair_passes = integer(loop.get("repair_passes"), "loop.repair_passes")
if arm == "variant" and not 0 <= repair_passes <= 1:
    raise ValueError("repair_passes must be zero or one")
if arm == "baseline" and repair_passes != 0:
    raise ValueError("baseline repair_passes must be zero")

pre_states_by_id = states_by_id
pre_state_hashes = state_hashes
pre_journey_passed = journey_passed
if repair_passes == 1:
    _, pre_states_by_id, pre_state_hashes = parse_states(
        loop.get("pre_repair_states"), "loop.pre_repair_states"
    )
    pre_journey_passed, _, _ = journey_result(
        loop.get("pre_repair_journey"),
        states_by_id=pre_states_by_id,
        state_hashes=pre_state_hashes,
        interactions_by_id=interactions_by_id,
        entry_route=entry_route,
        completion_signal=completion_signal,
        name="loop.pre_repair_journey",
    )

input_hashes = seq(
    critic.get("input_capture_hashes"), "loop.critic.input_capture_hashes"
)
if not all(isinstance(value, str) and value.strip() for value in input_hashes):
    critic_violations.append("critic input capture hashes must contain text")
expected_input_hashes = sorted(pre_state_hashes.values()) if arm == "variant" else []
input_hashes_bound = sorted(input_hashes) == expected_input_hashes
if not input_hashes_bound:
    critic_violations.append("critic inputs do not bind every pre-repair capture hash")

critic_findings = seq(critic.get("findings"), "loop.critic.findings")
finding_ids: list[str] = []
finding_artifacts: dict[str, str] = {}
finding_postconditions: dict[str, tuple[str, str]] = {}
for index, raw_finding in enumerate(critic_findings, 1):
    if not isinstance(raw_finding, dict) or set(raw_finding) != FINDING_FIELDS:
        critic_violations.append(
            f"finding {index} fields must be exactly "
            + ", ".join(sorted(FINDING_FIELDS))
        )
        continue
    finding_id = text(raw_finding.get("id"), f"finding {index}.id")
    artifact_id = text(raw_finding.get("artifact_id"), f"finding {index}.artifact_id")
    locator = text(raw_finding.get("locator"), f"finding {index}.locator")
    text(raw_finding.get("risk"), f"finding {index}.risk")
    text(raw_finding.get("evidence"), f"finding {index}.evidence")
    postcondition = obj(
        raw_finding.get("postcondition"), f"finding {index}.postcondition"
    )
    closed_fields(
        postcondition,
        required=POSTCONDITION_FIELDS,
        allowed=POSTCONDITION_FIELDS,
        name=f"finding {index}.postcondition",
    )
    postcondition_type = text(
        postcondition.get("type"), f"finding {index}.postcondition.type"
    )
    postcondition_value = text(
        postcondition.get("value"), f"finding {index}.postcondition.value"
    )
    if postcondition_type != "visible_text_absent":
        critic_violations.append(
            f"finding {finding_id} postcondition type must be visible_text_absent"
        )
    if finding_id in finding_ids:
        critic_violations.append(f"duplicate finding id: {finding_id}")
    finding_ids.append(finding_id)
    finding_artifacts[finding_id] = artifact_id
    finding_postconditions[finding_id] = (
        postcondition_type,
        postcondition_value,
    )
    artifact = pre_states_by_id.get(artifact_id)
    if artifact is None:
        critic_violations.append(
            f"finding {finding_id} references missing artifact {artifact_id}"
        )
    elif locator not in "\n".join(artifact["visible"]):
        critic_violations.append(
            f"finding {finding_id} locator is absent from artifact {artifact_id}"
        )

repair_violations: list[str] = []
changed_artifacts: list[str] = []
addresses: list[str] = []
affected: list[str] = []
postconditions_satisfied: list[str] = []
if repair_passes == 1:
    repair = obj(loop.get("repair"), "loop.repair")
    if set(repair) != {"addresses", "affected_artifacts"}:
        repair_violations.append(
            "repair fields must be exactly addresses and affected_artifacts"
        )
    addresses = seq(repair.get("addresses"), "loop.repair.addresses")
    affected = seq(repair.get("affected_artifacts"), "loop.repair.affected_artifacts")
    if not finding_ids:
        repair_violations.append("repair requires at least one valid critic finding")
    if not all(isinstance(value, str) and value.strip() for value in addresses):
        repair_violations.append("repair addresses must contain finding ids")
    if len(addresses) != len(set(addresses)):
        repair_violations.append("repair addresses must be unique")
    if set(addresses) != set(finding_ids):
        repair_violations.append("repair must address every critic finding exactly")
    if not affected or not all(
        isinstance(value, str) and value.strip() for value in affected
    ):
        repair_violations.append("repair must name affected artifacts")
    if len(affected) != len(set(affected)):
        repair_violations.append("repair affected artifacts must be unique")
    for artifact_id in affected:
        before = pre_state_hashes.get(artifact_id)
        after = state_hashes.get(artifact_id)
        if before is None or after is None:
            repair_violations.append(
                f"affected artifact is missing before or after repair: {artifact_id}"
            )
        elif before == after:
            repair_violations.append(f"affected artifact did not change: {artifact_id}")
        else:
            changed_artifacts.append(artifact_id)
    unaddressed_artifacts = {
        finding_artifacts[finding_id]
        for finding_id in finding_ids
        if finding_id in finding_artifacts
    } - set(affected)
    if unaddressed_artifacts:
        repair_violations.append(
            "finding artifacts not changed: " + ", ".join(sorted(unaddressed_artifacts))
        )
    for finding_id, (postcondition_type, value) in finding_postconditions.items():
        artifact_id = finding_artifacts[finding_id]
        artifact = states_by_id.get(artifact_id)
        if artifact is None:
            repair_violations.append(
                f"finding {finding_id} post-repair artifact is missing: {artifact_id}"
            )
            continue
        visible_text = "\n".join(artifact["visible"])
        if postcondition_type == "visible_text_absent" and value in visible_text:
            repair_violations.append(
                f"finding {finding_id} postcondition failed: {value!r} remains "
                f"visible in {artifact_id}"
            )
        else:
            postconditions_satisfied.append(finding_id)
    if not pre_journey_passed:
        repair_violations.append(
            "critic did not inspect a completed pre-repair journey"
        )
    if not journey_passed:
        repair_violations.append("post-repair journey did not complete")
elif critic_findings:
    repair_violations.append("critic findings were not repaired")

post_gate_inputs = {
    "states": states,
    "journey": candidate.get("journey"),
    "claims": candidate.get("claims"),
    "accessibility": access,
    "harm": harm,
    "interactions": interactions,
    "responsive_layout": responsive,
    "delivery": delivery,
}

raw_gates: dict[str, tuple[bool, Any]] = {
    "task_closed": (
        bool(
            same_task
            and journey_passed
            and (arm == "baseline" or real_replacement is True)
        ),
        {
            "same_task": same_task,
            "real_replacement": (
                real_replacement if arm == "variant" else "not-applicable"
            ),
            "journey": journey_evidence,
        },
    ),
    "facts_correct": (facts_passed, facts_evidence),
    "accessibility": (
        access.get("keyboard_path_complete") is True and not serious,
        {
            "keyboard_path_complete": access.get("keyboard_path_complete") is True,
            "serious_violations": serious,
        },
    ),
    "no_harm": (
        facts_passed and not misleading and not chart_crimes,
        {
            "semantic_claim_failures": facts_evidence["failures"],
            "misleading_claims": misleading,
            "invalid_visual_encodings": chart_crimes,
        },
    ),
    "earned_interaction": (
        not invalid_interactions
        and not unexecuted_new_interactions
        and len(set(purposes)) == len(new_interactions)
        and len(set(outcome_signatures)) == len(new_interactions)
        and added_burden_earned,
        {
            "new_choices": [item["id"] for item in new_interactions],
            "claimed_purposes": purposes,
            "distinct_effective_outcomes": len(set(outcome_signatures)),
            "effective_outcomes": outcomes,
            "invalid_interactions": sorted(set(invalid_interactions)),
            "successful_interaction_ids": sorted(successful_interaction_ids),
            "unexecuted_new_interactions": unexecuted_new_interactions,
            "baseline_task_closed": baseline_journey_passed,
            "baseline_actions": len(baseline_interactions),
            "candidate_actions": len(interactions),
            "added_action_burden": added_action_burden,
            "added_burden_earned": added_burden_earned,
        },
    ),
    "critic_bounded": (
        not critic_violations,
        {
            "producer_id": producer_id,
            "critic_actor_id": critic_actor_id,
            "rounds": rounds,
            "role": critic.get("role"),
            "behavior_basis": critic.get("behavior_basis"),
            "input_capture_hashes_bound": input_hashes_bound,
            "findings_checked": len(critic_findings),
            "violations": critic_violations,
            "authority": "cannot alter deterministic gates",
        },
    ),
    "critic_repair": (
        not critic_violations and not repair_violations,
        {
            "repair_passes": repair_passes,
            "finding_ids": finding_ids,
            "addresses": addresses,
            "affected_artifacts": affected,
            "changed_artifacts": changed_artifacts,
            "postconditions_satisfied": postconditions_satisfied,
            "post_repair_journey_sha256": journey_evidence["trace_sha256"],
            "post_repair_gate_inputs_sha256": canonical_sha256(post_gate_inputs),
            "recomputed_by_runner": [
                "task_closed",
                "facts_correct",
                "accessibility",
                "no_harm",
                "earned_interaction",
                "responsive_layout",
                "delivery_budget",
            ],
            "violations": critic_violations + repair_violations,
        },
    ),
    "responsive_layout": (
        responsive_passed,
        {
            "desktop": desktop,
            "mobile": mobile,
            "reflow_observed": responsive.get("reflow_observed"),
            "task_order_preserved": responsive.get("task_order_preserved"),
        },
    ),
    "delivery_budget": (
        delivery_passed,
        {
            "transferred_bytes": transferred,
            "max_transferred_bytes": max_transfer,
            "rendered_bytes": rendered,
            "max_rendered_bytes": max_render,
        },
    ),
}
gates = {
    name: {"passed": passed, "evidence": evidence}
    for name, (passed, evidence) in raw_gates.items()
}
if tuple(gates) != REQUIRED_GATES or any(
    not gate["evidence"] for gate in gates.values()
):
    raise ValueError("runner did not produce all required gate evidence")

superficial = obj(candidate.get("superficial_checks"), "superficial_checks")
if not superficial or not all(
    isinstance(value, bool) for value in superficial.values()
):
    raise ValueError("superficial_checks must be a non-empty boolean object")
score = sum(superficial.values()) / len(superficial)
result = {
    "score": score,
    "passed": all(gate["passed"] for gate in gates.values()),
    "skill_invoked": arm == "variant",
    "gates": gates,
    "evidence": {
        "grader": "deterministic-receipt-calibration",
        "grader_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "task": {"id": task_id, "name": task_name},
        "surface": surface,
        "captured_states": states,
        "capture_hashes": state_hashes,
        "superficial_checks": superficial,
        "loop": loop,
    },
    "metrics": {
        "captured_states": len(states),
        "hard_gates_passed": sum(gate["passed"] for gate in gates.values()),
        "new_interactions": len(new_interactions),
        "distinct_effective_outcomes": len(set(outcome_signatures)),
    },
    "artifacts": [],
}
Path(os.environ["SPINDLE_EVAL_RESULT_PATH"]).write_text(
    json.dumps(result), encoding="utf-8"
)
