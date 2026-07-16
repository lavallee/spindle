---
name: outcome-uat
description: Evaluate one interface change against the real task it replaces, with deterministic hard checks and one bounded repair pass.
---

# Outcome-based UAT

Evaluate a replacement, not a pile of interface parts.

## 1. Name the same task

Write down one task in plain language, the current surface that handles it, and
one observable completion signal. Use that exact task and signal for baseline
and candidate. If the candidate sits beside the old surface without changing
the task path, it is not yet a replacement.

## 2. Generate and exercise the replacement

Generate one bounded candidate. Run the task from its real entry point on both
baseline and candidate. Capture each consequential state: route, action, visible
result, and completion signal. Keep routes, viewport, data, and test conditions
fixed across the two runs.

## 3. Run the hard checks

Each check has its own evidence and passes or fails. Never average these checks
into a preference score.

- `task_closed`: the candidate is a real replacement and reaches the named
  completion signal for the same task.
- `facts_correct`: every presented factual claim matches its cited evidence.
- `accessibility`: the task has a complete keyboard path and no serious known
  accessibility violation.
- `no_harm`: the candidate introduces no misleading claim or invalid visual
  encoding.
- `earned_interaction`: each added choice produces a meaningfully distinct
  effective outcome: purpose, answer, proof target, and next action. Distinct
  URLs or DOM states do not rescue choices that all do the same thing. Do not
  add actions to a task the simpler baseline already closes.
- `critic_bounded`: run exactly one simulated, risk-and-visible-evidence-only
  critique. The critic has no approval, override, score, predicted-behavior, or
  observed-user authority.
- `responsive_layout`: desktop and mobile observations contain the task without
  horizontal overflow and preserve its useful order while reflowing.
- `delivery_budget`: captured transferred and rendered bytes stay within the
  task-specific limits. A multi-megabyte landing page does not pass because it
  eventually renders.

Any failed hard check rejects the current candidate even when routes work,
controls have labels, screenshots look polished, or a model prefers it.

## 4. Use one bounded cold critic

Show one cold critic the named task, captured states, and hard-check evidence.
Ask only for evidence-backed risks or missing states. The critic must not speak
as a parent, predict user sentiment, invent facts, produce a universal UX score,
or override a hard failure.

## 5. Repair once, rerun, and stop

Make at most one bounded repair that addresses a cited risk. Rerun the same task
and every hard check. Stop after that rerun:

- keep the candidate only if all required checks pass;
- otherwise reject it and carry the exact failure into a new, separately scoped
  loop.

Do not keep prompting the critic until it approves.
