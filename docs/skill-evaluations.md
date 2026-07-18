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

[dimensions]
harness = "isolated-executor"
model = "frozen-model-coordinate"
profile = "procedure-profile@1"
baseline_implementation = "raw-agent@1"

[origin]
schema = "spindle.procedure-origin/v1"
milton_finding_id = "fnd_..."
milton_revision_id = "fnr_..."
chip_candidate_id = "chc_..."
chip_receipt_id = "ccr_..."

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

`[origin]` is optional for ordinary evaluations and required for a procedure
candidate entering the promotion loop. When present, all four coordinates are
required and `[dimensions]` must also name `profile`, `model`, `harness`, and
`baseline_implementation`. Spindle computes the variant implementation from the
exact skill SHA-256. The evaluation receipt therefore carries complete baseline
and variant implementation/profile/model/harness tuples rather than relying on
a label such as “skill on” or “skill off.”

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

The result must contain:

```json
{
  "score": 0.82,
  "passed": true,
  "skill_invoked": true,
  "evidence": {"grader": "exact-regression-check", "receipt": "..."},
  "metrics": {"false_positives": 0, "corrections": 1},
  "artifacts": [".../agent-output.txt"]
}
```

`score` is bounded to `[0, 1]`. `skill_invoked` must match the arm. Evidence must
be non-empty. A timeout, nonzero exit, malformed result, missing evidence, or arm
mismatch is an evaluation error and blocks promotion. Receipts retain input hashes,
pair order, exit state, duration, stdout/stderr hashes, scores, metrics, and the
promotion decision without copying full potentially sensitive transcripts.

## Promotion Gate

Every selected case runs once per arm. Case order and within-pair arm order are
randomized from the manifest seed. The runner should freeze model, harness, tools,
and budgets across arms; put those coordinates in `[dimensions]` and its own
evidence.

Development cases are for fixture and grader iteration. They never make a run
promotion-eligible. Promotion requires:

1. the configured minimum number of held-out cases;
2. complete baseline/variant pairs with no runner errors;
3. variant mean score strictly above baseline when `min_improvement = 0`, or at
   least the configured positive improvement otherwise.

The held-out mean is a necessary gate, not a complete adoption decision. Review
case-level regressions, costs, latency, and human correction time before binding.
Rejected and null receipts remain evidence for that exact skill hash.

### DES design evaluations

A design skill or blend must bind its evidence to the semantic DES profile as
well as Spindle's implementation/model/harness tuple. If `[dimensions]` contains
either `des_profile` or `surface_mode`, Spindle fails closed unless all of these
string coordinates are present:

```toml
[dimensions]
des_profile = "des-public-data-frontier-c936737aee21"
surface_mode = "public-data"
harness = "codex"
model_tier = "frontier"
requested_model = "gpt-5"
served_model = "gpt-5"
capabilities = "browser,visual-input"
```

The four valid modes are `operator`, `public-data`, `editorial`, and `marketing`.
The runner should also carry the DES audit receipt path in result `evidence` and
put screenshots or grader artifacts in `artifacts`. Requested and served model
remain separate because a routed or fallback call is a different evaluation.
Capabilities are part of the context: a harness without browser or visual input
cannot make the same effectiveness claim as one that rendered and saw the work.

Use at least one held-out case per relevant mode; do not average a marketing win
over an operator regression. Promotion still requires review of case-level
safety, fabrication, accessibility, overflow, latency, tokens, and human
correction time rather than only the mean score.

For a procedure candidate, `record_evaluated_binding` is the binding boundary.
It refuses an ineligible evaluation and records the exact evaluation receipt,
origin, variant tuple, and baseline tuple in binding history.
`record_promotion` then emits an idempotent
`spindle.procedure-promotion/v1` receipt tying that evaluated tuple to the
binding coordinate. Spindle owns both decisions. An external finding system can
observe the receipts, but cannot evaluate or bind on Spindle's behalf.

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
