# Outcome-based UAT example

This package is a deterministic calibration example for evaluating an interface
change as a replacement for a real task, rather than as a collection of pages,
controls, or screenshots.

The loop is intentionally short:

1. Name one task, its existing surface, and the exact signal that closes it.
2. Generate a real replacement and run the same task on both surfaces.
3. Capture the exact states reached and run hard checks for task closure, facts,
   accessibility, harm, responsive layout, delivery size, and whether every
   added interaction earns its place.
4. Give one cold critic the captured result. The critic may identify an
   evidence-backed risk; it may not pretend to be a user or override a failed
   hard check.
5. Make at most one repair, rerun the same checks, and stop with either a
   candidate or a rejection.

`eval.toml` requires all eight hard checks on every held-out variant. A high mean
score cannot average away one of those failures.

## Run it

From the Spindle repository root:

```console
spindle eval validate examples/outcome-uat/eval.toml
spindle eval run examples/outcome-uat/eval.toml
```

The included held-out set is a calibration set, not a promotion claim. Its
`meaningless-identical-choices` control is expected to block promotion. That
candidate resolves, fits on mobile, has labeled controls, and scores perfectly
on the superficial rubric. It still fails because three distinct routes produce
the same answer, proof target, and next action, and do not answer the named task.
The receipt should report `required-variant-gates-failed` even though the held-out
mean improves. A second negative control is an 11.2 MB landing page that otherwise
looks functional; it is rejected by the task-specific delivery budget.
The third negative control gives the critic an approval role and a synthetic
parent reaction; `critic_bounded` rejects that overreach without letting the
critic change any other gate.

## Fixture shape

Each JSON fixture names one task and supplies frozen baseline and variant
observations. The runner derives the gates; fixtures do not declare their own
verdicts.

- `states` record the route, visible result, and exact completion signals.
- `interactions` record state-to-state effects. New choices must produce distinct
  effective outcomes: purpose, answer, proof target, and next action. Different
  URLs, anchors, or DOM states do not make an interaction useful by themselves.
- `facts`, `accessibility`, and `harm` contain deterministic observations.
- `responsive_layout` records desktop/mobile containment and task-order reflow.
- `delivery` is checked against the task's transferred/rendered byte limits.
- `critic_bounded` requires one risk-and-evidence-only simulated critique round;
  it rejects approval, override, score, or observed-user fields.
- `superficial_checks` produce the compatibility score. They are deliberately
  insufficient for acceptance.
- `loop` records the single cold-critic round, no more than one repair, the
  rerun, and the stop.

Replace the deterministic fixture adapter with a browser or product harness for
a real evaluation, but keep the task, state, hard-gate, and stopping contracts.
The model critic remains a bounded risk finder; it is not synthetic parent
research and it does not get a vote over deterministic evidence.
