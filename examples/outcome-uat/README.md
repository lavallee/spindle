# Outcome-based UAT example

This is deterministic receipt calibration for evaluating an interface change as
a replacement for one real task. The bundled runner does not drive a browser or
verify external capture custody. A real product adapter must execute and capture
the interface, then supply the recorded evidence to this contract.

The loop is deliberately short:

1. Freeze one task, real entry, completion target, and sealed source semantics.
2. Execute baseline and candidate through the same full journey.
3. Hash consequential captures and run conjunctive task, fact, accessibility,
   harm, interaction, layout, delivery, and critic gates.
4. Give one independent cold critic the task plus randomized, anonymized
   pre-repair captures; record their hashes in the receipt. The product adapter
   owns proof of what the critic actually received.
5. Repair once at most, then recompute the journey and hard gates from changed
   post-repair evidence.

`eval.toml` requires all nine hard checks on every held-out variant. A high mean
score cannot average away one failed task family.

## Run it

From the Spindle repository root:

```console
spindle eval validate examples/outcome-uat/eval.toml
spindle eval run examples/outcome-uat/eval.toml
```

## Negative controls

Every held-out candidate scores perfectly on the superficial rubric. Promotion
still blocks on deliberately different failure families:

- `meaningless-identical-choices`: accessible, responsive choices lead to the
  same effective result and never close the selected task.
- `oversized-payload`: a functional landing transfers 11.2 MB.
- `critic-overreach`: the critic claims approval and observed parent reaction.
- `aggregate-destination-overclaim`: the entry journey executes, but its
  destination calls aggregate, unlinked observations the same individuals and a
  no-op repair leaves that capture unchanged.
- `declared-route-without-executed-destination`: the route and completion state
  are declared, but the action trace records a failed navigation.
- `critic-self-review-noop-repair`: producer and critic are the same actor and
  the affected artifact hash does not change.

`aggregate-destination-repaired.json` is the positive twin: the same adapter,
task, pre-repair capture, and critic finding pass after the destination changes
to a source-supported aggregate limitation and the full journey is recomputed.

## Fixture contract

Fixtures are schema version 2 frozen calibration artifacts, not product claims.

- `states` contain routes, visible content, foreground targets, material claims,
  completion signals, and therefore deterministic capture hashes.
- `journey` records a contiguous event trace from `entry_route` to the
  foregrounded terminal capture. A completion signal in an unexecuted state is
  insufficient; the product adapter, not this calibration runner, owns execution
  and capture custody.
- `source_semantics` is sealed and lists the claim kinds each source supports.
  `claims` must cover every material captured claim exactly once.
- `interactions` are graded by effective outcome, not URL or DOM difference.
- The product adapter gives the critic randomized, anonymized captures plus the
  task and retains prompt, model, order, and raw-input custody.
  `critic.input_capture_hashes` must equal every pre-repair capture hash; this
  binds the receipt's declared input set, not what a model actually saw. Findings
  require IDs, artifact IDs, visible locators, and an exact
  `visible_text_absent` postcondition in this calibration.
- `repair` maps every finding to unique changed artifacts. Consequential hashes
  prove change; deterministic postconditions prove the cited calibration finding
  was addressed. The runner recomputes the post-repair journey and gate-input
  hash; fixtures cannot assert a rerun with a Boolean.

The example intentionally contains no browser dependency and no general semantic
model. Replace the frozen receipt fixture with a product-owned scripted harness
and domain oracle while retaining this evidence contract. Model critique remains
a simulated risk-finding input, never observed user research or approval
evidence.
