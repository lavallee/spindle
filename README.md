# Spindle

**Spindle chooses, hands over, and tracks the skills your coding agents use.**

It keeps a small set of rules and skills always on in every harness, a large
catalog of commit-pinned skills that is searched only when a task calls for one,
and a record of whether each skill helped. For the skills that must be
installed, it adds an evidence-bearing lifecycle and control plane: inspect
without executing, try before adopting, verify exact startup state, and update
or retire with custody.

[![CI](https://github.com/lavallee/spindle/actions/workflows/ci.yml/badge.svg)](https://github.com/lavallee/spindle/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

**Documentation: <https://lavallee.github.io/spindle/>.** Agents can read the
same content as [`llms.txt`](https://lavallee.github.io/spindle/llms.txt) or one
file, [`bundle.md`](https://lavallee.github.io/spindle/bundle.md).

## Why

A harness shows the model the name and description of every installed skill and
lets it pick. With ten good skills it picks well. With two hundred, from several
authors, it picks the wrong one or none far more often. Installing every useful
skill makes agents worse.

Spindle splits the list. The **house** is a short always-on list: rules every
agent follows and a kernel of skills most sessions use. The **catalog** keeps
everything else, your skills and public collections alike, available but out of
the list. For each task, search narrows the catalog, a judge decides whether any
candidate would materially help, and the agent gets a path to read. The outcome
is recorded against the skill, so the next choice is better informed.

## Install

```bash
uv tool install "git+https://github.com/lavallee/spindle@v0.4.2"
```

Python 3.11 or newer. The same Spindle is also a harness plugin, from the
public marketplace:

```bash
# Claude Code
claude plugin marketplace add lyra-forge/marketplace
claude plugin install spindle@lyra-forge

# Codex
codex plugin marketplace add lyra-forge/marketplace
codex plugin add spindle@lyra-forge
```

The plugin carries a launcher for its exact pinned source, so it needs no
separate package install. Start a new session afterwards; its first invocation
is `$spindle:spindle` in Codex or `/spindle:spindle` in Claude Code.

## The house

A house is a directory under version control:

```text
house/
  house.toml      version, kernel skill list, project patterns, sourcing
  RULES.md        rules every harness loads on every machine
  patterns/*.md   extra rules for one kind of project (optional)
  catalog.toml    pinned sources of on-demand skills
```

```bash
spindle house init ~/src/my-skills/house
spindle house setup --dry-run
spindle house setup            # Claude Code, Codex, and Hermes, as found
spindle house status
spindle house update           # pull, reinstall, rebuild the catalog (for a timer)
```

`setup` writes `RULES.md` into a managed block of each harness's always-loaded
instruction file (`~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`,
`~/.hermes/SOUL.md`) and links each kernel skill into its skill directory. Text
outside the block is never touched, and links it did not create are reported,
not replaced.

A repository opts into a pattern, and the pattern travels with it:

```bash
spindle house setup --here --pattern data-publication
```

That writes the pattern's rules into `AGENTS.md` (and `CLAUDE.md`), copies its
skills into `.agents/skills/` with links from `.claude/skills/`, and records
digests in `.spindle/house.json`. Commit the copies so worktrees, other
machines, and dispatched jobs see them.

## The catalog

```toml
[[source]]
slug = "upstream"
ref = "github:owner/skills@<40-character commit>"
track = "main"
include = ["plugins/upstream/skills/*"]
```

```bash
spindle catalog sync                       # export pinned sources, index them
spindle find "vet a benchmark before reporting the speedup"
spindle use upstream/benchmark-checklist   # prints the SKILL.md path to read
spindle report --outcome accepted --helped upstream/benchmark-checklist
spindle catalog update upstream            # what a newer commit would change
```

Sources are exported without hooks, install scripts, or package managers;
Spindle reads skill text and never runs a catalog skill's code. `find` ranks by
full-text search, optionally over phrases from a search expander, weights by
each skill's record, and asks a judge (the Jev decision model, with a
`TYPESAFE_API_KEY`) whether each candidate would materially help. Without a
judge it returns a shortlist marked `lexical`. Every offer, read, and outcome
goes to `~/.spindle/usage.jsonl`; `spindle usage` shows the result.

## For job runtimes

```bash
spindle brief --json --task-file - --repo "$WORKTREE" < commission.md
spindle report --selection "$SELECTION" --job "$JOB_ID" --outcome accepted
```

`brief` returns a `prompt_block` to append to the agent's prompt (skills offered
by path), a `skills` record to keep with the job's receipt (refs, digests, judged
probabilities), the `selection` id for `report`, and the `read_roots` a sandbox
must allow. Set `SPINDLE_JOB` in the agent's environment to attribute its own
`find` and `use` calls. Treat any failure as "no skills offered": sourcing never
gates a job. See [the catalog page](https://lavallee.github.io/spindle/catalog.html#runtimes).

## When a skill must be installed: try before adopting

Most skills never need installing. For one that must appear in a harness's
native list, or needs more care, Spindle keeps an evidence-bearing lifecycle:

```text
inspect → try/borrow → compose → bootstrap → realize → activate → evaluate
                                                                  │
                                                 adopt, update, distill, retire
```

```bash
# a small project-local operator plus stable startup hooks
spindle harness setup --harness codex --here --dry-run
spindle harness setup --harness codex --here
# then, in a new session: $spindle inspect a review skill for this task
# (in Claude Code:          /spindle inspect a review skill for this task)

spindle inspect ./candidate/review --for "review this migration" --harness codex --here --json
spindle try ./candidate/review --harness codex --task-file task.md --here
spindle borrow ./candidate/review --harness codex --until 2h --here
spindle bootstrap --harness codex --here --check
spindle adopt <lease-id> --here --owner you --reason "kept after trial" --dry-run
```

`inspect` is read-only. `try` and `borrow` work on content-addressed snapshots
and create leases, not adoptions. Startup compares the desired state with what
each harness can see, repairs only state Spindle owns, and preserves the rest.
Only `adopt` creates lasting custody. Paired evaluations (`spindle eval`) decide
whether a skill improves held-out work before it is promoted.

## Harnesses

| Harness | House rules | Skills (house kernel; `bind` targets) |
| --- | --- | --- |
| Claude Code | `~/.claude/CLAUDE.md` | `~/.claude/skills/`; `<repo>/.claude/skills/` |
| Codex | `~/.codex/AGENTS.md` | `~/.agents/skills/`; `<repo>/.agents/skills/` |
| Hermes | `~/.hermes/SOUL.md` | `~/.hermes/skills/spindle/` |
| pi | | `<repo>/.pi/skills/` |

Hermes discovers skills only under its global `~/.hermes/skills/` tree, so
Spindle writes to its own `spindle/` category there (override with
`SPINDLE_HERMES_SKILLS_DIR`) and never touches hand-curated categories. Skills
bound for Hermes from different repositories share that namespace.

## Documentation map

- [Overview](https://lavallee.github.io/spindle/), [why a small
  house](https://lavallee.github.io/spindle/rationale.html), [the
  house](https://lavallee.github.io/spindle/house.html), [the
  catalog](https://lavallee.github.io/spindle/catalog.html), and the
  [guide](https://lavallee.github.io/spindle/guide.html).
- [The house, the catalog, and sourcing on demand](docs/house-and-sourcing.md):
  the full reference.
- [The vetting lifecycle](https://lavallee.github.io/spindle/lifecycle.html) and
  [candidate inspection and leases](docs/local-lifecycle.md).
- [Startup integrity](docs/startup-integrity.md),
  [runtime realization](docs/runtime-realization.md), and
  [job-scoped leases](docs/job-scoped-leases.md).
- [Behavioral evaluation](docs/skill-evaluations.md) and the
  [evaluation page](https://lavallee.github.io/spindle/evaluation.html).
- [Adapter compatibility](docs/adapter-compatibility.md),
  [organization policy](docs/organization-policy.md), and
  [state custody](docs/migration-and-recovery.md).
- [Vision](VISION.md), [roadmap](ROADMAP.md), and [changelog](CHANGELOG.md).

## Pluggable sinks

The open base ships local reference implementations; private infrastructure
lives in separate adapter packages that depend on Spindle. `spindle ingest`
writes a dependency-ordered task queue to `SPINDLE_TASK_QUEUE` or
`$SPINDLE_HOME/tasks.jsonl` unless `SPINDLE_TASK_URL` is set. `spindle gate file`
writes decision gates to `SPINDLE_GATE_QUEUE` or `$SPINDLE_HOME/gates.jsonl`.
`spindle scout` materializes per-peer prompts and runs `SPINDLE_SCOUT_COMMAND`.

## Development

```bash
uv run --extra dev pytest
python scripts/build_docs.py      # after editing docs/*.html: nav, page links, bundle.md
```

The site in [`docs/`](docs/) is an [artoo](https://github.com/lavallee/artoo)
artifact served by GitHub Pages from `main`/`docs`. MIT licensed; see
[CONTRIBUTING.md](CONTRIBUTING.md) and [RELEASING.md](RELEASING.md).
