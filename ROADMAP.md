# Spindle roadmap

Status: execution roadmap for [VISION.md](VISION.md), 2026-10-15. The lifecycle
milestones (1 to 7) are complete; this roadmap adds the sourcing phase
(milestones 8 to 13).

## Outcome

Close the loop from task to guidance to outcome, for every agent an estate
runs:

```text
house rules + kernel (always) ─┐
                               ├─> task -> find -> judge -> hand over -> work
catalog (pinned, on demand) ───┘                                           │
       ^                                                                   v
       └──── promote / demote <── evaluate <── usage record <── grade + report
```

Each milestone leaves a usable path, durable records, and tests, and names a
gate that real use, not only unit tests, must pass. Command names may change;
the semantic boundaries and gates should not.

## Where we are

**The lifecycle (0.2 to 0.3, milestones 1 to 7, complete 2026-07-31).** The full
text, with implementation evidence and gates, is in the
[2026-07-31 roadmap](https://github.com/lavallee/spindle/blob/d290d66/ROADMAP.md).

| # | Milestone | Delivered |
| --- | --- | --- |
| 1 | Desired state, ownership, inventory | Versioned lock, ownership receipts, effective cross-scope inventory. |
| 2 | Startup bootstrap and hooks | `bootstrap`/`launch`, stable Claude and Codex hooks, `restart-required`. |
| 3 | Intent cards and leases | `inspect`, `try`, `borrow`, `release`, expiry. |
| 4 | Pinned remote try-on | Immutable source snapshots, non-executing export, trust preflight. |
| 5 | Adoption and maintenance | `adopt`, update-as-trial, health, rollback, disable, retire. |
| 6 | Minimalism and distillation | Named-arm experiments, ablations, non-inferior residues. |
| 7 | Certification and hardening | Conformance suite, adapter matrices, migration, recovery, policy. |

**Sourcing (0.4, October 2026).** Shipped:

- the house: rules, kernel, and patterns installed into Claude Code, Codex, and
  Hermes per machine, vendored per project, and kept current by `house update`;
- the catalog: commit-pinned sources with `include`/`exclude`, non-executing
  export, per-skill digests and static indicators, and `catalog update` diffs;
- `find`, `use`, `report`, and `usage`, with full-text recall, an optional search
  expander, a usage prior, a decision-model judge, and selection receipts; and
- `brief` for job runtimes: prompt block, skill record, read roots, `SPINDLE_JOB`
  attribution, bounded inlining, and fail-soft behavior.

**What the first weeks of real use showed.**

- Runtimes integrate in a day, and jobs carry exact skill records into review.
- Outcomes accumulate slowly: a handful of graded jobs per week is far too few to
  tell whether an offered skill helped.
- The judge threshold (0.6) and inline threshold (0.7) were set by hand. Nobody
  has measured selection precision.
- The kernel was chosen by judgment and has never been re-evaluated.
- Adding a source is a manual procedure: pin, filter, try queries, review.
- Only three harnesses receive the house. Task text goes to a remote judge by
  default.

## Invariants across every milestone

The lifecycle invariants still hold:

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

Sourcing adds:

11. Sourcing never gates work. Every failure degrades to "no skills offered".
12. Every offer is recorded with each skill's digest and the reason it was chosen.
13. Recall and judgment stay separate, and an unjudged shortlist is labelled.
14. House rules outrank skills; nothing third-party executes.
15. Any step that sends task text off the machine can be turned off, and says so.

## Milestone 8: outcomes that evaluators feed

Today outcomes come from one `report` per job, usually from the runtime. The
richest judgment, the reviewer's, never reaches the record.

### Deliver

- A per-skill verdict format that a reviewer or critic agent can emit beside its
  review: `helped`, `hurt`, or `no effect`, with a one-line reason tied to the
  work.
- `report` accepts several verdicts per selection from different reporters, each
  identified (runtime, grader, critic, person), and keeps them separate.
- A short evaluator brief (`spindle brief --for-review`) that tells a reviewer
  which skills the producer was offered and opened, and how to give a verdict.
- `spindle usage <ref>` shows a skill's history: offers, reads, verdicts by
  reporter, and the jobs behind them.
- The usage prior weights direct reviewer verdicts above weak "was loaded"
  evidence, with the weights documented.

### Gate

On a reference job runtime over two weeks, at least 80% of graded jobs that
were offered a skill carry a reviewer verdict for it, and `usage` can show, for
each of the ten most-offered skills, a verdict count large enough to rank them.

## Milestone 9: selection quality, measured

### Deliver

- A selection evaluation set: real tasks paired with the skills that helped or
  hurt, drawn from Milestone 8 verdicts plus hand-labelled cases, split into
  development and held-out.
- `spindle eval selection` reporting precision and recall at k for recall alone,
  recall with expansion, and the full judged pipeline, with cost and latency.
- Calibrated thresholds for selecting and inlining, chosen on development cases
  and checked on held-out ones.
- A local judge and expander path (a small local model, or none) for work whose
  task text must not leave the machine, measured on the same set.

### Gate

On held-out cases, judged selection beats the lexical shortlist on precision at
2 by a stated margin, the chosen thresholds are recorded with their evidence,
and the local path's quality loss is measured and documented.

## Milestone 10: catalog curation

### Deliver

- `catalog add` for a new source: resolve and pin, propose `include`/`exclude`
  from the repository's layout, sync into a scratch home, and run a short list of
  queries the source should win and lose, as one reviewable change.
- `catalog update` summaries per skill (description and body changes, new
  indicators, removed skills that were recently offered), not only counts.
- Harness-specific metadata recorded per skill (for example, "user-invoked only"
  or a harness tool name it depends on) and shown in `find` and the handover.
- Source health: commits since pin, last sync, skills never offered, skills with
  negative verdicts.
- A scout that proposes candidate sources from what the estate reads about, as
  assessments to accept or reject, never as automatic additions.

### Gate

A new third-party source is admitted, and an existing one updated, entirely
through these commands, with the query results and per-skill diffs in the
change that a person reviewed.

## Milestone 11: promotion and demotion across the house

### Deliver

- `spindle house review`: kernel and pattern skills with little use or negative
  verdicts; catalog skills with strong positive verdicts; each with its evidence.
- Promotion from catalog to pattern or kernel requires a paired evaluation on
  held-out real tasks (the existing `eval` machinery) and a house change.
- Demotion from kernel to pattern or catalog uses the same evidence and leaves the
  skill available on demand.
- House rules get the same treatment: a rule that keeps being broken is a
  candidate to become a check, and a rule nothing exercises is a candidate to go.

### Gate

At least one promotion and one demotion are decided from recorded evidence, with
the evaluation receipt and the house change linked, and the kernel is no larger
afterwards than before.

## Milestone 12: reach

### Deliver

- House setup for more harnesses (OpenCode and pi first), each with a live check
  that a new session actually loaded the rules.
- A house bundle for environments that never run setup (hosted agents,
  containers, CI): rules, kernel, and catalog access in one exportable form.
- A versioned `brief`/`report` contract with a schema and a conformance test a
  runtime can run, and a reference integration guide.
- Multi-machine status: which machines and harnesses carry which house version.

### Gate

Every supported harness passes the live load check on a named build, a container
with no setup uses the bundle to source a skill, and a second runtime integrates
from the contract and guide alone.

## Milestone 13: tools in the catalog

Skills are one kind of guidance. Agents also need to find the right tool: a CLI,
an API, an MCP server, an estate's own purpose-built service.

### Deliver

- Catalog entries for tools: what the tool does, when to prefer it, how to call
  it, and what authority it needs, indexed beside skills.
- `find` returns skills and tools together, judged the same way, and the
  handover says how to reach the tool, never installs it.
- Tool outcomes join the same usage record.

### Gate

For a reference set of tasks where an estate tool should be preferred over a
generic one, the judged pipeline offers that tool, and agents use it, measurably
more often than with a static routing skill alone.

## Cross-cutting workstreams

These advance with every milestone rather than waiting for a final hardening
phase.

### Schema and migration

Version all durable records from their first release, including selection
receipts and the usage ledger. Readers should reject unknown required fields,
preserve unknown optional fields where practical, and provide explicit
migrations rather than best-effort reinterpretation.

### Security and consent

Model instruction visibility, bundled code execution, tool installation,
network access, credentials, hook installation, durable adoption, and sending
task text to a remote model are separate grants. Test each boundary.

### UX and explanations

Every mutating command should have a plan/dry-run representation. Every blocked
decision should say what was expected, what was observed, what Spindle preserved,
and the smallest corrective action. Every selection should say why each skill
was or was not offered.

### Performance

Startup uses local hashes and cached metadata. A `find` or `brief` should answer
in seconds, degrade to no offer rather than wait, and never block a job on the
network.

### Compatibility research

Harness capabilities move quickly. Keep adapter behavior behind conformance
tests and dated evidence rather than embedding transient CLI flags in portable
packages or core schemas.

## Release slices

| Release | Coherent user outcome |
| --- | --- |
| `0.5` | Reviewers feed per-skill verdicts; each skill has a visible history. (M8) |
| `0.6` | Selection quality is measured, thresholds calibrated, a local path exists. (M9) |
| `0.7` | Sources are admitted and updated through reviewed, tested commands. (M10) |
| `0.8` | The house is reviewed against evidence; promotion and demotion work. (M11) |
| `0.9` | More harnesses, a portable house bundle, a versioned runtime contract. (M12) |
| `0.10` | Tools found and judged beside skills. (M13) |

Versions express dependency order, not calendar commitments. Milestones 10 and
12 do not depend on 9 and may ship earlier.

## Explicitly deferred

- Building a single canonical public skill marketplace.
- Automatically executing third-party setup scripts during inspection or sync.
- Letting skills choose their own model, permissions, or promotion.
- Removing foreign harness state without explicit user ownership transfer.
- Universal adapter behavior inferred from one harness build.
- Popularity-based global quality scores detached from task and runtime context.
- Automatic admission of a source, or automatic promotion into the house.

## Execution rule

Implement the highest unblocked milestone as an end-to-end vertical slice, and
prove it in a real estate, not only in tests. Prefer the milestone that produces
evidence the next one needs: outcomes before measurement, measurement before
promotion. Do not call a milestone complete when its gate names real use that has
not happened yet.

The paste-ready objective and completion contract are in [GOAL.md](GOAL.md).
