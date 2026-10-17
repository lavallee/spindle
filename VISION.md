# Spindle vision

Status: product direction as of 2026-10-15, after the house, catalog, and
on-demand sourcing shipped in 0.4. Supersedes the
[2026-07-31 vision](https://github.com/lavallee/spindle/blob/d290d66/VISION.md),
whose lifecycle remains part of this one.

## The promise

> Any agent, in any harness or runtime, gets the few skills that will help with
> the task in front of it, follows the same house rules everywhere, and leaves a
> record of whether those skills helped, which the people and agents judging
> the work can see.

Skills are the cheapest way to make an agent reliably good at a kind of work,
and good ones are now everywhere: your own, your team's, and public collections
with hundreds each. The constraint is no longer supply. It is choosing, from a
growing pool, the few that matter for this task, getting them to the agent with
almost no ceremony, and learning from the result.

Spindle's first vision was a lifecycle for installed skills: inspect, try,
borrow, adopt, verify startup, update, retire. That remains, and it is still how
a skill should enter a harness's native list. But most skills should never be
installed. Spindle is now the layer that decides which skill an agent sees, for
which task, and with what evidence.

## What Spindle is

Spindle is the skill layer for anything that runs agents: an interactive
harness on a laptop, a fleet of machines, or a runtime that dispatches jobs.

It has three parts, from always-on to on-demand:

| Part | Holds | Reaches the agent |
| --- | --- | --- |
| **House** | Rules every agent follows, a small kernel of skills, named project patterns. | Installed into every harness on every machine, and vendored into projects. Always loaded. |
| **Catalog** | Every other skill, ours and third-party, pinned to exact commits. | Searched and judged per task; handed over as a file to read. Never installed. |
| **Lifecycle** | The skills that must be in a harness's native list, or need more care. | Inspected, tried, leased, adopted, verified at startup, and retired with custody. |

And one loop runs through them:

```text
task -> find candidates -> judge -> hand over by path -> work -> grade -> report
  ^                                                                      |
  +------------------- usage prior, evaluations, promotion --------------+
```

Spindle is not:

- an installer that copies every discovered skill into every project;
- a marketplace or a registry (it federates other people's sources);
- a harness, an agent framework, or a job runner; or
- a prompt optimizer that rewrites skills without evidence.

## Why this shape

### Selection accuracy is the constraint

A harness shows the model the name and description of every installed skill
and lets it decide which to open. With ten good skills it chooses well. With two
hundred from five authors it chooses the wrong one, or none, far more often.
Token cost matters less than this. Every always-on skill must earn its place
against that cost, and everything else belongs in a catalog searched with the
task in hand.

### A text match is not a judgment

Full-text search finds the neighbourhood: skills that share words with the
task. It cannot tell a skill that would change the work from one that only
shares vocabulary. Spindle therefore separates recall (search, optionally over
phrases a small model writes from the task) from judgment (a decision model that
gives a calibrated probability that loading a skill would materially help).
Selecting nothing is a valid and frequent answer.

### Low ceremony or it will not be used

An offered skill is a path to a file. Any harness, sandbox, or job that can read
files can use it, with no install, reload, lease, or cleanup. One call before a
job picks the skills; one call after grading records the outcome. Sourcing is
fail-soft and never gates work.

### Outcomes, not anecdotes

Every offer, read, and graded outcome is recorded against the exact skill
digest. The record tunes future selection, tells an evaluator what guidance the
producer was given, and shows which skills deserve a real experiment. A skill
earns promotion, from catalog to pattern to kernel, with evidence; a kernel
skill that stops earning its place is demoted.

### Your rules travel

An estate has its own principles: how to work, which tools to use, what never to
do. They should load first in every harness on every machine, survive a fresh
container, and reach a dispatched job, from one versioned source. Third-party
skills are guidance under those rules, never over them.

### The best skills are somebody else's, pinned

Public collections improve weekly. Spindle should make them easy to use and safe
to follow: pinned by commit, exported without running anything, updated only
through a diff that shows what changed, and filtered to the parts that fit.

## Principles

These extend the lifecycle principles below; none of those is withdrawn.

1. **Keep the always-on list short.** The kernel holds only what most sessions in
   most projects use. Narrower skills go in patterns; the rest in the catalog.
2. **Judge, do not just match.** Recall and judgment are separate steps. A
   shortlist without a judge is labelled as one, and job runtimes do not offer
   unjudged matches.
3. **Hand over the least.** A path by default; embedded text only for sandboxes
   that cannot read, only for high-confidence choices, and only a few.
4. **Never gate the work.** A missing judge, a timeout, or any sourcing failure
   means "no skills offered", not a failed job.
5. **Record what was offered.** Every selection has a receipt with each skill's
   digest, so a reviewer, a critic agent, or an evaluation can pin exactly what
   the producer saw.
6. **Promote and demote with evidence.** The usage record says what to test; a
   paired evaluation decides what to keep. Popularity is not evidence.
7. **Rules outrank skills.** House rules load first. A skill never overrides
   the task, its acceptance criteria, or the rules.
8. **Nothing third-party executes.** Sources are exported without hooks, scripts,
   or package managers. Spindle reads skill text.
9. **Pins, not floating versions.** Upstream work arrives through a reviewed
   change to a pin, never silently.
10. **Say what leaves the machine.** Task text reaches the expander and the judge.
    Both can be turned off, and the default for sensitive work should be local.

## The lifecycle, still

For skills that must be installed, the July vision holds. In brief:

- **Intent before artifact.** Candidates are explained (outcome, trigger,
  contents, authority, cost, overlap) before they get any authority.
- **Temporary before durable.** `try` is one disposable session, `borrow` an
  expiring lease, and only `adopt` creates maintained state.
- **Desired state over ambient state.** What sits in a discovery directory is
  observed, not authorized. A lock and active leases define what is expected.
- **Own only what Spindle mutates.** Foreign skills, hooks, and directories are
  inventoried and never silently removed.
- **One package, many agent-local realizations.** Parent and child agents resolve
  independently from their model, role, tools, and policy.
- **Harness mechanics are not skill prose.** Reconciliation, routing, hooks, and
  receipts are deterministic adapter work.
- **Evidence is bounded.** "Works" names a digest, a runtime coordinate, a task
  distribution, and a budget.
- **Updates are trials.** A new revision runs beside the incumbent before it
  replaces it.
- **Minimalism is deletion under evidence.** As models improve, rebaseline and
  remove steering that no longer helps. That now applies to the kernel too.
- **Startup integrity.** Bootstrap before hooks; stable hooks over mutable state;
  `restart-required` rather than pretending an in-session repair is clean.

The record chain, startup contract, and conformance cases are in
[How it works](https://lavallee.github.io/spindle/how-it-works.html),
[startup integrity](docs/startup-integrity.md), and
[runtime realization](docs/runtime-realization.md).

## Trust and authority

Trying and sourcing must be easier than installing without becoming a path
around consent.

- Inspection, catalog sync, and structural scanning never execute bundled
  scripts. A clean scan is evidence, not proof of safety.
- The catalog records static indicators of network, credential, and shell use,
  and a pin update reports new ones before it is accepted.
- An offered skill is read, not installed: it gains no tool, network, or
  filesystem authority the agent did not already have.
- Unknown trials default to instruction-only, read-only authority. Tool,
  network, credential, and filesystem expansion is shown and granted separately.
- Hook installation is explicit and respects the harness's own trust review.
- Managed policy can prohibit local hooks, remote sources, executable skill
  resources, automatic reconciliation, or sending task text to a judge.
- Receipts record denials and mismatches; policy decides whether a run passes.

## Who uses it, and how

- **A person at a harness** asks the agent to work. House rules and the kernel
  are already loaded; the agent runs `spindle find` before unfamiliar or
  high-stakes work, reads what is offered, and the person or a grader reports
  the result.
- **A machine or fleet** runs `spindle house update` on a timer from a dedicated
  clone of the house, so every harness on it carries the merged rules and kernel.
- **A project** vendors a pattern into the repository, so worktrees, other
  machines, and dispatched jobs get the same rules and skills.
- **A job runtime** calls `spindle brief` before dispatch (prompt block, skill
  record, read roots), sets `SPINDLE_JOB` so the agent's own lookups are
  attributed, stores the skill record with the job's receipt, passes it to the
  reviewer, and calls `spindle report` after grading.
- **An evaluator or critic agent** sees the producer's skill record beside the
  work it judges, can attribute a defect to the guidance or to its absence, and
  reports `helped` or `hurt` for the skills it can tie to the result.

## What success looks like

Spindle is fulfilling this vision when, across an estate of harnesses, machines,
projects, and dispatched jobs:

- every agent loads the current house rules and kernel without anyone copying
  files, and a merged change to the house reaches all of them within a day;
- a new public collection can be pinned, filtered, tried on real queries, and
  made available in under an hour, and its upstream changes arrive as diffs;
- for a typical task, the judge offers zero to two skills, and the ones offered
  are opened and rated useful far more often than not;
- every graded job names the exact skills it was offered, and evaluators use that
  record;
- skill outcomes accumulate fast enough that promotion and demotion are decided
  by evidence, and the kernel stays small; and
- installed skills, where they are still needed, keep the lifecycle's guarantees.

The north star is useful agent behavior per unit of attention: the fewest,
best-chosen instructions, with a legible chain from task to guidance to outcome.

## Boundaries

- Spindle federates sources and never becomes the canonical marketplace.
- It does not execute third-party code to index or hand over a skill.
- It does not let a skill choose its own model, permissions, or promotion.
- It does not run jobs or own grading; it gives runtimes and graders the calls
  and records they need.
- Organization-specific providers, sinks, and estates live outside the open core
  and depend on it.

## Related design notes

- [The house, the catalog, and sourcing on demand](docs/house-and-sourcing.md)
- [Minimalist skills after the default shifts](docs/minimalist-skills-vision.md)
- [Skill lifecycle UX](docs/skill-lifecycle-ux.md)
- [Runtime skill realization](docs/runtime-realization.md)
- [Behavioral skill evaluations](docs/skill-evaluations.md)
