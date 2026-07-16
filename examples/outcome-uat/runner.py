"""Deterministic runner for the outcome-based UAT calibration example."""

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
    "responsive_layout",
    "delivery_budget",
)
OUTCOME_FIELDS = ("purpose", "answer", "proof_target", "next_action")


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


fixture = obj(
    json.loads(Path(os.environ["SPINDLE_EVAL_FIXTURE"]).read_text(encoding="utf-8")),
    "fixture",
)
if fixture.get("schema_version") != 1:
    raise ValueError("fixture schema_version must be 1")
arm = os.environ["SPINDLE_EVAL_ARM"]
task = obj(fixture.get("task"), "task")
baseline = obj(fixture.get("baseline"), "baseline")
candidate = obj(fixture.get(arm), arm)
task_id = text(task.get("id"), "task.id")
task_name = text(task.get("name"), "task.name")
completion_signal = text(task.get("completion_signal"), "task.completion_signal")

states = seq(candidate.get("states"), "states")
if not states:
    raise ValueError("states must not be empty")
states_by_id: dict[str, dict[str, Any]] = {}
for index, raw in enumerate(states, 1):
    state = obj(raw, f"states[{index}]")
    state_id = text(state.get("id"), f"states[{index}].id")
    if state_id in states_by_id:
        raise ValueError(f"duplicate state id: {state_id}")
    text(state.get("route"), f"states[{index}].route")
    visible = seq(state.get("visible"), f"states[{index}].visible")
    if not visible or not all(isinstance(item, str) and item.strip() for item in visible):
        raise ValueError(f"states[{index}].visible must contain text")
    seq(state.get("signals", []), f"states[{index}].signals")
    states_by_id[state_id] = state

loop = obj(candidate.get("loop"), "loop")
critic = obj(loop.get("critic"), "loop.critic")
rounds = critic.get("rounds")
if isinstance(rounds, bool) or not isinstance(rounds, int):
    raise ValueError("loop.critic.rounds must be an integer")
critic_findings = seq(critic.get("findings"), "loop.critic.findings")
critic_violations: list[str] = []
expected_rounds = 1 if arm == "variant" else 0
if rounds != expected_rounds:
    critic_violations.append(f"expected {expected_rounds} round, observed {rounds}")
if critic.get("role") != "risk-finder-only":
    critic_violations.append("critic role exceeded risk-finder-only")
expected_basis = "simulated-not-observed" if arm == "variant" else "not-run"
if critic.get("behavior_basis") != expected_basis:
    critic_violations.append(f"behavior_basis must be {expected_basis}")
unknown_critic_fields = sorted(
    set(critic) - {"rounds", "role", "behavior_basis", "findings"}
)
if unknown_critic_fields:
    critic_violations.append(
        "forbidden critic fields: " + ", ".join(unknown_critic_fields)
    )
for index, raw_finding in enumerate(critic_findings, 1):
    if not isinstance(raw_finding, dict):
        critic_violations.append(f"finding {index} must be an object")
        continue
    if set(raw_finding) != {"risk", "evidence"}:
        critic_violations.append(
            f"finding {index} fields must be exactly risk and evidence"
        )
        continue
    if not all(
        isinstance(raw_finding[field], str) and raw_finding[field].strip()
        for field in ("risk", "evidence")
    ):
        critic_violations.append(f"finding {index} risk and evidence must be text")

if arm == "variant":
    repairs = loop.get("repair_passes")
    if loop.get("generated") is not True:
        raise ValueError("variant loop must record generation")
    if isinstance(repairs, bool) or not isinstance(repairs, int) or not 0 <= repairs <= 1:
        raise ValueError("repair_passes must be zero or one")
    if loop.get("reran_hard_gates") is not True or loop.get("stopped") is not True:
        raise ValueError("variant loop must rerun the hard gates and stop")

same_task = candidate.get("task_id") == task_id
completion_states = [
    state["id"] for state in states if completion_signal in state.get("signals", [])
]
baseline_states = seq(baseline.get("states"), "baseline.states")
baseline_task_closed = any(
    isinstance(state, dict) and completion_signal in state.get("signals", [])
    for state in baseline_states
)
baseline_surface = text(baseline.get("surface_id"), "baseline.surface_id")
surface = text(candidate.get("surface_id"), f"{arm}.surface_id")
real_replacement = None
if arm == "variant":
    real_replacement = (
        candidate.get("replacement_for") == baseline_surface
        and surface != baseline_surface
        and candidate.get("states") != baseline.get("states")
    )

facts = seq(candidate.get("facts"), "facts")
fact_failures: list[str] = []
for index, raw in enumerate(facts, 1):
    fact = obj(raw, f"facts[{index}]")
    claim = text(fact.get("claim"), f"facts[{index}].claim")
    if not isinstance(fact.get("source"), str) or not fact["source"].strip() or fact.get("matches") is not True:
        fact_failures.append(claim)

access = obj(candidate.get("accessibility"), "accessibility")
serious = seq(access.get("serious_violations"), "accessibility.serious_violations")
harm = obj(candidate.get("harm"), "harm")
misleading = seq(harm.get("misleading_claims"), "harm.misleading_claims")
chart_crimes = seq(harm.get("invalid_visual_encodings"), "harm.invalid_visual_encodings")

interactions = seq(candidate.get("interactions"), "interactions")
baseline_interactions = seq(baseline.get("interactions"), "baseline.interactions")
new_interactions: list[dict[str, Any]] = []
invalid_interactions: list[str] = []
purposes: list[str] = []
outcomes: list[dict[str, str]] = []
for index, raw in enumerate(interactions, 1):
    interaction = obj(raw, f"interactions[{index}]")
    interaction_id = text(interaction.get("id"), f"interactions[{index}].id")
    from_state = text(interaction.get("from_state"), f"interactions[{index}].from_state")
    to_state = text(interaction.get("to_state"), f"interactions[{index}].to_state")
    if from_state not in states_by_id or to_state not in states_by_id:
        invalid_interactions.append(interaction_id)
    if interaction.get("new") is True:
        new_interactions.append(interaction)
        purpose = interaction.get("claimed_purpose")
        destination = states_by_id.get(to_state, {})
        outcome = destination.get("outcome")
        if not isinstance(purpose, str) or not purpose.strip() or not isinstance(outcome, dict):
            invalid_interactions.append(interaction_id)
            continue
        try:
            normalized = {field: text(outcome.get(field), f"{to_state}.outcome.{field}") for field in OUTCOME_FIELDS}
        except ValueError:
            invalid_interactions.append(interaction_id)
            continue
        purposes.append(purpose.strip())
        outcomes.append(normalized)
outcome_signatures = [json.dumps(outcome, sort_keys=True) for outcome in outcomes]
added_action_burden = max(0, len(interactions) - len(baseline_interactions))
added_burden_earned = added_action_burden == 0 or not baseline_task_closed

responsive = obj(candidate.get("responsive_layout"), "responsive_layout")
desktop = obj(responsive.get("desktop"), "responsive_layout.desktop")
mobile = obj(responsive.get("mobile"), "responsive_layout.mobile")
responsive_passed = (
    desktop.get("contained") is True
    and desktop.get("horizontal_overflow_px") == 0
    and mobile.get("contained") is True
    and mobile.get("horizontal_overflow_px") == 0
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
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
delivery_passed = transferred <= max_transfer and rendered <= max_render

raw_gates: dict[str, tuple[bool, Any]] = {
    "task_closed": (
        bool(same_task and completion_states and (arm == "baseline" or real_replacement is True)),
        {
            "same_task": same_task,
            "real_replacement": real_replacement if arm == "variant" else "not-applicable",
            "completion_signal": completion_signal,
            "observed_in_states": completion_states,
        },
    ),
    "facts_correct": (not fact_failures, {"claims_checked": len(facts), "failed_claims": fact_failures}),
    "accessibility": (
        access.get("keyboard_path_complete") is True and not serious,
        {"keyboard_path_complete": access.get("keyboard_path_complete") is True, "serious_violations": serious},
    ),
    "no_harm": (
        not misleading and not chart_crimes,
        {"misleading_claims": misleading, "invalid_visual_encodings": chart_crimes},
    ),
    "earned_interaction": (
        not invalid_interactions
        and len(set(purposes)) == len(new_interactions)
        and len(set(outcome_signatures)) == len(new_interactions)
        and added_burden_earned,
        # A candidate may replace an action or add one to close a task the
        # baseline could not close. It may not add work to an already-closed task.
        # This is separate from sibling-choice differentiation above.
        {
            "new_choices": [item["id"] for item in new_interactions],
            "claimed_purposes": purposes,
            "distinct_effective_outcomes": len(set(outcome_signatures)),
            "effective_outcomes": outcomes,
            "invalid_interactions": sorted(set(invalid_interactions)),
            "baseline_task_closed": baseline_task_closed,
            "baseline_actions": len(baseline_interactions),
            "candidate_actions": len(interactions),
            "added_action_burden": added_action_burden,
            "added_burden_earned": added_burden_earned,
            "explanation": (
                f"new choices: {len(new_interactions)}; claimed purposes: "
                f"{len(set(purposes))}; distinct effective outcomes: "
                f"{len(set(outcome_signatures))}"
            ),
        },
    ),
    "critic_bounded": (
        not critic_violations,
        {
            "rounds": rounds,
            "role": critic.get("role"),
            "behavior_basis": critic.get("behavior_basis"),
            "findings_checked": len(critic_findings),
            "violations": critic_violations,
            "authority": "cannot alter deterministic gates",
        },
    ),
    "responsive_layout": (
        responsive_passed,
        {"desktop": desktop, "mobile": mobile, "reflow_observed": responsive.get("reflow_observed"), "task_order_preserved": responsive.get("task_order_preserved")},
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
gates = {name: {"passed": passed, "evidence": evidence} for name, (passed, evidence) in raw_gates.items()}
if tuple(gates) != REQUIRED_GATES or any(not gate["evidence"] for gate in gates.values()):
    raise ValueError("runner did not produce all required gate evidence")

superficial = obj(candidate.get("superficial_checks"), "superficial_checks")
if not superficial or not all(isinstance(value, bool) for value in superficial.values()):
    raise ValueError("superficial_checks must be a non-empty boolean object")
score = sum(superficial.values()) / len(superficial)
result = {
    "score": score,
    "passed": all(gate["passed"] for gate in gates.values()),
    "skill_invoked": arm == "variant",
    "gates": gates,
    "evidence": {
        "grader": "deterministic-outcome-uat",
        "grader_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "task": {"id": task_id, "name": task_name},
        "surface": surface,
        "captured_states": states,
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
Path(os.environ["SPINDLE_EVAL_RESULT_PATH"]).write_text(json.dumps(result), encoding="utf-8")
