# Spindle roadmap

Status: execution roadmap for [VISION.md](VISION.md), 2026-07-31.

## Outcome

Deliver a complete, evidence-bearing skill lifecycle across Claude Code and
Codex first:

```text
intent -> inspect -> try/borrow -> compose -> bootstrap -> realize -> activate
       -> evaluate -> adopt/update/distill/release -> retire
```

The roadmap is organized as vertical product milestones. Each milestone must
leave a usable path, durable records, and tests. A command name may change during
implementation; the semantic boundaries and completion gates should not.

## Starting point

Spindle already has:

- package, distribution, channel, doctrine, and surface composition models;
- fail-closed bind and Spindle-owned symlink reconciliation;
- harness and model rendering;
- exact session-local realization with conservative fallback;
- provider-neutral projection, activation, and delegation receipt contracts;
- paired behavioral evaluation and held-out promotion gates;
- source discovery, candidate verdict, and acquisition scaffolds; and
- an append-only event ledger.

The missing product loop is:

- one authoritative desired-state and ownership model;
- effective inventory across Spindle and non-Spindle scopes;
- startup reconciliation and native hook adapters;
- executable leases and zero-adoption trials;
- intent cards and preflight;
- promotion from successful lease to adoption;
- update, staleness, health, and retirement workflows; and
- evaluation that can certify tuple-specific minimal residues and adapters.

## Invariants across every milestone

1. Never delete or overwrite state without an ownership record.
2. Distinguish desired, configured, observed, derived, and evaluated facts.
3. Preserve exact source, package, realization, and receipt digests.
4. Treat model, harness, tools, permissions, role, and active blend as part of an
   evidence coordinate.
5. Keep harness mechanics out of portable skill manifests and prose.
6. Make inspection read-only and make authority expansion explicit.
7. Test updates beside incumbents before promotion.
8. Fail honestly on unknown state; do not turn missing evidence into success.
9. Keep hook output concise and detailed evidence out of model context.
10. Support parent and child agents independently without shared mutable routing
    state.

## Milestone 1: desired state, ownership, and effective inventory

Status: complete on 2026-07-31.

Implementation evidence:

- `spindle.lifecycle` defines the v1 package, adoption, lease, surface-lock,
  ownership-receipt, and ownership-index records; `spindle.inventory` defines the
  v1 effective-inventory record. Package and projection identities use full
  SHA-256 content digests.
- `bind`, the global Claude projection flow, aliases, reconciliation, and
  `unbind` now require exact ownership custody. An unowned same-target link and a
  user-retargeted formerly owned link are both preserved.
- `inventory`, `why`, `diff --effective`, `doctor --startup`, and `package
  snapshot` expose the first desired-versus-observed loop. Plugin and managed
  scopes that local files cannot prove remain explicitly `opaque` pending the
  native adapters in Milestone 2.
- The polluted-state, editable-drift, preflight, package-revision, and
  idempotence gates are executable in `tests/test_inventory.py`,
  `tests/test_materialize.py`, `tests/test_packages.py`, and
  `tests/test_cli_inventory.py`.
- Read-only runs against the 2026-07-31 local harness environments repeated
  deterministically at inventory IDs `sha256:778cc1b2…` for Codex and
  `sha256:8fd819ab…` for Claude. The Claude run observed 81 foreign entries and
  four same-name conflicts without mutation; its roughly seven-second deep scan
  establishes a cached-fast-path requirement for Milestone 2 startup.
- Full validation at this checkpoint: `736 passed`; `ruff check .` and
  `git diff --check` pass.

### Deliver

- Define versioned schemas for `SkillRef`, `PackageRevision`, `AdoptionRecord`,
  `Lease`, `SurfaceLock`, `OwnershipRecord`, and `EffectiveInventory`.
- Add a content-addressed package cache distinct from runtime availability.
- Resolve version constraints, tags, and editable installs to content digests.
- Record every Spindle-created projection with target, owner, surface, harness,
  package digest, and creation receipt.
- Inventory repository, ancestor, user, admin, plugin, and known system scopes for
  each reference harness.
- Classify observed entries as expected-owned, stale-owned, foreign,
  conflicting, disabled, broken, or opaque.
- Add provisional commands:

  ```bash
  spindle inventory --effective --here
  spindle why <skill> --effective --here
  spindle diff --effective --here
  spindle doctor --startup --here
  ```

### Gate

- A fixture containing correct links, stale Spindle links, foreign symlinks,
  foreign directories, duplicate names, and broken links produces a deterministic
  inventory.
- Reconciliation removes only stale entries whose ownership receipt matches the
  exact target.
- Foreign state is never mutated, including in error cases.
- A second run is idempotent and produces the same effective-state digest.
- Editable sources changing content become drift even when their declared
  version is unchanged.

## Milestone 2: startup bootstrap and harness hooks

Status: complete on 2026-07-31, including lease-expiry rechecks delivered with
Milestone 3.

Implementation evidence:

- `spindle bootstrap` now has pure plan, locked apply, and observation phases;
  `spindle launch` is the portable pre-discovery enforcement boundary. Startup
  plans and receipts carry exact surface-lock and inventory identities, runtime
  facts, owned actions, foreign conflicts, adapter build, event source, and the
  four distinct decisions.
- Native hook runs use a metadata-keyed local digest cache and fail closed on a
  cache miss. The normal hook path cannot fall back to a deep hash in the
  regression suite. Direct commands measured 0.142 seconds for Codex and 0.634
  seconds for Claude in the evidence environment.
- `spindle hooks plan|install|status|remove` structurally merges stable Claude
  and Codex definitions, preserves unrelated configuration and file mode, owns
  only exact installed fragments, serializes ownership-index updates, and keeps
  configured state, harness trust, and observed heartbeats separate.
- `spindle harness setup|status|context|remove` makes that lifecycle drivable
  from the primary UX surface. It projects one 187-word owned operator as
  `$spindle` in Codex or `/spindle` in Claude Code; current state, authorization,
  and exact action contracts stay in the deterministic CLI. Setup remains
  available as a diagnostic foothold when unrelated ambient conflicts block the
  full surface, and removal touches only receipt-owned operator/hook state.
- Nested live testing demonstrated why environment markers alone are
  insufficient: a Claude child inherits its Codex parent's markers. Runtime
  detection now prefers the nearest named harness process and otherwise fails
  closed. Claude Code 2.1.220 Sonnet and Codex CLI 0.146.0 Terra both discovered
  the operator and executed its context command. Claude's native hook recorded
  the pre-existing user-scope conflicts as blocked; Codex project hooks remained
  configured-unverified in noninteractive `codex exec`, preserving the trust gap
  instead of treating installed configuration as an observed heartbeat.
- `spindle conflict allow|list|revoke` records exact surface, harness, skill,
  absolute path, and content digest decisions. A content or path change makes an
  allowance inapplicable; ambiguous ownership can never be allowed.
- Live Claude Code 2.1.220 evidence covers `Setup --init-only`, fresh Sonnet 5
  and Opus 5 sessions, resume, and a Sonnet 5 `Explore` child. Live Codex CLI
  0.146.0 evidence covers fresh and resume sessions on `gpt-5.6-sol`. Both
  matched a pre-launch surface lock and inventory digest in the following native
  heartbeat.
- Claude Code 2.1.220 omitted model and permission facts from the hook payloads
  observed here, including child-model identity on `SubagentStart`; Spindle
  preserves these as unknown for later activation/delegation evidence. Codex
  showed repository-layer trust to be distinct from command trust. Both are
  explicit adapter capability gaps, not inferred successes.
- The polluted live run preserved five user-scope Claude name collisions and
  the unrelated fixture skill. The owned-link repair receipt changed one exact
  Spindle link while the unrelated file retained SHA-256 `cfb0646d…`.
- The deterministic evidence archive and anchor receipts are documented in
  `experiments/m2-native-hooks/README.md`. Validation at this checkpoint is
  `772 passed`; `ruff check .` and `git diff --check` pass.

### Deliver

- Add a portable startup engine:

  ```bash
  spindle bootstrap --harness <name> --here --check
  spindle bootstrap --harness <name> --here --reconcile-owned
  spindle bootstrap --harness <name> --here --json
  spindle launch <harness> --here -- <harness arguments>
  ```

- Split bootstrap into pure plan, apply, and observe phases.
- Serialize apply operations with a per-surface lock and make duplicate hook
  calls idempotent.
- Define `StartupPlan` and `StartupReceipt` with expected and observed inventory
  digests, owned actions, foreign conflicts, lease status, adapter build, event
  source, and decision.
- Emit distinct `ok`, `warn`, `blocked`, and `restart-required` decisions.
- Generate stable, inspectable hook kits for Codex and Claude Code. Hook
  definitions invoke a stable Spindle command; desired state remains in the
  surface lock.
- Support startup, resume, clear, and compact events where the harness provides
  them. Support parent and subagent start separately.
- Add hook installation, status, dry-run, and removal commands that preserve
  unrelated hooks and respect harness trust:

  ```bash
  spindle hooks plan --harness codex --scope repo
  spindle hooks install --harness codex --scope repo
  spindle hooks status --harness codex --effective
  spindle hooks remove --harness codex --scope repo
  ```

- Use Claude `Setup`/`--init-only` as an optional preflight accelerator while
  keeping `spindle launch` as the portable pre-discovery path.
- On a native session-start hook, inject only a compact status marker and a
  pointer to the full receipt.

### Gate

- Fresh Claude and Codex sessions verify the exact adopted/leased digests before
  task execution and emit startup receipts.
- A stale Spindle-owned projection is safely repaired during pre-launch.
- If the same mismatch is discovered after harness discovery, startup reports
  `restart-required` rather than claiming a clean session.
- A same-name foreign skill is preserved and blocks strict startup until an
  explicit conflict decision exists.
- Hook updates do not occur when only package pins or leases change.
- Concurrent startup hooks cannot corrupt ownership state or produce divergent
  applied plans.
- Resume and compaction recheck lease expiry and desired-state drift without
  flooding model context.
- Disabling or distrusting hooks is visible in `doctor` and never recorded as a
  successful attestation.

## Milestone 3: local intent cards and executable leases

Status: complete on 2026-07-31.

Implementation evidence:

- `spindle inspect` resolves a skill directory, `SKILL.md`, installed skill or
  package, or exact package fragment to separate package and skill digests. It
  generates a deterministic intent card with outcome/trigger facts, behavioral
  delta, contents, references, context cost, provenance, freshness basis,
  profiles/evidence, and authority indicators. Structural/lexical fit is a
  separately labeled deterministic derivation; behavioral fit remains
  `unassessed`.
- Inspection imports and executes nothing, creates no cache entry or projection,
  and writes no Spindle state. Executable and script-like resources are reported
  as authority requirements rather than run.
- Leases are immutable `spindle.lease/v1` grants over exact cached package and
  skill identity, surface/harness, kind/scope, TTL, permitted agents, posture,
  renewal, cleanup policy, and optional task digest. Lease plans, events, and
  trial runs are independently content-addressed.
- `spindle borrow` overlays one `lease:<id>` projection onto the incumbent
  surface lock; `release` removes it through an inspectable plan while retaining
  the package cache and historical receipts. Binding preserves non-colliding
  leases and blocks a same-name takeover before mutation.
- Startup resolves the lock against immutable lease receipts at every event. A
  pre-launch run ownership-safely removes expired projections, updates the lock,
  and writes an expiry event; resume/compact leaves the discovered projection in
  place and returns `restart-required`. Automated tests cover both paths and
  preservation of unrelated foreign state.
- `spindle try` adds a session lease over the actual blend, launches Claude in
  plan/read-tool/no-persistence mode or Codex in ephemeral/read-only/no-approval
  mode, explicitly invokes the candidate, and releases in `finally`. Its run
  receipt joins the task digest, redacted command shape, exit code, stdout/stderr
  digests, startup, activation, and cleanup evidence without retaining task or
  output text.
- Live Claude Code 2.1.220 Sonnet and Codex CLI 0.146.0 `gpt-5.6-sol` trials
  independently returned the exact canary output digest `sha256:2f5c63dc…`,
  exited zero, and removed their exact owned projections. Run receipts are
  `sha256:78c93da7…` and `sha256:816aef70…`; the complete evidence map is in
  `experiments/m3-local-lifecycle/README.md`.
- A first live Claude attempt proved fail-before-mutation behavior against two
  real unrelated ambient name conflicts. The successful isolated-discovery run
  exposed and documented a Claude config-path side effect; its exact generated
  file was relocated intact while older configuration and all foreign skills
  remained untouched.
- Full validation at this checkpoint: `787 passed`; `ruff check .` and
  `git diff --check` pass.

### Deliver

- Generate deterministic intent cards from local and installed packages:
  outcome, trigger boundary, behavioral delta, contents, requirements, context
  cost, provenance, evidence, freshness, authority, and current-environment fit.
- Mark package facts separately from model-assisted fit analysis.
- Turn the existing `try` and `borrow` verdicts into lease records with scope,
  TTL, permitted agents, authority posture, renewal policy, and cleanup state.
- Add:

  ```bash
  spindle inspect <local-ref> --for <intent> --here
  spindle try <local-ref> --harness <name> --task-file <path>
  spindle borrow <local-ref> --here --until <ttl>
  spindle release <lease-id>
  ```

- Compose a trial over the user's actual effective blend and show its exact
  instruction, tool, permission, and conflict delta.
- Default unknown trials to instruction-only, read-only authority.
- Expire runtime availability separately from cached package retention.

### Gate

- `inspect` performs no activation and executes no bundled code.
- `try` leaves installed/adopted state unchanged after session cleanup.
- `borrow` survives new sessions until expiry and then disappears from desired
  runtime state automatically.
- Startup receipts name the lease that authorized each temporary projection.
- Trial cleanup is recoverable after abrupt harness termination.
- A baseline and a trial can run against the same incumbent blend.

## Milestone 4: pinned remote try-on and trust preflight

Status: complete on 2026-07-31.

Implementation evidence:

- `spindle.sources` implements `github:`, `skills.sh:`, generic HTTPS/SSH/file
  Git, and absolute local-Git references. Mutable refs resolve under a
  per-source process lock to an immutable commit/tree before candidate or lease
  construction. The bare cache remote is identity-checked; safe archive export
  rejects traversal, duplicate paths, special files, symlink traversal, and
  bounded-size/count violations.
- Source receipts use a machine-independent snapshot key and bind provider,
  locator, requested revision, commit, tree, and complete package digest.
  Snapshots without receipts, malformed receipts, remote-cache locator changes,
  and content drift fail closed. A pinned commit can be re-resolved offline
  without the origin, and the stable source package name/version remains
  update-comparable across commits.
- `spindle.trust` performs no-execution structure, reference, realization,
  license, selected-skill static-risk, declared-tool, authority, composition,
  and named opaque-attestation preflight. Lease plans bind the source and
  preflight receipt IDs; executable, network, credential, and tool expansions
  require operation-local approvals and remain distinct from observed runtime
  permissions.
- `spindle source quarantine|unquarantine|status` maintains an immutable linked
  event history plus a current policy index. Lease planning and apply both
  recheck quarantine, so revocation blocks future authority without rewriting
  existing source, lease, activation, or run evidence.
- Tests move a mutable Git branch between commits, reuse an exact pin with the
  origin unavailable, poison a verified snapshot, construct malicious tar
  entries, omit references, withhold executable approval, and quarantine a
  previously inspected digest. CLI tests prove inspection/try-on does not
  create adoption state or leave a projection.
- A public `skills.sh`-compatible source at
  `vercel-labs/agent-skills@7c180d9…#web-design-guidelines` was inspected,
  preflighted offline, and tried through Codex CLI 0.146.0 on `gpt-5.6-sol`.
  Run receipt `sha256:fec337aa…` exited zero; cleanup event
  `sha256:b040e525…` removed the exact owned projection and left zero leases and
  adoptions. The compact evidence map and deterministic archive are in
  `experiments/m4-pinned-remote/`.
- Full validation at this checkpoint: `804 passed`; `ruff check .` and
  `git diff --check` pass.

### Deliver

- Generalize source providers behind immutable `SkillRef` resolution.
- Begin with local Git and skills.sh-compatible Git references; add other
  registries through provider adapters.
- Fetch into the content-addressed cache without activating or executing the
  package.
- Run structural validation, provenance checks, license discovery, reference
  completeness, static risk checks, composition analysis, and authority preview.
- Accept third-party security scans as named attestations without treating them
  as proof.
- Require explicit approval for executable resources, network, credentials, or
  new tool dependencies.
- Preserve source revision and complete content digest in every downstream
  record.

### Gate

- A remote skill can be inspected and tried without durable installation.
- Mutable source references are pinned before a lease is created.
- Offline reuse of a previously verified digest works without contacting the
  source.
- Cache poisoning, digest mismatch, incomplete references, and unsupported
  executable requirements fail closed.
- Revocation or quarantine affects future leases without rewriting historical
  receipts.

## Milestone 5: adoption, updates, health, and retirement

Status: complete on 2026-07-31.

Implementation evidence:

- `spindle.maintenance` adds immutable v2 adoption records, adoption plans, and
  linked maintenance events plus a small current-state index. Records bind an
  owner, repository scope, exact source/package/skill pin, refresh channel,
  authority ceiling, retirement policy, successful lease/run/activation/
  preflight provenance, prior adoption, runtime evidence coordinate, and exact
  evaluation-claim IDs.
- `spindle adopt` is the sole trial promotion boundary. It requires a
  content-valid lease plan, zero-exit run with activation and cleanup receipts,
  intact cached bytes, and a non-quarantined package. Its dry-run explicitly
  previews the surface-lock delta and records that no distribution or channel
  mutation is implied.
- `update plan` resolves and preflights refreshable sources without mutation;
  `update try` projects changed bytes beside the incumbent under a digest-named
  candidate alias. Promoted revisions link to their predecessor while starting
  with no inherited evaluation claims.
- `health` separates lifecycle state, last activation, behavioral contribution,
  evidence coverage, cache/projection integrity, effective-inventory findings,
  and drift in model, harness build, toolset, permissions, source revision, and
  package digest. Manual pins remain explicitly non-refreshable.
- Disable, enable, deprecate, rollback, and retirement are plan/apply
  transitions with durable reasons. Rollback reconstructs the predecessor's
  exact lock identity; retirement reconciles only the adoption-owned projection
  and leaves cached evidence and history intact. `vendor` and `distill` expose
  non-mutating custody-path plans.
- CLI tests use a mutable local Git branch to prove failed-trial refusal,
  adoption, changed-source planning, simultaneous incumbent/candidate presence,
  candidate cleanup, non-inheritance, coordinate drift, byte-exact rollback,
  lifecycle states, history retention, and preservation of an unrelated
  user-managed skill.
- Full validation at this checkpoint: `808 passed`; `ruff check .` and
  `git diff --check` pass.

### Deliver

- Promote a successful lease into an `AdoptionRecord` with owner, scope, exact
  pin, update channel, authority ceiling, and retirement policy.
- Preview the exact distribution/channel/surface-lock change before adoption.
- Add:

  ```bash
  spindle adopt <lease-id> --scope repo
  spindle health --here
  spindle update plan --here
  spindle update try <skill>
  spindle disable <skill>
  spindle retire <skill>
  ```

- Treat upstream updates as side-by-side candidate leases.
- Track last activation, last observed behavioral contribution, evidence
  coverage, maintainer/source freshness, conflicts, and runtime drift.
- Support disabled, deprecated, quarantined, and retired states without erasing
  history.
- Provide explicit vendor/fork and distill paths when local ownership is the
  better maintenance choice.

### Gate

- Adoption is the only trial action that changes durable desired state.
- Updating a package never silently inherits the incumbent's evaluation claim.
- Rollback restores the prior exact desired-state digest and projection set.
- Health identifies stale evidence after a model, harness, permission, toolset,
  source, or package change.
- Retirement removes only owned runtime projections and retains historical
  receipts and decision rationale.

## Milestone 6: evidence-driven minimalism and distillation

Status: complete on 2026-07-31.

Implementation evidence:

- `spindle.minimalism` defines a separate v1 named-arm experiment and receipt
  contract without changing the legacy paired-evaluation interpretation. It
  supports no-skill, invariant-core, candidate-overlay, incumbent, and ablation
  arms; repeated seeded case/arm runs; exact artifact and task-distribution
  digests; and a complete model/harness-build/toolset/policy/active-blend
  coordinate.
- Every runner result reports availability, activation, routing, authorization,
  behavior, and adapter conformance as distinct `pass`, `fail`, `unknown`, or
  `not-applicable` gates with evidence. Unknown cannot become success. Negative,
  null, unrelated-arm, error, and case-level results remain in the receipt.
- The distillation decision uses held-out repeated pairs, a predeclared
  non-inferiority margin, a one-sided 95% lower bound, a per-run hard floor, all
  required runtime gates, and a minimum artifact-size reduction. A zero-byte
  overlay is an ordinary candidate and can qualify only through those gates.
- `eval matrix freshness` requires all six current coordinate dimensions and
  returns `rebaseline-required` when any material dimension changes. It never
  carries a claim across a model upgrade by package or profile name.
- `eval distill classify|plan|stage` statically separates behavioral steering,
  reference knowledge, deterministic procedures, tool integrations, fixtures,
  and obsolete workarounds. Plans route deterministic resources toward
  Chip/tools, preserve rich material as progressive references, and propose one
  bounded deletion at a time. Staging copies a local trial revision, leaves the
  source intact, and explicitly makes no adoption change.
- The checked-in deterministic contract run in `experiments/m6-minimalism/`
  retained all 30 observations for five arms, two held-out cases, and three
  repeats. Receipt `sha256:32918ba5…` qualifies an empty overlay 203 bytes
  smaller than the incumbent with a `-0.01` lower bound inside the `-0.03`
  margin and a `0.79` minimum above the `0.70` floor. A model-only change is
  separately proven stale. This is contract evidence, not a model-quality
  claim.
- Full validation at this checkpoint: `812 passed`; `ruff check .` and
  `git diff --check` pass.

### Deliver

- Extend evaluation beyond one baseline/variant mean to named arms:
  no-skill, invariant core, candidate overlay, incumbent, and ablations.
- Add repeats, task-distribution digests, hard floors, non-inferiority gates,
  routing checks, authorization checks, and adapter conformance gates.
- Rebaseline when model/harness coordinates change materially.
- Classify package material as behavioral steering, reference knowledge,
  deterministic procedure, tool integration, fixture, or obsolete workaround.
- Route deterministic candidates to Chip/tools and preserve rich references
  behind progressive disclosure.
- Generate bounded edit proposals and stage them as trial revisions; never
  auto-adopt optimized text by default.

### Gate

- Spindle can demonstrate that removing an instruction is non-inferior before
  landing the smaller realization.
- Availability, activation, routing, permission, and behavioral success are
  reported as separate gates.
- Negative and null results remain visible.
- A tuple-specific empty overlay is a valid evaluated outcome.
- A model upgrade reopens relevant claims rather than carrying prompt residue
  forward blindly.

## Milestone 7: adapter certification and release hardening

Status: complete on 2026-07-31.

Implementation evidence:

- `spindle.conformance` publishes ten cases covering inventory, bootstrap,
  projection, model identity, effective tools/policy, subagent independence,
  resume/reload, restart, and receipt integrity. Reference matrices are
  fail-closed for unobserved runtime capabilities, support explicit negotiation,
  and certify only digest-valid observations. Passing agent evidence now requires
  `projection_loaded = true`, independent content-valid receipts, and an exact
  matching harness/build.
- The sanitized live evidence in `experiments/m7-adapter-certification/`
  certifies Claude Code 2.1.220 (`claude-opus-5` parent to
  `claude-sonnet-5` child) at `sha256:96c11b9d…`, and Codex CLI 0.146.0
  (`gpt-5.6-sol` parent to `gpt-5.6-terra` child) at
  `sha256:f4093c3f…`. Every agent independently loaded the exact canary and
  retained served-model and effective tool/policy evidence. Raw transcripts are
  excluded; sanitized facts retain their source-log digests.
- `spindle.custody` adds deterministic state export/import, exact-plan cache GC,
  mutable-index recovery from immutable receipts, and non-adopting legacy
  migration audits. Import never overwrites different state; recovery refuses
  corrupt chains; GC protects locks, leases, and adoption history.
- `.spindle/policy.toml` / `SPINDLE_POLICY` can allow source providers, cap
  authority, require hook scopes and attestations, pin adapter builds, and
  require a content-valid certification. Policy is enforced at candidate and
  adoption boundaries as well as exposed through `policy show|check`.
- The acceptance journey runs Claude and Codex fixtures in both clean and
  intentionally polluted environments. It covers inspect, disposable try,
  expiring borrow and restart bootstrap, exact conflict decisions, owned-link
  repair, adoption, rejected and promoted updates, coordinate drift,
  distillation, exact rollback, disable/enable/deprecate/retire, crash recovery,
  and preservation of ambient state.
- Documentation and CLI help now distinguish cache, install, bind, lease,
  realization, activation, evaluation, adoption, migration, recovery, and
  retirement. The compatibility, organization-policy, and migration/recovery
  guides name the safety and evidence boundaries.
- Spindle remains in the `0.x` development line at `0.2.0`. Full validation:
  `846 passed`; `ruff check .` and `git diff --check` pass. A clean wheel
  installation imported 0.2.0 and verified both certifications; the wheel
  included the bundled operator assets. Its SHA-256 was `26e1177e…`; the source
  archive also built successfully. The sdist hash is intentionally not embedded
  in a file contained by that same archive.

### Deliver

- Publish an adapter conformance suite for inventory, bootstrap, projection,
  model identity, permissions, subagents, reload/restart behavior, and receipts.
- Certify Claude Code and Codex adapters against named harness builds.
- Add compatibility matrices and capability negotiation for partial adapters.
- Provide migration from legacy global installs and existing Spindle bindings.
- Add schema migration, crash recovery, cache GC, export/import, and reproducible
  diagnostic bundles.
- Document organization policy seams for managed hooks, registries, scanners,
  authority ceilings, and required evidence.
- Dogfood the full lifecycle in multiple real repositories and mixed-model
  parent/subagent sessions.

### Gate

- The end-to-end acceptance journey passes on clean and intentionally polluted
  Claude and Codex environments.
- Adapter receipts prove the actual served model and effective tool/policy
  envelope for parent and child agents independently.
- Upgrade, crash, resume, expired lease, and rollback scenarios preserve desired
  state and history.
- No test requires deleting foreign skill state.
- Documentation and `--help` consistently distinguish cache, install, bind,
  lease, realization, activation, evaluation, adoption, and retirement.
- A release candidate can be reproduced from a fresh machine using pinned test
  fixtures and public instructions.

## Cross-cutting workstreams

These advance with every milestone rather than waiting for a final hardening
phase.

### Schema and migration

Version all durable records from their first release. Readers should reject
unknown required fields, preserve unknown optional fields where practical, and
provide explicit migrations rather than best-effort reinterpretation.

### Security and consent

Model instruction visibility, bundled code execution, tool installation,
network access, credentials, hook installation, and durable adoption are
separate grants. Test each boundary.

### UX and explanations

Every mutating command should have a plan/dry-run representation. Every blocked
decision should say what was expected, what was observed, what Spindle preserved,
and the smallest corrective action.

### Performance

Startup uses local hashes and cached metadata. Network refresh, evaluation, and
deep scanning happen before launch or asynchronously, never as an unbounded
session-start dependency. The normal correct-state hook should finish quickly
and add only a one-line marker to context.

### Compatibility research

Harness capabilities move quickly. Keep adapter behavior behind conformance
tests and dated evidence rather than embedding transient CLI flags in portable
packages or core schemas.

## Release slices

The milestones can ship incrementally:

| Release | Coherent user outcome |
| --- | --- |
| `0.2` | Trustworthy effective inventory and ownership-safe reconciliation. |
| `0.3` | Verified startup for Claude and Codex with stable hooks and receipts. |
| `0.4` | Local inspect, try, borrow, release, and expiring leases. |
| `0.5` | Pinned remote zero-install trials with trust preflight. |
| `0.6` | Adoption, update-as-trial, health, rollback, and retirement. |
| `0.7` | Tuple-aware ablation, distillation, and richer evidence gates. |
| `0.8` | Certified adapters, migrations, recovery, policy seams, and dogfooded lifecycle. |

Versions express dependency order, not calendar commitments.

## Explicitly deferred

- Building a single canonical public skill marketplace.
- Automatically executing third-party setup scripts during inspection.
- Letting skills choose their own model, permissions, or update promotion.
- Removing foreign harness state without explicit user ownership transfer.
- Universal adapter behavior inferred from one Claude or Codex build.
- Popularity-based global quality scores detached from task and runtime context.

## Execution rule

Implement the highest unblocked milestone as an end-to-end vertical slice. Do
not build remote acquisition before local ownership, inventory, and startup
semantics are trustworthy. Do not call a milestone complete from unit tests
alone when its gate names a live harness or polluted-environment scenario.

The paste-ready objective and completion contract are in [GOAL.md](GOAL.md).
