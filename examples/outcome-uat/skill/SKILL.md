---
name: outcome-uat
description: Evaluate one interface change against the real task it replaces, with recorded execution evidence and one bounded independent repair pass.
---

# Outcome-based UAT

Evaluate a replacement, not a pile of interface parts.

## 1. Freeze the task and its evidence boundary

Name one task, its current surface, the real entry route, and one observable
completion signal. Use that exact task for baseline and candidate. Seal the
source semantics that constrain material claims before generating the candidate.
For example, aggregate unlinked observations cannot support a linked-individual
claim. The product adapter owns those domain semantics; do not invent a universal
classifier.

## 2. Execute the whole journey

Run baseline and candidate from the real entry with the same scripted product
harness, data, viewport, and test conditions. Retain a contiguous action trace.
Capture every consequential state and hash its route, visible content,
foreground targets, material claims, and completion signals.

`task_closed` requires the executed trace—not a declared URL—to end at a
foregrounded terminal capture containing the completion signal. A working entry
page fails if its destination is dead, misleading, inaccessible, or unexecuted.

## 3. Run conjunctive hard checks

Each check has evidence and passes or fails. Never average these checks into a
preference score.

- `task_closed`: the same task executes from its real entry to the foregrounded
  completion target on a real replacement.
- `facts_correct`: every material claim in every capture is covered exactly once
  and its sealed source supports that claim kind.
- `accessibility`: the task has a complete keyboard path and no serious known
  accessibility violation.
- `no_harm`: the candidate introduces no unsupported material claim,
  misleading claim, or invalid visual encoding.
- `earned_interaction`: each added choice produces a distinct effective outcome:
  purpose, answer, proof target, and next action. Do not add work to a task the
  simpler baseline already closes.
- `critic_bounded`: one cold critic receives the task plus randomized,
  anonymized captures. Receipt hashes bind the declared input set; the product
  adapter retains prompt, model, order, and raw-input custody. The critic acts as
  a risk finder, remains independent of the producer, and has no approval,
  score, observed-user, or override authority.
- `critic_repair`: findings name IDs, visible artifact locators, and deterministic
  postconditions; one repair addresses every finding. Changed consequential
  hashes prove the capture changed, and postconditions prove this calibration's
  cited risk was addressed before the adapter recomputes the journey and gates.
- `responsive_layout`: desktop and mobile observations contain the task without
  horizontal overflow and preserve useful order while reflowing.
- `delivery_budget`: captured transferred and rendered bytes remain within the
  task-specific limits.

Any failed hard check rejects the candidate even when routes work, controls have
labels, screenshots look polished, or a model prefers it.

## 4. Use one independent cold critic

Give a critic that did not produce the candidate the task plus randomized,
anonymized pre-repair captures. Withhold the expected winner, implementation
story, and fixture class; for paired screens, blind the labels and inspect both
orders. Record capture hashes for the receipt's declared input set, and retain
the prompt, model, order, and raw input as product-owned custody evidence. Ask
only for risks grounded in a named artifact and visible locator. The critic must
not speak as a user, predict sentiment, invent facts, produce a universal UX
score, or override a hard failure. If independent critique is unavailable,
record self-evaluation and fail promotion.

## 5. Repair once, recompute, and stop

Make at most one bounded repair. Map it to finding IDs and affected artifacts.
Changed consequential hashes prove that cited artifacts changed; deterministic
postconditions prove that the cited risks were addressed. Execute the full
post-repair journey and recompute every hard check; a Boolean saying that a rerun
happened is not evidence.

Keep the candidate only if every required gate passes. Otherwise reject it and
carry the exact failure into a separately scoped loop. Do not prompt the critic
again merely to obtain approval.

The bundled runner calibrates deterministic receipts. It does not drive a
browser or verify external capture custody. Real product evaluation must use a
product-owned adapter to execute and capture the full journeys above, then supply
that evidence to this contract.
