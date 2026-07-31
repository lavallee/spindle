# Skill lifecycle UX: from installed blobs to evidence-bearing leases

Status: design rationale and ecosystem comparison. The core lifecycle described
here is implemented in Spindle 0.2; discovery federation and ecosystem notes
remain product direction, 2026-07-31.

## Spindle 0.2 implementation checkpoint

The design's core verbs now have executable, receipt-bearing boundaries:

- `inspect` builds deterministic intent cards without activating local input;
- `try`, `borrow`, and `release` manage exact disposable or expiring leases;
- `inventory`, `bootstrap`, `launch`, `hooks`, and `conflict` reconcile desired
  and effective harness state without deleting foreign entries;
- `realize` plus activation/delegation receipts keep parent and child routing
  independent;
- `adopt`, `update`, `health`, `rollback`, `disable`, `deprecate`, and `retire`
  provide durable maintenance custody;
- `eval matrix` and `eval distill` provide tuple-bound minimalism evidence; and
- `adapter`, `policy`, `state`, and `migrate` cover certification, organization
  constraints, export/import, recovery, GC, and legacy audits.

The sections below retain “should” language where they describe UX principles or
future registry/provider integration rather than pretending every ecosystem seam
is finished.

## Thesis

The ordinary skill experience begins too late and ends too early:

```text
find a repository -> install it somewhere -> hope the agent uses it -> forget it
```

Installation collapses several different decisions into one durable mutation:

- this source is trustworthy;
- this skill is relevant to the task;
- it is compatible with the current harness and model;
- it does not conflict with the rest of the environment;
- its instructions improve the desired outcome;
- its scripts, tools, and permissions are acceptable; and
- the user wants to maintain it after this task.

Those claims should not share one button. Spindle should make a skill cheap to
understand and temporarily use before asking a person or project to adopt it.
Durable installation becomes one late lifecycle state rather than the prerequisite
for every interaction.

The product direction is:

> Treat a skill as an inspectable, leasable, evidence-bearing dependency. Let a
> user try it in the environment they already have, retain what happened, and
> adopt it only when temporary use earns permanence.

This extends Spindle's existing separation:

```text
source       says where an artifact came from
package      preserves its stable identity and resources
binding      composes a coherent set for a surface
lease        grants temporary availability without adoption
realization  selects the residue for one actual agent coordinate
activation   proves what the harness disclosed to that agent
evaluation   proves whether the resulting behavior helped
adoption     creates a durable, update-bearing relationship
```

This is more consolidation than greenfield architecture. Spindle already has most
of the right nouns in separate loops:

| Existing surface | Lifecycle role |
| --- | --- |
| `liaison.WhatRequest` | the user's intent, desired outcome, acceptance, and local surface facts |
| `roster` | federated upstream discovery providers |
| `broker` | candidate fit, provenance, and an explicit propose-before-acquire boundary |
| `verdicts` | the existing `try`, `borrow`, `graft`, `track`, or `ignore` judgment vocabulary |
| composition and binder | current-blend resolution, shadowing, doctrine, and conflict checks |
| runtime realization | exact agent-local instruction artifact |
| evaluation | availability-versus-behavior evidence boundary |
| event ledger | append-only source for a reconciled inventory |

The lifecycle work should join these into one user journey. In particular,
`broker.acquire` currently records an acquisition while its transpose hook remains
a stub. That broad state should split into fetch/cache, lease, trial outcome, and
adoption. Likewise, `try` and `borrow` should become executable, receipt-bearing
states rather than verdict labels alone.

## User jobs

The lifecycle should be designed around questions, not storage locations.

### What might help me do this?

Search should begin with the user's intent and current surface. A result is a
candidate, not a recommendation to install.

```bash
spindle find "review this migration for rollback risk" --here
```

Results should explain why they may fit, which current skills overlap, and which
claims are source metadata versus Spindle inference. Registry presence and install
counts establish discoverability, not quality or adoption.

Spindle should federate existing sources through roster providers rather than try
to become the only public registry. Git repositories, local packages, skills.sh,
Tessl, organizational catalogs, and future registries can all yield pinned
candidate references.

### What is this skill trying to change?

Before downloading executable dependencies or activating anything:

```bash
spindle inspect github:owner/repo#skill --for "my migration review"
```

The output should be an intent card:

| Field | Question answered |
| --- | --- |
| Outcome | What should become different if this works? |
| Trigger boundary | When should it and should it not activate? |
| Behavioral delta | What does it ask the runtime to do beyond its default? |
| Contents | Which instructions, references, scripts, assets, hooks, or tools arrive? |
| Requirements | Which binaries, services, network paths, credentials, and permissions are needed? |
| Context cost | What is always visible and what loads only on activation? |
| Evidence | On which models, harness builds, roles, tools, and tasks has it helped? |
| Freshness | When was source, review, evaluation, and runtime evidence last refreshed? |
| Trust | Who authored, published, scanned, reviewed, and evaluated this exact digest? |
| Fit | What overlaps or conflicts with the current effective environment? |

The canonical card should be deterministic and source-grounded. A contextual fit
paragraph may be model-assisted, but must be labeled as analysis rather than
package fact.

### Can I try it without taking custody of it?

`try` should launch one managed, disposable session:

```bash
spindle try github:owner/repo#skill \
  --harness claude \
  --task "review the current migration"
```

The operation should:

1. resolve the source to an immutable digest;
2. inspect and validate the package without executing its scripts;
3. compare it with the current bound blend and effective runtime inventory;
4. show the instruction, tool, permission, and conflict delta;
5. ask for any authority the trial actually needs;
6. create a session lease and exact agent realization;
7. let the harness adapter project it without mutating installed state;
8. retain activation and run receipts; and
9. release the lease automatically when the session ends.

The candidate is tried **on top of the user's real current blend**, not in an empty
fictional environment. A no-skill baseline can still be run when the user asks for
an evaluation, but ordinary try-on should answer the immediate question first.

Trial postures should be explicit:

| Posture | Instruction body | Bundled scripts | Network/tools |
| --- | --- | --- | --- |
| `read-only` | yes | disabled | existing read-only envelope only |
| `sandboxed` | yes | temporary workspace | declared and approved subset |
| `full` | yes | allowed | explicit expanded authority |

Unknown skills should default to `read-only`. A tool dependency is a request for
authority, not permission to install or start it silently.

### Can I borrow it for a little longer?

`borrow` creates a renewable lease without creating an adopted dependency:

```bash
spindle borrow github:owner/repo#skill --here --until 2h
spindle borrow github:owner/repo#skill --worktree --until branch-close
spindle release lease-7e42
```

A lease names:

- the source and package digest;
- surface, harness, and permitted agents;
- start, expiry, and renewal policy;
- projection and authority posture;
- conflicts accepted for the lease;
- realizations and activation receipts created under it; and
- whether files or external state changed during use.

Expired leases disappear from runtime discovery but remain visible as historical
receipts. Cache retention and runtime availability are separate: Spindle may keep
the content-addressed package without continuing to expose it to an agent.

### What is active, and why is it here?

The inventory should reconcile all scopes and lifecycle states:

```bash
spindle inventory --here
spindle why migration-review --here
spindle diff --effective
```

One table should distinguish:

| State | Meaning |
| --- | --- |
| discovered | known through a source, never fetched |
| cached | immutable content present, not available to a harness |
| installed | package dependency available to Spindle |
| active | distribution selected as a source of bindings |
| bound | selected into this surface's durable blend |
| leased | temporarily eligible for named sessions or agents |
| realized | exact immutable instruction surface produced |
| activated | harness evidence says an agent received it |
| observed | runtime use or non-use was recorded |
| stale | evidence no longer covers the current coordinate |
| disabled | retained but unavailable |
| deprecated | available with a migration warning |
| quarantined | blocked pending trust or behavior review |

`why` should trace the complete route:

```text
source -> package -> distribution/channel or lease -> surface blend
       -> runtime profile -> realization -> projection -> activation evidence
```

The same view should show shadowed skills, duplicate names from other scopes,
trigger overlap, permission expansion, load errors, last observed use, context tax,
and update/evaluation status.

### Should I keep it?

Adoption promotes a successful lease into an owned relationship:

```bash
spindle adopt lease-7e42 --scope repo
```

The adoption preview should show the exact change: package pin, distribution or
channel edit, expected blend delta, conflicts, evaluation coverage, update policy,
and new maintenance owner. The lease receipt provides evidence, not automatic
promotion authority.

The user may instead choose:

- keep borrowing with a bounded renewal;
- vendor/fork because local ownership matters;
- distill only the useful behavioral residue into an existing package;
- route deterministic pieces to Chip or tools;
- reject and remember why; or
- release without retaining anything beyond the receipt.

### Is it still earning its place?

Maintenance should be exception-oriented:

```bash
spindle health --here
spindle update plan --here
```

Spindle should surface, not silently resolve:

- an upstream version changed;
- a model, harness build, toolset, policy, or dependency moved outside evaluated
  coordinates;
- the skill has not activated or affected outcomes recently;
- a neighboring skill now overlaps or conflicts;
- the runtime default caught up and an instruction may be removable;
- observed failures suggest a bounded retuning experiment; or
- a maintainer deprecated, transferred, or abandoned the source.

Updates should be trials before they are adoptions. Existing evidence stays bound
to the old digest; it cannot be inherited by a new version merely because the
package name is the same.

## Core records

The lifecycle needs a few stable records rather than one overloaded install
manifest.

### `SkillRef`

A source locator resolved to content identity: provider, owner, repository or
package, path, revision, and complete package digest.

### `IntentCard`

The deterministic package explanation plus provenance, requirements, evidence
summary, freshness, and current-surface compatibility findings.

### `Lease`

A temporary grant connecting one package digest to a surface/session scope,
authority posture, expiry, and renewal policy.

### `ProjectionPlan`

The immutable realization and harness-native method by which it should reach one
agent. Projection mechanics stay out of the skill package.

### `ActivationReceipt`

Observed evidence that the intended agent received the realization, which model
actually served it, and which tools and policy were effective.

### `EvaluationClaim`

A bounded claim over package/realization digest, task distribution, agent tuple,
budgets, hard floors, and evidence receipt. Claims can be current, stale, null, or
failed; they are never universal quality badges.

### `AdoptionRecord`

The user or owner decision that turns a tested artifact into a maintained package,
distribution, or surface dependency. It names update and retirement policy.

## Conflict and trust preflight

Trying should be easier than installing, not less safe. Preflight should evaluate:

1. **Artifact structure:** valid Agent Skills package and complete referenced
   resources.
2. **Provenance:** immutable source revision, author/publisher identity where
   available, license, signatures or attestations, and local modifications.
3. **Static risk:** suspicious prompt instructions, executable content, credential
   handling, exfiltration paths, hidden files, and dependency expansion.
4. **Composition:** duplicate names or commands, trigger overlap, conflicting
   authority, doctrine contradictions, and shadowing.
5. **Runtime fit:** harness/model profile coverage, projection support, required
   tools, effective permission envelope, and known adapter limitations.
6. **Behavior evidence:** relevant rather than global evals, including null and
   negative findings.

Third-party scanners should be pluggable attestations. A clean scan is useful
evidence, not proof that a skill is safe. Spindle's distinctive responsibility is
joining trust evidence to composition and actual runtime activation.

## Ecosystem landscape

No single current system covers the complete lifecycle. Several now solve
important pieces that Spindle should reuse or interoperate with.

| System | Strong move | Remaining opening for Spindle |
| --- | --- | --- |
| Agent Skills specification | Portable directory, metadata, compatibility, optional tools, and progressive disclosure | Defines an artifact format, not source trust, composition, leases, runtime evidence, or behavioral maintenance |
| Vercel `skills` / skills.sh | `skills use` resolves a skill into a temporary directory and launches or prompts an agent without installing; also provides find/list/update/remove across many harnesses | Try-on is primarily raw skill projection; documented surfaces do not establish coherent blending, tuple-specific realization, or behavioral evidence |
| Anthropic Claude Code plugins | Excellent install audit: component inventory, estimated context cost, last update, scopes, load errors, last use, enable/disable, marketplace update, and release channels | Plugin lifecycle is harness-specific and still centered on durable installation; runtime use is not the same as measured behavioral benefit |
| OpenAI skills and plugins | Explicit `@`/`$` invocation, skill exploration, local scopes, disable-without-delete, packaged connectors, a shared directory, and workspace controls | Strong discovery and governance surfaces; Spindle can add cross-harness composition, leases, exact realization, and independent evidence claims |
| GitHub Copilot | `copilot plugins list` reconciles plugins, MCP, skills, instructions, and language servers; skill add/remove/reload works across several Copilot surfaces | Strong effective-environment inventory; documented management does not yet close the install-to-outcome evidence loop |
| Tessl | Closest full lifecycle product: registry, versioned tiles, lint/review, install/update/uninstall, scenario evals with and without a skill, cross-agent runs, and optimization | Still mainly dependency/install oriented; Spindle can differentiate on temporary leases, current-blend conflict analysis, session-local profiles, and activation receipts |
| Microsoft SkillOpt / SkillOpt-Sleep | Bounded add/delete/replace optimization, held-out gates, rejected-edit memory, local-session harvesting, staged human adoption | Deep evolution loop rather than package/distribution/inventory system; a natural experimental backend for Spindle distillation |
| Cisco Skill Scanner and Snyk Agent Scan | Security analysis plus, in Snyk's case, machine-wide discovery of agent skills and MCP configuration | Security and inventory evidence should feed Spindle preflight; neither establishes task fit or behavioral lift |
| Google Cloud Agent Registry | Immutable revisions, default revision pointer, visible history, and explicit draft/active/disabled/deprecated/decommissioned states | Strong enterprise lifecycle state model; not a local task-centric try/borrow/compose UX |
| LF agentregistry | Resolves versioned skills into a temporary read-only runtime mount for containerized agents | Useful runtime packaging precedent, but agent manifests still own the dependency and require rebuild/re-run rather than an interactive session lease |

The closest direct competitive overlap is Tessl. The strongest product patterns to
borrow immediately are Vercel's zero-install `use`, Anthropic's context/component/
last-use audit, GitHub's effective inventory, SkillOpt's staged evidence-driven
updates, and Google's explicit retirement states.

Spindle should not answer by building another undifferentiated public leaderboard.
Its distinctive center is:

```text
intent-relative discovery
  + coherent current-environment composition
  + temporary agent/session leases
  + exact model/harness realization
  + activation and outcome evidence
  + reversible adoption and retirement
```

## Proposed CLI journey

```bash
# Find and understand without activating anything.
spindle find "migration rollback review" --here
spindle inspect skills.sh:owner/repo#review --for "this migration"

# Try one disposable session over the current effective blend.
spindle try skills.sh:owner/repo#review --harness claude --task-file task.md

# Keep it available temporarily, or release it.
spindle borrow skills.sh:owner/repo#review --here --until 2h
spindle inventory --here
spindle why review --here

# Option A: release it.
spindle release lease-7e42

# Option B, instead: turn observed usefulness into an owned dependency.
spindle adopt lease-7e42 --scope repo

# Later, inspect drift and test updates before promotion.
spindle health --here
spindle update plan --here
spindle update try review
```

These names are provisional. The important semantic boundary is that `find`,
`inspect`, cache, lease, activation, and adoption remain different operations.

## Delivery sequence

### Slice 1: close the runtime evidence seam

- Add the provider-neutral adapter protocol.
- Add projection, activation, and delegation receipts.
- Retain configured versus raw/canonical observed runtime facts.
- Certify Claude and Codex adapter behavior independently from skill quality.

This makes a lease auditable before introducing remote sources.

### Slice 2: local inspect, inventory, and leases

- Generate intent cards for installed and local-path skills.
- Reconcile installed, active, bound, realized, and observed state.
- Add local `borrow`/`release` over the current blend with explicit TTL.
- Add `why` and effective-environment conflict reporting.

This proves the lifecycle model without registry or supply-chain ambiguity.

### Slice 3: pinned remote try-on

- Add source-provider interfaces and a content-addressed cache.
- Begin with Git and skills.sh-compatible references.
- Add non-executing structural/security preflight and authority preview.
- Launch disposable Claude and Codex trials through certified adapters.

### Slice 4: adoption and maintenance

- Promote a lease into an explicit package/distribution/channel change.
- Bind evaluation claims to exact artifact and runtime coordinates.
- Add update-as-trial, staleness, last-use, deprecation, and quarantine views.
- Feed session failures to bounded retuning experiments without auto-adoption.

## Success criteria

The lifecycle succeeds when a user can answer, before permanent installation:

- what the skill is trying to change;
- why it might fit this task and environment;
- exactly what it would add or override;
- what authority and context it would consume;
- what relevant evidence exists and what remains unknown;
- whether the intended runtime actually received and used it; and
- whether it earned adoption, another lease, distillation, or release.

The north star is not more installed skills. It is lower-cost, reversible access
to useful behavior with legible custody at every step.

## Primary sources

- Agent Skills, [Specification](https://agentskills.io/specification).
- Vercel, [`skills` CLI](https://github.com/vercel-labs/skills) and
  [skills.sh documentation](https://www.skills.sh/docs).
- Anthropic, [Discover and install Claude Code plugins](https://code.claude.com/docs/en/discover-plugins)
  and [create a plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces).
- OpenAI, [Build skills](https://learn.chatgpt.com/docs/build-skills) and
  [build plugins](https://developers.openai.com/plugins/build/plugins).
- GitHub, [About agent skills](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills)
  and [Copilot CLI command reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference).
- Tessl, [What is Tessl?](https://docs.tessl.io/),
  [skill scenario evaluations](https://docs.tessl.io/evaluate/evaluate-skill-quality-using-scenarios),
  and [skill reviews](https://docs.tessl.io/evaluate).
- Microsoft Research, [SkillOpt](https://microsoft.github.io/SkillOpt/) and
  [SkillOpt-Sleep guidance](https://microsoft.github.io/SkillOpt/docs/guideline.html).
- Cisco AI Defense, [Skill Scanner](https://github.com/cisco-ai-defense/skill-scanner).
- Snyk, [Agent Scan](https://github.com/snyk/agent-scan).
- Google Cloud, [Manage skills in Agent Registry](https://docs.cloud.google.com/agent-registry/manage-skills).
- LF Projects agentregistry, [Add skills](https://aregistry.ai/docs/agents/skills/).
