# Runtime skill realization

Status: implemented resolver, activation/delegation receipts, and certified
reference-adapter boundary in Spindle 0.2, 2026-07-31.

Spindle keeps one immutable skill package and realizes its smallest evaluated
instruction surface separately for each parent or child agent. Installation and
session routing are distinct operations:

```text
bind/lease: package revision -> desired blend -> immutable package
realize:    immutable package + actual session coordinate -> immutable realization
activate:   realization + harness observation -> per-agent activation receipt
```

The implementation does not ask a model to identify itself and never rewrites a
repository-wide `SKILL.md`. A harness or task router supplies the coordinate.
Spindle selects at most one overlay, writes a content-addressed package, and emits
an audit receipt.

## Package contract

A runtime-aware skill adds `spindle-realization.toml` beside its invariant
`SKILL.md`:

```text
review/
  SKILL.md
  spindle-realization.toml
  overlays/
    codex-sol-review.md
    codex-terra-explore.md
  references/
    rubric.md
```

```toml
schema_version = 1

[[profile]]
id = "codex-sol-review"
overlay = "overlays/codex-sol-review.md"

[profile.match]
harness = "codex"
model = "gpt-5.6-sol"
effort = "high"
role = "reviewer"

[[profile]]
id = "codex-terra-explore"
overlay = "overlays/codex-terra-explore.md"

[profile.match]
harness = "codex"
model = "gpt-5.6-terra"
effort = "medium"
role = "explorer"
```

Supported match axes are:

- `harness`
- `model`, meaning the actually served model
- `effort`
- `role`
- `harness_build`
- `toolset_digest`
- `policy_digest`
- `memory_policy`

Each value may be a string or an array of exact strings. Every profile must
constrain `harness`. An omitted axis is an explicit portability claim for that
profile, not an inference that the axis does not matter.

The most specific matching profile wins. `priority` breaks a tie only among
equally specific profiles. If a tie remains, no profile matches, the served model
is unknown, or the requested and served models differ, Spindle discloses only the
invariant core and records an unresolved result.

The `overlay` field is optional. A matched profile without an overlay is an
evaluated claim that the invariant core is sufficient for that tuple. Overlay
files must remain inside the reserved `overlays/` directory. Neither the manifest
nor unselected overlays are copied into the realized package.

## Session command

The task router chooses the model; Spindle follows that decision:

```bash
spindle realize /path/to/review \
  --session-id parent-42 \
  --harness codex \
  --requested-model gpt-5.6-sol \
  --served-model gpt-5.6-sol \
  --effort high \
  --role reviewer \
  --strict
```

When requested and served model are known to be identical, `--model` is shorthand
for both fields:

```bash
spindle realize review \
  --session-id child-17 \
  --harness codex \
  --model gpt-5.6-terra \
  --effort medium \
  --role explorer \
  --json
```

`review` may be an installed Spindle skill name or a path to a skill directory.
Session adapters may supply the coordinate through `SPINDLE_SESSION_ID`,
`SPINDLE_HARNESS`, `SPINDLE_REQUESTED_MODEL`, `SPINDLE_SERVED_MODEL`,
`SPINDLE_EFFORT`, `SPINDLE_AGENT_ROLE`, `SPINDLE_HARNESS_BUILD`,
`SPINDLE_TOOLSET_DIGEST`, `SPINDLE_POLICY_DIGEST`, and
`SPINDLE_MEMORY_POLICY`; explicit flags take precedence. `--strict` returns exit
code 2 after writing the conservative receipt unless an evaluated profile
matched. Invalid manifests fail closed with exit code 1.

By default, realized packages and receipts land under:

```text
$SPINDLE_HOME/realizations/<digest>/<skill>/
$SPINDLE_HOME/realization-receipts/<receipt-id>.json
```

`SPINDLE_REALIZATIONS_DIR` and `SPINDLE_REALIZATION_RECEIPTS_DIR` can move those
stores. Realization paths are content-addressed and immutable. Different agents
may safely resolve different overlays concurrently; identical realizations reuse
one directory.

## Harness adapter boundary

The portable CLI produces an immutable skill path and receipt. A harness adapter
is responsible for making that path available only to the corresponding agent
session:

1. choose the agent role, model, effort, tools, and permissions;
2. obtain or verify the served model;
3. call `spindle realize` for each eligible adopted or leased skill;
4. load the returned paths into that agent's skill configuration; and
5. retain the receipts with the delegation or run record.

An adapter must not retarget the repository's installed skill symlink. That would
reintroduce the parent/child race this design removes.

`spindle.adapters` formalizes this boundary without launching a harness:

- `ProjectionPlan` links one agent-local projection target to the package,
  realization, and realization receipt that produced it;
- `ActivationEvidence` records whether the projection loaded, the raw and
  canonical served-model identities, observed harness build, effective tools
  and policy, and observed permission denials; and
- activation and delegation receipts content-address those facts and retain the
  transitive package, realization, and parent/child links.

Every evidence value names its authority. `requested` and `configured` are
intent; `observed` comes from a harness event or result; `derived` is a
reproducible interpretation such as model-id canonicalization. The raw served
model is never replaced by its canonical form. A delegation receipt joins
independently activated agents rather than allowing a child to inherit its
parent's realization.

The Claude Code and Codex reference descriptors advertise portable projection
modes (`skill-path` and `agent-instructions`) and required runtime evidence. They
are capability descriptions, not claims that a particular harness build has
passed conformance. Surface adapters own launch syntax and event parsing.

If the harness changes a session's model or effort, it must call the resolver
again before the skill is reused. Existing content-addressed paths remain valid
historical artifacts, but the earlier receipt no longer describes the active
session coordinate.

The portable resolver still stops before harness invocation; launch syntax and
event parsing remain adapter responsibilities. Spindle 0.2 supplies reference
Claude Code and Codex adapters, startup wrappers/native hooks, fail-closed
capability matrices, and build-specific certification. The checked evidence
certifies Claude Code 2.1.220 and Codex CLI 0.146.0 rather than treating a harness
name as an evergreen capability claim.

By default, the additional receipts land under:

```text
$SPINDLE_HOME/activation-receipts/<receipt-id>.json
$SPINDLE_HOME/delegation-receipts/<receipt-id>.json
```

`SPINDLE_ACTIVATION_RECEIPTS_DIR` and
`SPINDLE_DELEGATION_RECEIPTS_DIR` can move those stores.

## Binding compatibility

`spindle bind` continues to select and install the package once. Harness dialect
rendering may still produce a content-addressed installed package. When a skill
contains `spindle-realization.toml`, the legacy repository-wide model-density
transform is skipped for that skill, and the binding record lists it under
`runtime_profiled_skills`. Skills without a runtime manifest keep the existing
bind-time model behavior.

This permits gradual migration: a distribution can contain legacy static skills
and session-realized skills in the same blend.

## Promotion evidence

Adding a profile asserts that its match coordinate has been evaluated. The
`spindle eval matrix` contract can retain the corresponding no-skill,
invariant-core, candidate-overlay, incumbent, and ablation arms with separate
runtime gates, repeated held-out results, non-inferiority bounds, and hard floors.
The resolver still does not infer evidence from the presence or brevity of an
overlay; it executes the declared mapping and records what happened. Adoption and
profile curation remain explicit decisions over the resulting receipts.
