# Spindle completion goal

Status: active for the sourcing phase (roadmap milestones 8 to 13), set
2026-10-15. The lifecycle goal (milestones 1 to 7) was completed on 2026-07-31;
see [the previous goal](#previous-goal).

This is paste-ready language for running [VISION.md](VISION.md) and
[ROADMAP.md](ROADMAP.md) to completion as one persistent implementation goal.

## Objective

```text
Implement the sourcing phase of Spindle's VISION.md and ROADMAP.md end to end:
close the loop from task to guidance to outcome for every agent an estate runs.

Every agent, in an interactive harness or a dispatched job, should load the
current house rules and kernel, be offered only the catalog skills (and later
tools) a judge expects to materially help, receive them as files to read, and
leave a per-skill record of whether they helped that reviewers and critic agents
contribute to. That record must be good enough to measure selection quality,
calibrate thresholds, and decide promotion and demotion across the house.

Work milestone by milestone in ROADMAP.md dependency order (outcomes before
measurement, measurement before promotion), completing the highest unblocked
vertical slice before expanding scope. Keep sourcing fail-soft: it never gates a
job. Never execute third-party code to index or hand over a skill. Keep house
rules above skills. Record every offer with exact digests. Say what task text
leaves the machine, and keep a local path.

The goal is complete only when every milestone gate from 8 to 13 passes in real
use on at least one estate (a set of machines, harnesses, projects, and a job
runtime), the full test and lint suites pass, schemas and documentation are
current, and the acceptance journey below succeeds. Do not mark the goal
complete because one milestone ships, the remaining work is difficult, or a gate
needs more real use than has happened yet. Record incomplete work and continue
with the next highest-priority gap.
```

## Definition of done

1. One versioned house installs rules and kernel into every supported harness on
   every machine, and a merged house change reaches all of them through a timer
   without manual steps.
2. A project's vendored pattern stays current with the house, and a container or
   hosted agent with no setup can still load the rules and reach the catalog.
3. A new third-party source can be admitted, filtered, tested on queries it
   should win and lose, and later updated, entirely through reviewed commands.
4. `find` and `brief` separate recall from judgment, label unjudged shortlists,
   offer zero to two skills for a typical task, and degrade to "no offer" on any
   failure.
5. Every selection has a receipt with digests and reasons, and every graded job
   that was offered a skill carries per-skill verdicts from its reviewer.
6. Selection precision and recall are measured on held-out real tasks, for the
   remote and the local judge, and the thresholds in use cite that evidence.
7. Promotion and demotion between catalog, pattern, and kernel are decided from
   recorded evidence and a paired evaluation, and the kernel does not grow
   without one.
8. Tools are indexed, judged, and handed over beside skills, with outcomes in the
   same record.
9. The `brief`/`report` contract is versioned with a conformance test, and a
   second runtime has integrated from the documentation alone.
10. The lifecycle's guarantees (ownership, startup integrity, leases, adoption,
    updates as trials) still pass their conformance suite.
11. The public documentation, CLI help, and examples describe the implemented
    behavior accurately.

## Operating contract

- Begin each continuation by reading the roadmap, the repository, the latest
  usage and selection records, and failing gates. Do not restart completed work.
- Prefer evidence from real use over synthetic cases, and say which one a claim
  rests on.
- Keep at most one milestone's main slice in progress. Parallelize only bounded
  research, adapter, or validation work with clear file ownership.
- Run focused tests while building and the full suite before closing a slice.
- When a gate needs more real use than exists, keep the instrumentation running,
  report the count, and move to the next unblocked milestone instead of
  weakening the gate.
- Treat a changed model, harness build, judge, threshold, or catalog pin as
  evidence drift that may reopen a passing claim.
- Never let sourcing slow startup or block a job. Never add a skill to the kernel
  to make a metric move.
- Keep the worktree safe. Preserve unrelated user changes and never clean foreign
  skill directories as a convenience.
- Update ROADMAP.md when evidence changes sequencing or a gate, but do not weaken
  a gate merely to declare progress.

## Acceptance journey

```text
1. Start from a fresh machine and a house repository; install the house into
   every supported harness and confirm a new session in each loaded the rules.
2. Vendor a pattern into a project, then move the house version and watch the
   project report itself behind and update.
3. Admit a public skill collection with a filter and a query test; confirm
   `find` offers its skills for tasks they fit and not for tasks they do not.
4. Run a week of real work through a job runtime with `brief` before dispatch,
   reviewer verdicts after, and `report` on every graded job.
5. Show each frequently offered skill's history, and the selection evaluation's
   precision for remote, local, and unjudged selection.
6. Recalibrate a threshold from that evidence and show the change in offers.
7. Promote one catalog skill and demote one kernel skill from the evidence, each
   with a paired evaluation receipt and a reviewed house change.
8. Update the pinned collection through a reviewed diff that lists per-skill
   changes and new indicators.
9. Find and hand over an estate tool for a task where a generic one would
   otherwise be used.
10. Run a container with no setup that loads the house bundle and sources a
    skill.
11. Run the lifecycle conformance suite and confirm nothing regressed.
```

## Checkpoint language

```text
Continue the active Spindle completion goal. Read VISION.md, ROADMAP.md, and
GOAL.md; inspect the repository, the usage and selection records, and failing
gates; then implement the highest unblocked gap in the current milestone. Prove
the slice with focused tests and, where the gate names it, real use. Update the
roadmap truthfully and continue while safe, meaningful work remains. Do not
repeat completed work, broaden into a later milestone prematurely, weaken a gate,
or mark the goal complete until every definition-of-done item and the acceptance
journey pass.
```

## Completion report

The final report should name the release and schema versions, the harnesses and
builds verified, the estate and runtime the gates were proven on, test and lint
results, the selection-evaluation numbers and thresholds with their evidence,
the promotions and demotions made, known limitations, and the migration and
rollback paths.

## Previous goal

The lifecycle goal ran from July to 2026-07-31 and delivered an evidence-bearing
skill lifecycle for Claude Code and Codex: desired-state and ownership records,
effective inventory, startup bootstrap and stable hooks, intent cards, local and
pinned-remote leases, per-agent realization and activation evidence, adoption,
updates as trials, retirement, tuple-aware evaluation and distillation, and a
harness operator. Its full text, definition of done, and acceptance journey are
in [GOAL.md at d290d66](https://github.com/lavallee/spindle/blob/d290d66/GOAL.md).
