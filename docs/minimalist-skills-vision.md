# Spindle after the default shifts

Status: research and product-vision note, 2026-07-29. Spindle 0.2 implements the
named-arm, full-coordinate, non-inferiority, freshness, classification, and
bounded-staging contracts described here. The broader package-design guidance is
direction, not a promotion decision for any skill.

## Spindle 0.2 implementation checkpoint

`spindle eval matrix validate|run|freshness` now supports no-skill,
invariant-core, candidate-overlay, incumbent, and ablation arms; repeated seeded
cases; six separate runtime/behavior gates; hard floors; a one-sided 95%
non-inferiority lower bound; material size reduction; and rebaselining across
model, harness build, toolset, policy, active blend, and task distribution.

`spindle eval distill classify|plan|stage` separates behavioral steering,
reference knowledge, deterministic procedures, tool integrations, fixtures, and
obsolete workarounds. Staging creates one local trial revision and never changes
adoption. The checked deterministic contract experiment is under
`experiments/m6-minimalism/`; it is evidence for the machinery, not a general
model-quality claim.

## Thesis

Spindle should stop treating a skill primarily as a reusable body of
instructions. It should treat a skill as a **versioned, evidence-backed behavioral
delta**: the smallest intervention that moves one exact model-and-harness system
from its observed default behavior to a desired outcome.

That gives Spindle a sharper purpose:

> Spindle discovers what a capable agent already does, isolates the residual gap,
> lands the smallest package that closes it, and rechecks that conclusion whenever
> the model or harness default changes.

The minimal unit is not necessarily a tiny package. A package may contain rich
references, executable tools, templates, fixtures, and evaluation cases. The
minimal unit is the **instruction surface activated in the model's context**.
The right pattern is often a thin root and a rich, progressively disclosed
package.

This also clarifies the relationship with Chip. Spindle evicts behavior that the
current model or harness already supplies. Chip and ordinary tools evict behavior
that should not remain prose. What survives both pressures is the real skill:
situated recognition, interpretation, local knowledge, product taste, and the few
judgment calls that still cause a measured improvement when stated.

## What changed at the frontier

The user's premise is now directly supported by the model vendors' own guidance.

Anthropic reports that it removed more than 80 percent of Claude Code's system
prompt for Opus 5 and Fable 5 with no measurable loss on its coding evaluations.
Its explanation is not merely that tokens are expensive. Older rules, examples,
and repeated tool instructions increasingly conflict with one another, constrain
the model's exploration, and duplicate abilities now supplied by the model or
harness. Its current advice is to rely more on judgment, design expressive tool
interfaces, use progressive disclosure, keep repository instructions focused on
non-obvious gotchas, and make skills lightweight guides carrying opinions or
knowledge specific to the team or product.[^anthropic-new-rules]

OpenAI reports the same direction independently. In internal coding-agent evals,
leaner system prompts improved scores by roughly 10–15 percent while reducing
total tokens by 41–66 percent and cost by 33–67 percent. Its recommended method is
controlled ablation: remove one instruction, example, or tool group at a time and
rerun representative evals; state each requirement once; and retain examples or
style guidance only when they encode a product requirement or repair an observed
gap.[^openai-lean]

This does not mean that instructions have ceased to matter. It means their value
has become more conditional:

- Opus 5 now self-verifies reliably enough that legacy “double-check” and
  verifier-agent instructions can cause over-verification and wasted tokens.[^opus5]
- Fable 5 guidance likewise warns that skills written for earlier models may be
  too prescriptive and degrade output, but still recommends explicit,
  fresh-context verification for certain long-running tasks.[^fable5]
- Sonnet 5 is more agentic and more literal than Sonnet 4.6. It often no longer
  needs scaffolding that forces periodic progress updates, while instructions
  intended to apply broadly must name their scope explicitly.[^sonnet5]
- Anthropic's earlier harness experiments show the complementary result: model
  improvements can delete an orchestration mechanism, not just prose. Opus 4.5
  largely removed the “context anxiety” that had made context resets necessary in
  a Sonnet 4.5 long-running harness.[^anthropic-harness]

The default is therefore not a universal model property. It is behavior emerging
from a complete runtime system.

## The object being tuned

Let a tested system coordinate be:

```text
T = model + reasoning/effort + harness build + system policy
    + tools and schemas + permissions + memory/compaction policy
    + agent role + active blend + surface state
```

For any representative task set, Spindle can observe the system's default
behavior `B0(T)`. A skill candidate `S` is useful only if `B(T, S)` produces a
materially better outcome. If a new model or harness changes `T`, the old claim
does not automatically transfer.

This framing has four consequences.

1. **No-skill behavior is the starting artifact.** A skill is not justified by
   the plausibility of its prose. It is commissioned by a reproducible gap.
2. **Minimality is tuple-relative.** A line essential for one model, effort, or
   harness can be redundant or harmful for another.
3. **Portability is an evaluated claim.** A source skill can retain one identity,
   but its landed steering delta may legitimately differ across tuples.
4. **Drift is expected.** A model or harness upgrade starts a re-baselining event,
   not a blind carry-forward of historical prompt workarounds.

OpenAI's evaluation guidance reinforces the tuple boundary: agentic evaluation
reports should name the model, reasoning setting, tool access, harness,
safeguards, retry and token budgets, elicitation method, and validity checks. It
also recommends testing through the agentic interface users actually rely on,
not only a stripped-down model endpoint.[^openai-evals]

## Essence and steering residue

The stable essence of a skill and the text needed to steer a particular runtime
are related but different objects.

**Skill essence** is the enduring product intent:

- when the capability is relevant and when it is not;
- the outcome and evidence that define success;
- local facts or conventions the model cannot discover reliably;
- product or team preferences where multiple reasonable answers exist;
- authority and safety boundaries not already owned by the harness; and
- the irreducible situated judgment that should remain with the model.

**Steering residue** is the smallest tuple-specific instruction that makes that
essence show up in behavior. It may be empty. It may be one sentence. It may need
an example on a smaller model and no example on a frontier model. It may reference
a rich file only when a branch of the task requires it.

This distinction avoids two traps. “Canonical skill prose” need not be stretched
until it works everywhere, and “minimal” need not mean throwing away valuable
domain knowledge. Spindle can preserve the semantic contract and package while
compiling different, measured residues for different targets.

## One installed set, many runtime realizations

A distribution cannot assume that one repository or one session has one model.
The main agent may use one model for implementation, delegate exploration to a
faster model, and ask a stronger reviewer to inspect the result. Those agents can
operate concurrently in the same worktree. One installed skill set must therefore
support different steering residues without duplicating its identity or mutating
a workspace-wide “current model” file.

The useful distinction is:

- the **installed package** is the stable identity, contract, invariant core,
  references, tools, tests, and evaluated overlay library;
- a **session profile** is the runtime coordinate available to one agent: harness,
  requested and served model, effort, role, tool/policy envelope, and relevant
  harness capabilities; and
- a **realization** is the invariant core plus at most one selected overlay that
  is actually disclosed to that agent for that invocation.

In short: **binding chooses the package; session loading chooses the
realization**.

```text
install one package
        |
agent/session starts with a profile coordinate
        |
skill is selected
        |
resolver discloses invariant core + one matching overlay
        |
receipt records package, profile, overlay, and requested/served model
```

This routing must obey six properties.

1. **Session-local, never workspace-global.** A parent and two subagents must be
   able to realize three profiles concurrently without racing on a generated
   `SKILL.md`, environment file, or symlink.
2. **Resolve from facts, not self-assessment.** The model should not be asked to
   guess its own identity or decide whether it is “frontier enough.” The harness
   or agent definition supplies the coordinate.
3. **Child agents re-resolve.** A subagent inherits the package and behavior
   contract, not the parent's overlay. Model selection and compatible profile
   selection should be one operation in delegation.
4. **Prefer an exact evaluated mapping.** Coarse tiers such as `frontier` are
   conservative fallbacks. Promotion binds an overlay to a real model family,
   effort, role, harness, and policy/tool envelope.
5. **Fail honest.** An unknown profile, absent overlay, or requested/served model
   mismatch falls back to the invariant core and records an unresolved or
   unevaluated realization. It must not silently claim to be tuned.
6. **Invalidate on change.** If a model or effort changes during a session, the
   prior realization becomes stale. The next invocation must re-resolve, or the
   harness must require an explicit skill reload or new session.

Model routing and skill routing are coupled but have different owners. The
task/delegation policy chooses an agent role, model, effort, permissions, and tool
envelope. Spindle then resolves the installed skill against the coordinate that
was actually granted. A skill-level model override would invert that relationship
and make a reusable skill fight the task router. “Choose model and profile
together” therefore means an atomic delegation receipt and compatibility check,
not letting each skill choose which model runs it.

Current harness behavior makes a two-level design pragmatic. Codex custom agents
can configure model, reasoning effort, developer instructions, and skill
availability; Claude Code subagents can configure model, effort, and preloaded
skills.[^codex-subagents][^claude-subagents] Claude Code also provides dynamic
skill context and session hooks, including the active model at session start,
which are useful adapter seams.[^claude-skills][^claude-hooks] But the portable
Agent Skills specification defines discovery and progressive loading, not a
standard runtime-model conditional for a skill body.[^agent-skills-spec]

Spindle should therefore support:

- a **portable fallback**: a tiny invariant `SKILL.md` whose dispatcher reads an
  already supplied session profile and opens exactly one overlay reference; and
- a **harness-native adapter**: when the surface supports it, resolve an ephemeral
  realization at skill invocation so even the dispatcher does not become a
  recurring context tax.

The fallback is deliberately less magical. If the harness cannot expose a
reliable session-local profile—especially after an in-session model switch—the
package uses its conservative core and says why. A global generated render is
not an acceptable shortcut.

An overlay should also remain small and behavioral. If two model tiers require
different output contracts, authority, or workflows rather than different
elicitation, that is evidence for separate skills or agent roles, not an excuse
to hide two products behind a router.

## The role of Spindle

The best north star is **behavioral linker and delta manager**, not skill pile
manager and not general prompt optimizer.

Spindle should own:

- **Baseline discovery:** measure what the exact target tuple already does without
  the skill.
- **Gap custody:** record the observed failure, desired behavior, provenance, and
  representative cases that commissioned the skill.
- **Behavior decomposition:** classify each instruction or resource by why it
  exists and where it belongs.
- **Deletion-first tuning:** search for the smallest non-inferior intervention,
  not the most comprehensive explanation.
- **Realization:** combine a stable behavior contract with one session-local,
  target-specific delta without changing the installed package.
- **Composition:** measure triggering and coexistence in the actual blend, not
  just isolation.
- **Evaluation custody:** bind every effectiveness and minimality claim to an
  exact tuple, case-set digest, budgets, and receipt.
- **Drift handling:** expire or re-open claims when model, harness, tool, policy,
  or package coordinates change.
- **Placement advice:** recommend delete, harness/config, reference, tool/CLI,
  Chip, or residual skill rather than assuming all useful behavior belongs in
  prompt text.

It should not claim to discover one universally optimal prompt, infer usefulness
from token count alone, auto-promote self-edits from the same cases used to tune
them, or turn every package into a thin but opaque dependency graph.

## A placement test for every behavior

Before optimizing wording, split a candidate skill into behavior atoms and ask
where each belongs.

| Observed need | Default destination |
| --- | --- |
| The current model and harness already do it reliably | Delete it |
| The harness can guarantee it through permissions, policy, state, or a tool schema | Harness/configuration |
| It is stable, detailed knowledge needed only on one branch | Progressive reference |
| A fixture can decide it and it has no standing state or authority | Script, test, or CLI |
| It has a deterministic envelope, durable state, bounded judgment, and a refusing/authority gate | Chip candidate |
| It is a team-specific fact, preference, trigger, exception, or situated negotiation | Residual skill |

This extends Chip's falsifiability triage. The Chip ladder asks what can leave
prose for deterministic or governed execution. Spindle adds an earlier question:
what can leave prose because the current runtime already supplies it?

The resulting pressure is:

```text
legacy skill
    ├── already default behavior ───────────────> delete
    ├── runtime-wide rule or affordance ────────> harness/config
    ├── deep but conditional knowledge ─────────> progressive reference
    ├── falsifiable stateless procedure ────────> test/script/CLI
    ├── stateful governed bounded judgment ─────> Chip
    └── situated, local, outcome-relevant delta > thin skill core
```

## How to test the minimalist claim

### 1. Write the claim before the skill

A skill experiment should start with:

- the exact behavior gap observed without the skill;
- representative positive, negative, and ambiguous tasks;
- outcome requirements and hard safety/authority floors;
- the target tuple and run budgets;
- known confounders and the external state that must be frozen; and
- a maximum acceptable regression margin.

Anthropic's current authoring guidance is explicit: run representative tasks
without a skill, document specific failures, establish the baseline, then write
only enough instruction to close those failures.[^anthropic-skill-authoring]

### 2. Separate discovery from effectiveness

A skill can fail because the harness did not select it, because the model did not
read the right resource, or because its instructions did not improve the work.
Those are different claims and need different runs.

**Trigger suite**

- positive requests where the skill should activate;
- nearby negative requests where it must stay inactive;
- ambiguous requests where clarification or conservative activation is expected;
- crowded catalog runs where descriptions compete; and
- false-steal checks against neighboring skills.

**Forced-invocation suite**

- hold discovery constant and compare the behavior of each content arm;
- record which referenced resources and scripts were actually accessed; and
- distinguish “available” from “used” from “caused the outcome.”

Anthropic recommends evaluating triggering, isolation, coexistence, instruction
following, and output quality across each model an organization uses, then
rerunning those evaluations as models and workflows change.[^anthropic-enterprise]

**Routing suite**

- each supported parent and subagent profile selects its intended overlay;
- unknown profiles and missing overlays take the documented conservative path;
- requested and actually served model mismatches remain visible;
- concurrent agents realize different profiles without shared-state races;
- a model or effort change invalidates the prior realization; and
- session resume, compaction, and skill re-invocation preserve or recompute the
  right coordinate.

These cases test the resolver end to end. A forced overlay can prove that its
content works, but it cannot prove that the installed package will select it.

### 3. Use more than two arms

The current no-skill/full-skill pair is necessary but insufficient for essence
extraction. A useful experiment has at least these arms:

| Arm | What it isolates |
| --- | --- |
| `A0 no-skill` | Current system default |
| `A1 metadata-only` | Trigger and mere skill-presence effects |
| `A2 essence` | Proposed minimal instruction core |
| `A3 essence+resources` | Value of scripts, references, templates, or examples |
| `A4 current-full` | Legacy or incumbent behavior |

Not every production run needs all five arms. They are the diagnostic ladder for
commissioning or retuning. Once the essence is understood, ordinary promotion can
compare the incumbent and candidate directly.

### 4. Perform deletion-first ablation

Parse the full skill into named atoms or coherent groups. Each atom should carry:

- a category: trigger, outcome, local fact, preference, safety/authority,
  procedure, example, tool guidance, or explanatory scaffold;
- a provenance reference: the failure, product requirement, policy, or source
  that caused it to be added;
- a predicted effect;
- its target scope and applicable tuples; and
- its latest ablation result.

Then remove one group at a time, preserving the same tasks and budgets. If quality
is non-inferior and hard floors hold, the deletion survives. After single-group
passes, test combinations because redundant instructions can mask one another.
Occasionally try additions or replacements, but addition is a response to an
observed residual failure, not the default motion.

This is compatible with SkillOpt's strongest ideas—bounded add/delete/replace
edits, rejected-edit memory, and held-out selection—but changes the objective from
“highest score” to “smallest non-inferior behavioral delta.” SkillOpt's published
results also show why tuple testing matters: optimized skill artifacts can
transfer across models and between Codex and Claude Code, but transfer is measured
rather than assumed.[^skillopt]

### 5. Use a non-inferiority and efficiency gate

A minimalist candidate should pass when:

1. all safety, authority, and required-outcome floors pass;
2. quality is no worse than the incumbent beyond a predeclared margin, including
   per-stratum and worst-case review;
3. no material regression appears on unrelated tasks or neighboring skills; and
4. the candidate is strictly better on at least one efficiency or simplicity
   dimension, or materially better on quality.

Efficiency dimensions should include:

- root `SKILL.md` tokens;
- total activated package tokens;
- total input, reasoning, and output tokens;
- latency and cost;
- unnecessary tool calls, retries, verifier loops, and subagent runs;
- unneeded user interruptions or approval requests;
- scope expansion and excess artifacts; and
- compaction or context-reset pressure on long tasks.

The gate is Pareto-shaped, not a single score-per-token ratio. Token savings cannot
buy a safety regression, and a tiny mean quality gain may not justify a large cost
or variance increase.

### 6. Protect the test set from the optimizer

Iterative deletion creates selection pressure. Reusing one “held-out” set for
every optimization epoch eventually tunes to that set.

Spindle should distinguish:

- **development:** visible cases for grader and skill construction;
- **selection:** unseen cases used to accept or reject bounded candidate edits;
- **final test:** sealed cases used once for a promotion claim; and
- **monitoring:** later real or newly sampled cases used for drift detection.

Repeated stochastic samples, paired case order, and confidence intervals should
replace a single run per arm for any material promotion. Means should not hide a
critical task-family regression. A small corpus can begin with 3–5 representative
queries for author feedback, as Anthropic recommends, but a production claim
needs enough cases and repeats to make its predeclared non-inferiority margin
credible.

### 7. Evaluate the blend and the long run

The final candidate must run:

- alone;
- in its intended distribution with neighboring skills;
- on unrelated tasks to detect over-triggering and behavioral bleed;
- early and late in a long context;
- across compaction or memory boundaries where relevant; and
- with requested and actually served models recorded separately.

This matters even with million-token windows. Controlled research continues to
find that model performance becomes less reliable as input grows, and Anthropic
describes context as a finite resource with diminishing marginal returns.[^context-rot]

## What “minimal” can honestly mean

Finding the global shortest prompt is neither tractable nor useful. Spindle can
make a narrower, auditable claim:

> For tuple `T`, case distribution `D`, budgets `R`, and hard floors `F`, this
> skill realization is deletion-minimal with respect to the tested atom set: no
> tested single deletion or accepted deletion combination remained non-inferior.

That is a **1-minimal evidence claim**, not a claim of universal optimality.
The receipt should say what was tested, what was not, and when the claim expires.

Useful package-level measures include:

- **excess instruction:** tokens removed without a material regression;
- **essentiality coverage:** share of retained atoms backed by a policy owner,
  product requirement, source fact, or measured ablation;
- **activation tax:** expected activated tokens per eligible task;
- **behavioral lift:** outcome change from no-skill to minimal candidate;
- **oversteer:** unrelated-task and neighboring-skill regressions;
- **instruction utilization:** retained references or tools actually used in
  successful runs; and
- **staleness:** time or coordinate distance since the last no-skill rebaseline.

These are diagnostics, not a leaderboard. A 30-token skill that does nothing is
worse than a 500-token skill that supplies indispensable local knowledge.

## What a tuned skill package should contain

The long-term source artifact should be richer than one canonical prose file:

```text
skill-package/
  SKILL.md                   # invariant core and portable dispatcher
  spindle-realization.toml   # evaluated runtime coordinates and overlay mapping
  contract.md                # desired outcome, evidence, authority, non-goals
  overlays/
    codex-sol-review.md      # minimal tuple-specific steering residue
    codex-terra-scan.md
    claude-opus-review.md
  references/                # conditional high-fidelity knowledge
  scripts/                   # deterministic work and validation
  templates/                 # output/interface constraints when genuinely needed
  evals/
    development/
    selection/
    test/
  receipts/                  # baseline, ablation, promotion, drift
```

This is the shape used by the first runtime-realization slice; contract and eval
directories remain conceptual rather than required. It makes three ownership
boundaries visible:

- the contract explains **what behavior matters**;
- the realization manifest and overlays explain **what this runtime still needs to
  be told**;
  and
- references, tools, and Chips explain **where non-prompt capability lives**.

The installed root `SKILL.md` should usually contain only a precise
trigger/anti-trigger, the outcome and evidence contract, genuinely invariant
local steering, and the portable routing instruction. A harness-native adapter
may materialize the same root plus one overlay in a session cache, but never
overwrite the shared package. Examples stay only when ablation shows that they
encode taste or repair a failure. Tool examples should preferentially become
expressive schemas or executable help. Deterministic verification should prefer
tests and tools over prose reminders.

## Guardrails without instruction accumulation

Current Spindle correctly refuses to let a renderer silently drop hard clauses.
The minimalist vision should preserve that safety intent while evolving the
mechanism.

“Guardrails only accumulate” is safe against accidental deletion, but repeated or
conflicting instructions can themselves degrade behavior. The stronger future
rule is:

> Every required invariant has one named owner and proven coverage at the
> strongest practical enforcement boundary; skills reference or inherit that
> invariant instead of restating it everywhere.

A policy enforced by harness permissions or code need not be duplicated in every
skill. A product authority boundary that exists only as model instruction must
remain until another owner proves coverage. Compliance and safety requirements
are not removable merely because a small behavior suite did not trigger a failure.

This suggests moving from verbatim-line preservation alone toward invariant
coverage receipts: policy id, owner, enforcement surface, applicable tuples, and
verification evidence. Verbatim preservation remains a useful floor for any hard
rule that still lives in skill text.

## Implications for the current Spindle implementation

Spindle already has several of the right pieces, but they need to be pointed at
the new objective.

| Current capability | What it proves now | Required evolution |
| --- | --- | --- |
| Harness/model render profiles | Text can vary by surface and “frontier” scaffolds can be trimmed | Replace a simple capability-tier density assumption with explicit tuple-specific behavior deltas |
| Static surface binding | One rendered package can be materialized for a target repository | Install one package and realize its overlay per session or agent without shared mutable state |
| Paired no-skill/skill evaluation | A full candidate can beat a baseline on held-out cases | Add metadata/essence/resource arms, repeated samples, non-inferiority gates, and coexistence/trigger suites |
| `optimize` with bounded edits | Candidate prose can be accepted by a score gate | Prefer deletion, add complexity costs, and separate selection cases from sealed final tests |
| Verbatim guardrail preservation | A renderer cannot silently strip a hard source line | Track invariant ownership and coverage so safe deduplication is possible |
| Binding coordinates and receipts | Skill, doctrine, model, and harness claims can be pinned | Separate package binding from session realization; include role, harness build, tool/schema digest, effort, policy, memory/compaction, budgets, and requested/served model |
| Chippability scoring | Static prose can reveal a chip-shaped pattern | Make placement analysis a first-class result alongside delete/reference/tool/harness/skill |
| Package/distribution composition | A coherent subset can land on a surface | Gate the landed blend on trigger precision, coexistence, activated context, and drift status |

One current seam deserves early correction: model profiles named only by tiers such
as `frontier` imply a monotonic “same instructions, less scaffold” relationship.
The vendor guidance shows behavior-specific divergence inside the frontier. Opus
5 and Fable 5 can need different verification guidance; Sonnet 5's literalism and
tool defaults differ again. A tier can remain a fallback, but evidence-promoted
profiles should bind to real model families and harness coordinates.

## A practical first program

Start with a bounded private-distribution pilot rather than redesigning the
package schema first.

1. Select six to eight skills spanning local data knowledge, planning, release
   procedure, design judgment, broad review, and a narrow security check. Include
   both long and short incumbents.
2. Freeze three production-relevant tuples—for example a current Codex tuple and
   two materially different Claude Code model tuples—with exact effort, role,
   tool, permission, and harness coordinates.
3. Build trigger, forced-invocation, coexistence, and unrelated-task cases from
   real prior work. Hold back a sealed final set.
4. Run no-skill and current-full baselines. Do not commission minimalist work for
   a skill whose full form shows no lift.
5. Atomize only the skills with demonstrated lift. Run deletion-first selection
   and route deterministic or stateful residue to tool/Chip review.
6. Promote a minimal candidate only on non-inferiority plus a measured efficiency
   win; retain null and failed-ablation receipts.
7. Install each package once. Run a mixed parent/subagent workflow in which at
   least two agents concurrently need different overlays, including unknown and
   requested/served-mismatch cases.
8. Re-run the full landed blends, then observe a small number of real workflows
   before making the package and its evaluated profile mappings canonical.

The pilot's success criterion is not “cut every skill by 80 percent.” It is:

- fewer activated instructions and lower cost where defaults have caught up;
- no loss of product-specific behavior, safety, or authority boundaries;
- explicit evidence for every substantial retained instruction;
- a clear destination for behavior that should leave prose; and
- faster, honest retuning when the next model or harness changes the default.

## Product principles

The vision can be held in eight rules:

1. **Baseline first.** No observed gap, no commissioned skill.
2. **Difference, not recipe.** Tell the runtime only what changes the desired
   outcome from its current default.
3. **Delete before adding.** Legacy scaffolding is a hypothesis, not an asset.
4. **One package, local realizations.** Preserve a shared essence while each
   parent or child loads only the residue evaluated for its actual tuple.
5. **One owner per invariant.** Do not purchase safety by repeating conflicting
   prose.
6. **Code what a fixture can decide.** Use Chip only where state, bounded judgment,
   and authority justify its governance.
7. **Evaluate the real system.** Model, effort, harness, tools, policy, blend, and
   budgets are part of the claim.
8. **Expire confidence.** A new default reopens the question of what the skill
   still needs to say.

The deepest shift is simple: Spindle should not be a machine for preserving
skills. It should be a machine for preserving **desired behavior while allowing
instruction to disappear**.

## Sources

[^anthropic-new-rules]: Anthropic, [“The new rules of context engineering for Claude 5 generation models”](https://claude.com/blog/the-new-rules-of-context-engineering-for-claude-5-generation-models), July 24, 2026.
[^openai-lean]: OpenAI, [“Model guidance — Favor leaner prompts”](https://developers.openai.com/api/docs/guides/latest-model#favor-leaner-prompts), accessed July 29, 2026.
[^opus5]: Anthropic, [“Prompting Claude Opus 5”](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5), accessed July 29, 2026.
[^fable5]: Anthropic, [“Prompting Claude Fable 5”](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5), accessed July 29, 2026.
[^sonnet5]: Anthropic, [“Prompting Claude Sonnet 5”](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5), accessed July 29, 2026.
[^anthropic-harness]: Anthropic, [“Harness design for long-running application development”](https://www.anthropic.com/engineering/harness-design-long-running-apps), March 24, 2026.
[^openai-evals]: OpenAI, [“A shared playbook for trustworthy third party evaluations”](https://openai.com/index/trustworthy-third-party-evaluations-foundations/), 2026.
[^anthropic-skill-authoring]: Anthropic, [“Skill authoring best practices”](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices), accessed July 29, 2026.
[^anthropic-enterprise]: Anthropic, [“Skills for enterprise”](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/enterprise), accessed July 29, 2026.
[^skillopt]: Microsoft Research, [“SkillOpt: Executive Strategy for Self-Evolving Agent Skills”](https://microsoft.github.io/SkillOpt/), May 2026; [arXiv:2605.23904](https://arxiv.org/abs/2605.23904).
[^context-rot]: Anthropic, [“Effective context engineering for AI agents”](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents), September 29, 2025; Kelly Hong, Anton Troynikov, and Jeff Huber, [“Context Rot: How Increasing Input Tokens Impacts LLM Performance”](https://www.trychroma.com/research/context-rot), July 2025.
[^codex-subagents]: OpenAI, [“Subagents”](https://learn.chatgpt.com/docs/agent-configuration/subagents), accessed July 29, 2026; [“Build skills”](https://learn.chatgpt.com/docs/build-skills), accessed July 29, 2026.
[^claude-subagents]: Anthropic, [“Create custom subagents”](https://code.claude.com/docs/en/sub-agents), accessed July 29, 2026.
[^claude-skills]: Anthropic, [“Extend Claude with skills”](https://code.claude.com/docs/en/slash-commands), accessed July 29, 2026.
[^claude-hooks]: Anthropic, [“Hooks reference”](https://code.claude.com/docs/en/hooks), accessed July 29, 2026.
[^agent-skills-spec]: Agent Skills, [“Specification”](https://agentskills.io/specification), accessed July 29, 2026.
