# Spindle completion goal

Status: completed for the current Spindle 0.x baseline on 2026-07-31; future harness or
model coordinates require recertification under the same contract.

This is paste-ready language for running [VISION.md](VISION.md) and
[ROADMAP.md](ROADMAP.md) to completion as one persistent implementation goal.

## Objective

```text
Implement the Spindle VISION.md and ROADMAP.md end to end, delivering an
evidence-bearing skill lifecycle for Claude Code and Codex: desired-state and
ownership records; effective cross-scope inventory; ownership-safe startup
bootstrap and stable native hooks; intent cards; local and pinned-remote try and
borrow leases; exact per-agent realization and activation evidence; explicit
adoption; update-as-trial, health, rollback, disable, quarantine, and retirement;
and tuple-aware evaluation and distillation.

Make that lifecycle directly operable from the harness: ship a minimal
project-local Spindle operator for Codex and Claude Code that queries live CLI
state and action contracts, routes correctly in nested mixed-harness sessions,
previews every mutation, and never treats operator installation or hook
configuration as proof of skill activation or runtime observation.

Work milestone by milestone in ROADMAP.md dependency order, completing the
highest unblocked vertical slice before expanding scope. Preserve foreign and
user-managed harness state. Never delete or overwrite an artifact without an
exact Spindle ownership record. Keep harness mechanics deterministic and outside
portable skill prose. Bind all effectiveness claims to exact artifact and runtime
coordinates. Treat live Claude/Codex validation and durable receipts as required
evidence wherever a roadmap gate names them.

The goal is complete only when every roadmap milestone gate passes, the full
test and lint suites pass, schema migrations and user documentation are current,
and the end-to-end acceptance journey succeeds from fresh and intentionally
polluted environments on certified Claude Code and Codex builds. Do not mark the
goal complete because one milestone ships, the remaining work is difficult, or
the context window is ending. Record incomplete work and continue with the next
highest-priority acceptance gap.
```

## Definition of done

All of the following must be true:

1. A user can inspect a local or pinned remote skill without activating it or
   executing bundled code.
2. A user can try it for one disposable session or borrow it with a TTL over the
   actual current blend, without creating durable adoption state.
3. A surface lock resolves adopted and leased skills to immutable content
   identity, not only names or version strings.
4. Startup bootstrap inventories all supported discovery scopes, verifies exact
   expected revisions, repairs only stale Spindle-owned projections, preserves
   foreign state, and blocks or explains collisions.
5. Stable Claude and Codex hooks attest startup, resume/compaction, and subagent
   state without embedding mutable pins in hook definitions or flooding context.
6. Parent and child agents independently resolve and prove their actual model,
   realization, effective tools, permissions, and activation state.
7. A successful lease can be explicitly adopted; adoption is the only trial
   path that changes durable desired state.
8. Updates run beside incumbents as candidate trials. Rollback, disable,
   quarantine, release, and retirement preserve history and remove only owned
   runtime state.
9. Evaluation separates availability, activation, routing, authorization, and
   behavior; supports named arms and ablations; and can prove that a smaller or
   empty steering residue is non-inferior for a bounded runtime coordinate.
10. Claude Code and Codex adapters pass the published conformance suite on named
    builds, including clean, stale-owned, foreign-conflict, resume, expired-lease,
    mixed-model delegation, and crash-recovery cases.
11. All durable schemas are versioned and migrated; all mutating commands expose
    a plan or dry-run; all receipts are content-addressed and reproducible except
    for explicitly non-addressed observation metadata.
12. The public documentation, CLI help, examples, and migration guide describe
    the implemented behavior accurately.
13. A user can invoke `$spindle` in Codex or `/spindle` in Claude Code to inspect
    current lifecycle state and drive exact dry-run/apply commands; mixed-harness
    nesting routes to the active child, and status separates operator custody,
    hook configuration, and observed startup evidence.

## Operating contract

Use these rules while the goal is active:

- Begin each continuation by reading the current roadmap, repository state,
  latest receipts, and failing acceptance gates. Do not restart completed work.
- Keep at most one milestone's main vertical slice in progress. Parallelize only
  bounded research, adapter, or validation tasks whose file ownership is clear.
- Prefer executable acceptance tests and raw receipts over architectural claims.
- Run focused tests during implementation and the full suite before closing a
  slice.
- Validate harness-specific claims through the actual harness version under test
  and record the build. Do not generalize from undocumented behavior.
- When an API or harness limitation blocks one adapter, preserve the portable
  contract, report the capability gap, and continue other meaningful work.
- Treat a changed model, harness build, toolset, policy, package digest, or active
  blend as evidence drift that may reopen a previously passing claim.
- Keep startup fast: no network fetch, deep scan, or behavioral evaluation in the
  normal session-start hook path.
- Keep the worktree safe. Preserve unrelated user changes and never clean foreign
  skill directories as a convenience.
- Update ROADMAP.md when evidence changes sequencing or a gate, but do not weaken
  a gate merely to declare progress.

## Acceptance journey

The final system must demonstrate this scenario on both reference harnesses:

```text
1. Begin with a fresh repo plus one unrelated user-managed skill.
2. Inspect a pinned candidate without installing or executing it.
3. Try it read-only over the current blend and retain startup, activation, and
   run receipts.
4. Borrow it for a bounded TTL and verify a new session loads the exact digest.
5. Delegate to a differently modeled child and prove independent realization.
6. Introduce a stale Spindle-owned link and a same-name foreign skill.
7. Bootstrap repairs the owned link, preserves the foreign skill, and blocks or
   requires an explicit conflict decision.
8. Adopt the useful lease and restart with the adopted lock.
9. Present an upstream update, test it beside the incumbent, reject one failing
   revision, and promote one passing revision.
10. Change the harness/model coordinate and observe the evidence become stale.
11. Rebaseline, distill redundant steering when non-inferior, and retain the
    richer references progressively disclosed.
12. Roll back, disable, and retire the skill while preserving historical
    receipts and the unrelated user-managed skill.
```

## Checkpoint language

Use this for subsequent continuation turns:

```text
Continue the active Spindle completion goal. Read VISION.md, ROADMAP.md, and
GOAL.md; inspect the current repository, plan, receipts, and tests; then implement
the highest unblocked acceptance gap in the current roadmap milestone. Validate
the vertical slice with focused tests and any required live harness evidence,
update the roadmap truthfully, and continue while safe meaningful work remains.
Do not repeat completed work, broaden into a later milestone prematurely, mutate
foreign skill state, or mark the goal complete until every definition-of-done
item and final acceptance journey passes.
```

## Completion report

The final report should name:

- the release and schema versions;
- the certified harness builds and capability matrix;
- the full automated test/lint results;
- the acceptance-journey receipt IDs;
- known limitations and explicitly unsupported harness behavior;
- migration and rollback paths; and
- evidence that foreign state remained intact.
