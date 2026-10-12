# Spindle vision

Status: implemented 0.x baseline and continuing product direction, 2026-07-31.

## The promise

Spindle makes agent skills understandable, reversible, current, and measurably
useful.

Today, adopting a skill usually means installing an artifact into an ambient
directory and hoping that:

- the current model notices it at the right time;
- its instructions still improve the current harness;
- its dependencies and permissions are acceptable;
- it composes with everything else the harness can see;
- the installed version is the version the user intended; and
- somebody will retest, update, and eventually retire it.

Spindle should replace that hope with an evidence-bearing lifecycle:

```text
discover -> inspect -> try -> borrow -> realize -> activate -> evaluate
                                                      |
                                           adopt, distill, or release
                                                      |
                                             update, disable, retire
```

The durable product promise is:

> A user can understand and temporarily use a skill in the environment they
> already have, know exactly what reached each agent, and adopt it only after it
> earns ongoing custody.

This broadens Spindle's original composition thesis without discarding it.
Composition remains the center of runtime correctness; the lifecycle makes that
correctness available before installation and maintainable afterward.

## The product Spindle is becoming

Spindle is a lifecycle and control plane for behavioral dependencies.

It is not merely:

- an installer;
- a public registry;
- a prompt optimizer;
- a harness-specific plugin manager; or
- a system that copies every discovered skill into every project.

It joins three planes that are commonly separate:

| Plane | Responsibility |
| --- | --- |
| Intent | Explain what outcome a skill is trying to change, when it applies, and what authority it needs. |
| Runtime | Compose the effective set, resolve exact versions, project one realization per agent, and reconcile harness discovery. |
| Evidence | Prove what loaded, what model and tools were effective, whether behavior improved, and when the claim became stale. |

The object under management is not just `SKILL.md`. It is a relationship among
an intent, an immutable package, a current environment, an authority grant, and
bounded evidence.

## Lifecycle model

Spindle should keep these records distinct:

```text
SourceRef
  -> PackageRevision
  -> IntentCard
  -> Lease or AdoptionRecord
  -> SurfaceBinding
  -> AgentRealization
  -> ProjectionPlan
  -> StartupReceipt and ActivationReceipt
  -> EvaluationClaim
```

Each answers a different question:

- **Source reference:** Where did this come from?
- **Package revision:** Which exact instructions and resources are under review?
- **Intent card:** What is it trying to change, and why might it fit here?
- **Lease:** Who may use it temporarily, where, for how long, and with what
  authority?
- **Adoption record:** Who accepted maintenance responsibility, at which pin and
  update policy?
- **Binding:** Which coherent set should this surface expose?
- **Realization:** What is the smallest evaluated instruction surface for this
  actual agent coordinate?
- **Projection plan:** How should the harness disclose that realization to this
  agent?
- **Startup and activation receipts:** What environment did the harness actually
  expose?
- **Evaluation claim:** Did the intervention help on this bounded task and
  runtime distribution?

Installation is therefore not the beginning of the lifecycle. It is one
possible implementation detail of an adoption record.

## Product principles

### Intent before artifact

Discovery results should be candidates, not install recommendations. Before a
skill receives authority, Spindle should explain its intended outcome, trigger
boundary, behavioral delta, contents, dependencies, context cost, provenance,
freshness, relevant evidence, and overlap with the current environment.

### Temporary before durable

`try` should create one disposable session lease. `borrow` should create a
renewable, expiring lease. Neither should create an update-bearing dependency.
`adopt` should be an explicit promotion of a useful lease into maintained desired
state.

### Desired state over ambient state

What happens to be present in a harness discovery directory is observed state,
not authorization. An adopted lock and active leases define what Spindle expects.
Startup reconciliation compares that expectation with the full effective
inventory.

### Own only what Spindle mutates

Spindle may repair or remove an obsolete projection only when an ownership
record proves that Spindle created it. A foreign skill, plugin, hook, real
directory, or unrecognized symlink is inventoried and checked for conflicts, but
never silently deleted.

### One package, many agent-local realizations

The installed package preserves identity, invariant intent, resources, and an
evaluated overlay library. Parent agents and subagents resolve independently
from their observed model, effort, role, harness build, toolset, and policy. No
session mutates a workspace-global "current" skill.

### Harness mechanics are not skill prose

Version checks, filesystem reconciliation, model routing, permissions, hook
protocols, and receipt writing are deterministic adapter responsibilities. Skill
instructions should contain only the behavioral delta and situated knowledge the
model needs.

### Evidence is bounded

"Works" always means for a named package digest, realization, model/harness
coordinate, task distribution, tool and permission envelope, and evaluation
budget. A new package or runtime coordinate does not inherit an old claim merely
because its name is unchanged.

### Updates are trials

An upstream update is a candidate revision. Spindle should inspect and test it
beside the incumbent before changing adopted state. Automatic fetching may be a
policy; automatic promotion should not be the default.

### Minimalism is deletion under evidence

As models and harnesses improve, Spindle should rebaseline no-skill behavior and
remove steering that has become redundant or harmful. Deterministic behavior
should move to tools or Chip. Rich references may remain progressively disclosed
even when the always-visible instruction residue becomes tiny or empty.

## Startup integrity

The effective skill environment must be correct before the first task depends on
it. Spindle needs a startup control loop, not just a bind command somebody might
remember to run.

### Expected state

A surface lock should resolve all durable and temporary inputs to immutable
identity:

- adopted source revision and package digest;
- distribution and package versions;
- channel and doctrine coordinates;
- active lease IDs and expiries;
- selected surface binding and realization rules;
- expected harness projection paths; and
- explicit conflict, shadow, or foreign-skill decisions.

A version string alone is insufficient. Editable packages and mutable tags must
also resolve to content identity.

### Observed state

Each harness adapter should inventory every relevant discovery scope it can
observe, including:

- repository and ancestor skill directories;
- user, administrator, system, and plugin scopes;
- enabled and disabled skills where the harness exposes them;
- names, paths, source ownership, content digests, and load errors;
- hooks, plugins, tools, MCP dependencies, and permission posture that change
  effective behavior; and
- opaque built-ins or managed state that can be named but not inspected.

The inventory should classify entries as:

| Class | Startup behavior |
| --- | --- |
| expected and Spindle-owned | Verify exact target and keep. |
| stale and Spindle-owned | Reconcile safely before discovery, or require restart if already loaded. |
| foreign and non-conflicting | Preserve and report as ambient context. |
| foreign and conflicting | Block strict startup or require an explicit shadow/allow decision. |
| ambiguous ownership | Preserve, fail closed for mutation, and request repair. |

"Lingering" must therefore mean either stale Spindle-owned state or unexpected
foreign state. Only the former is eligible for automatic removal.

### Bootstrap before hook

Native startup hooks are necessary but not a universal pre-discovery boundary.
The portable sequence should be:

```text
spindle launch / spindle bootstrap
  1. resolve desired state and active leases
  2. inspect the effective harness inventory
  3. reconcile only Spindle-owned projections
  4. detect foreign collisions and version drift
  5. write a content-addressed startup plan/receipt
  6. launch the harness

native SessionStart hook
  7. observe session id, source, model, permissions, and harness facts
  8. verify the startup receipt is still current
  9. inject only a concise success marker or actionable mismatch
 10. append session-start evidence
```

If the native hook discovers a change that may already have affected skill
discovery, it should not pretend that an in-place repair made the session clean.
It should report `restart-required` or stop the first turn where the harness
supports that decision. Harnesses with documented live reload may offer a
verified repair path, but that is an adapter capability, not a portable
assumption.

### Stable hooks, mutable state

The installed hook definition should be tiny and stable:

```text
SessionStart -> spindle bootstrap --hook <harness> --event session-start
SubagentStart -> spindle bootstrap --hook <harness> --event subagent-start
```

Pins, leases, and expected inventory belong in Spindle state, not generated hook
configuration. This keeps harness trust attached to a stable command rather than
forcing users to reapprove a hook whenever desired skills change.

Startup hooks should:

- run quickly and without network access by default;
- serialize mutation through a per-surface lock;
- tolerate duplicate or concurrent invocation;
- emit a short model-visible status and keep full detail in a receipt;
- rerun on resume, clear, compaction, and subagent start where supported;
- never print credentials or sensitive paths into model context; and
- expose `ok`, `warn`, `blocked`, and `restart-required` decisions separately.

Codex currently provides `SessionStart` and `SubagentStart` command hooks, makes
the active model and permission mode available to hooks, composes hooks from
multiple active sources, and requires trust for changed non-managed hook
definitions.[^codex-hooks] Claude Code provides `SessionStart`, `Setup`,
`SubagentStart`, configuration/instruction lifecycle events, and live change
detection for existing skill directories; creating a previously absent
top-level skill directory still requires restart.[^claude-hooks][^claude-skills]
These are valuable adapter seams, but the Spindle contract must remain correct
when a harness supports only a pre-launch wrapper and post-start observation.

## User experience

The primary surface should be the harness where the work is already happening,
backed by the CLI as a deterministic engine:

```bash
spindle harness setup --harness codex --here --dry-run
spindle harness setup --harness codex --here

# new Codex session:       $spindle show which skills are active and why
# new Claude Code session: /spindle try this review skill once
```

The operator skill must stay minimal. It should query a compact live context and
action contract rather than reproduce CLI documentation in model context. Its
job is to translate user intent into the smallest exact lifecycle action, preview
mutations, and refresh evidence afterward. Operator availability, native hook
configuration, observed startup, target-skill activation, authorization, and
behavior remain distinct gates.

Harness routing must follow the active session, not merely the union of inherited
environment variables: a Claude child launched from Codex legitimately exposes
both marker sets. Prefer active runtime evidence and fail closed to an explicit
adapter selection when it is unavailable.

The same lifecycle should remain directly addressable from the CLI:

```bash
spindle find "review this migration" --here
spindle inspect github:owner/repo#review --for "this migration"
spindle try github:owner/repo#review --harness claude --task-file task.md
spindle borrow github:owner/repo#review --here --until 2h

spindle inventory --effective --here
spindle why review --here
spindle health --here

spindle adopt lease-7e42 --scope repo
spindle update try review
spindle release lease-7e42
spindle retire review
```

Harness startup should normally be invisible when state is correct:

```text
Spindle: 6 expected skills verified; 1 foreign skill preserved; receipt 82cc…
```

It should be specific when state is not correct:

```text
Spindle blocked startup: expected review@sha256:91d…, observed stale owned
projection sha256:26a…; reconciled on disk, restart required before use.
Foreign skill `review` at ~/.agents/skills/review was preserved and conflicts by
name. Run `spindle why review --effective`.
```

## Trust and authority

Trying must be easier than installing without becoming a path around consent.

- Inspection and structural scanning do not execute bundled scripts.
- Unknown trials default to instruction-only, read-only authority.
- Tool, network, credential, and filesystem expansion is shown and granted
  separately.
- Hook installation is explicit and respects native harness trust review.
- Managed policies can prohibit local hooks, remote sources, executable skill
  resources, or automatic reconciliation.
- A clean scanner result is evidence, not proof of safety.
- Receipts record denials and mismatches; policy decides whether a run passes.

## What completion looks like

Spindle is fulfilling this vision when a user can move from an intent to a
temporary, correctly loaded skill session in minutes, without polluting durable
state, and can later answer:

- what the skill was trying to change;
- which exact revision and realization each agent received;
- why that revision was present and who owned it;
- what else the harness could see;
- which authority was effective;
- whether the skill materially improved the intended outcome;
- whether the evidence is still current; and
- whether the right next action is renew, adopt, update, distill, disable, or
  retire.

The north star is not the number of installed skills. It is useful behavior with
low context cost, reversible custody, and a legible chain from intent to outcome.

## Boundaries

Spindle should federate registries rather than require one canonical marketplace.
It should accept third-party security and evaluation attestations while retaining
its own composition and runtime evidence. It should not become a general package
manager for every tool a skill may use, nor should it let a skill select its own
model or silently expand its own permissions.

The source skill remains portable. The adapter, startup control loop, leases,
receipts, and evaluation claims are Spindle's value around that source.

## Related design notes

- [Minimalist skills after the default shifts](docs/minimalist-skills-vision.md)
- [Skill lifecycle UX](docs/skill-lifecycle-ux.md)
- [Runtime skill realization](docs/runtime-realization.md)
- [Behavioral skill evaluations](docs/skill-evaluations.md)

[^codex-hooks]: OpenAI, [Hooks](https://learn.chatgpt.com/docs/hooks), accessed July 31, 2026.
[^claude-hooks]: Anthropic, [Hooks reference](https://code.claude.com/docs/en/hooks), accessed July 31, 2026.
[^claude-skills]: Anthropic, [Extend Claude with skills](https://code.claude.com/docs/en/slash-commands), accessed July 31, 2026.
