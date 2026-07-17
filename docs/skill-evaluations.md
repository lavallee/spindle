# Behavioral Skill Evaluations

## Boundary

`spindle bind` answers “can this surface load the intended skill without losing
resources or guardrails?” `spindle eval` answers “does this skill improve behavior
on this task family for this model and harness?” A bind is never an effectiveness
claim.

Spindle does not call a model provider directly. A manifest names an argv runner.
The runner may delegate to an isolated executor, a benchmark harness, or a local
deterministic fixture. It receives one case and one arm at a time through environment variables
and writes one structured result. No shell is involved.

## Manifest

```toml
schema_version = 1
id = "diagnosing-bugs-v1"
skill = "diagnosing-bugs"
skill_path = "candidate/SKILL.md"
runner = ["python", "runner.py"]
timeout_seconds = 900
seed = 20260711
min_held_out_cases = 10
min_improvement = 0.05
receipt_dir = "receipts"

[acceptance]
required_variant_gates = ["task_closed", "facts_correct", "no_harm"]

[dimensions]
harness = "isolated-executor"
model = "frozen-model-coordinate"

[[cases]]
id = "known-regression"
split = "development"
fixture = "fixtures/known-regression.json"
tags = ["diagnosis"]

[[cases]]
id = "unseen-regression"
split = "held_out"
fixture = "fixtures/unseen-regression.json"
tags = ["diagnosis"]
```

Paths resolve relative to the manifest. Case IDs are unique. A valid manifest has
at least `min_held_out_cases`; `eval validate` exits `2` when the contract is
structurally valid but the held-out bar is not met.

## Runner Contract

Spindle sets:

| Variable | Meaning |
|---|---|
| `SPINDLE_EVAL_ID` | manifest evaluation ID |
| `SPINDLE_EVAL_RUN_ID` | receipt/run coordinate |
| `SPINDLE_EVAL_CASE_ID` | current case |
| `SPINDLE_EVAL_SPLIT` | `development` or `held_out` |
| `SPINDLE_EVAL_ARM` | `baseline` or `variant` |
| `SPINDLE_EVAL_FIXTURE` | absolute fixture path |
| `SPINDLE_EVAL_SKILL_ENABLED` | `0` or `1` |
| `SPINDLE_EVAL_SKILL_FILE` | candidate path for the variant; empty for baseline |
| `SPINDLE_EVAL_RESULT_PATH` | where the runner must write JSON |
| `SPINDLE_EVAL_DIMENSIONS` | JSON object copied from `[dimensions]` |
| `SPINDLE_EVAL_REQUIRED_VARIANT_GATES` | JSON array copied from `[acceptance].required_variant_gates` |

The result must contain the ordinary fields below and, when acceptance gates are
configured, the `gates` object shown:

```json
{
  "score": 0.82,
  "passed": true,
  "skill_invoked": true,
  "evidence": {"grader": "exact-regression-check", "receipt": "..."},
  "gates": {
    "task_closed": {"passed": true, "evidence": "completion signal observed"},
    "facts_correct": {"passed": true, "evidence": {"checked_claims": 4}},
    "no_harm": {"passed": true, "evidence": "no misleading claims found"}
  },
  "metrics": {"false_positives": 0, "corrections": 1},
  "artifacts": [".../agent-output.txt"]
}
```

`score` is bounded to `[0, 1]`. `skill_invoked` must match the arm. Evidence must
be non-empty. A timeout, nonzero exit, malformed result, missing evidence, or arm
mismatch is an evaluation error and blocks promotion. Receipts retain input hashes,
pair order, exit state, duration, stdout/stderr hashes, scores, metrics, and the
promotion decision without copying full potentially sensitive transcripts.
`passed` is runner-supplied diagnostic evidence; promotion uses the comparative
score and any explicitly configured required gates.

`[acceptance]` is optional. When `required_variant_gates` is present, every named
gate in every held-out variant result must contain a Boolean `passed` value and
non-empty `evidence`. Missing, malformed, or false required gates block promotion
by conjunction regardless of score. All gates passing does not promote by itself;
the variant must still clear the comparative held-out improvement bar. Baseline
and development gate outcomes remain diagnostic receipt evidence, not independent
promotion blockers.

Gate names, meanings, and oracles belong to the runner or skill package. This
mechanism lets factual, harm, or task-closure failures remain non-negotiable without
inventing a universal UX score. A model critic may surface risks for a runner to
check, but it cannot override a deterministic gate or claim that synthetic feedback
was observed user behavior. See [`examples/outcome-uat/eval.toml`](../examples/outcome-uat/eval.toml)
for a deterministic calibration example.

## Promotion Gate

Every selected case runs once per arm. Case order and within-pair arm order are
randomized from the manifest seed. The runner should freeze model, harness, tools,
and budgets across arms; put those coordinates in `[dimensions]` and its own
evidence.

Development cases are for fixture and grader iteration. They never make a run
promotion-eligible. Promotion requires:

1. the configured minimum number of held-out cases;
2. complete baseline/variant pairs with no runner errors;
3. every configured required gate passing on every held-out variant;
4. variant mean score strictly above baseline when `min_improvement = 0`, or at
   least the configured positive improvement otherwise.

The held-out mean is a necessary gate, not a complete adoption decision. Review
case-level regressions, costs, latency, and human correction time before binding.
Rejected and null receipts remain evidence for that exact skill hash.

## System Adapters

- **Execution adapter:** creates an isolated worktree/session per arm, captures
  executable red/green and verifier receipts, waits for the terminal outcome, and
  writes the normalized result JSON.
- **Telemetry adapter:** records requested/served model, skill/harness dimensions,
  tokens, cache, latency, cost, and later outcome. The runner places stable call or
  campaign IDs in `evidence`.
- **Intent ledger:** stores the experiment intent and final decision. Raw trajectories
  and per-case scratch state stay with the executor.
- **SkillOpt:** consumes these held-out scores through `command_scorer`; optimizing
  prose and evaluating behavior therefore use the same gate.

## Initial Task Families

- **Diagnosis:** exact symptom reproduction, loop determinism, pre-edit hypothesis
  testing, regression sensitivity, completion, time, and cost.
- **Code review:** true findings, severity, false positives, standards versus spec
  attribution, missed seeded issues, and correction time. Include clean controls.
- **Handoff:** repeated exploration, missing decisions, invalid assumptions, time to
  first correct action, and eventual completion in a fresh context.
