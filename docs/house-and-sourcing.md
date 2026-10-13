# The house, the catalog, and sourcing skills on demand

Spindle's lifecycle commands manage one skill at a time with full evidence. This
page covers the lighter path most sessions need: a small set of rules and skills
that is always installed, and a large catalog that is searched only when a task
calls for it.

The reason for the split is selection accuracy, not token cost. A harness shows
the model a name and a description for every installed skill, and the model picks
worse as that list grows. Keeping the always-on list short, and reaching the rest
through a search step, keeps both the short list and the long tail usable.

## The house

A *house* is a directory you keep under version control, usually inside the
repository that holds your own skills:

```text
house/
  house.toml      version, kernel skill list, project patterns
  RULES.md        rules every harness loads on every machine
  patterns/*.md   extra rules for one kind of project (optional)
  catalog.toml    pinned sources of on-demand skills
```

```toml
schema = "spindle.house/v1"
version = "0.1.0"
skill_roots = ["../packages"]        # where the named skills live

[kernel]
skills = ["orient", "review"]        # linked into every harness

[patterns.data-publication]
description = "Static data sites"
rules = "patterns/data-publication.md"
skills = ["chart-review", "publish-gate"]
```

Point a machine at the house once, then install:

```bash
spindle house init ~/src/my-skills/house
spindle house setup            # every harness found on this machine
spindle house status
```

`setup` writes `RULES.md` into a managed block in each harness's always-loaded
instruction file and links each kernel skill into its skill directory:

| Harness | Rules | Kernel skills |
| --- | --- | --- |
| Claude Code | `~/.claude/CLAUDE.md` | `~/.claude/skills/` |
| Codex | `~/.codex/AGENTS.md` | `~/.agents/skills/` |
| Hermes | `~/.hermes/SOUL.md` | `~/.hermes/skills/spindle/` |

Text outside the managed block is never touched. A link is created or retargeted
only when it is missing, dead, recorded as installed by an earlier `setup`, or an
older Spindle render; anything else is reported as a conflict and left alone.
`--prune-dangling` also removes dead symlinks from those skill directories.
`--dry-run` shows the plan, and `spindle house remove` undoes the setup for a
harness. After editing the house, bump `version` and run
`setup` again; `status` reports rules that are stale or were edited by hand.

Keep a machine current with one command, suitable for a timer:

```bash
spindle house update
```

It fast-forwards the Git checkout that holds the house (and leaves it alone if
that is not a clean fast-forward), reinstalls rules and kernel for the harnesses
this machine already has set up, and rebuilds the catalog index.

### Projects

A repository opts into a pattern, and the pattern travels with it:

```bash
spindle house setup --here --pattern data-publication
spindle house status --here
```

This writes the pattern's rules into a managed block in `AGENTS.md` (and in
`CLAUDE.md` when that file exists and does not import `AGENTS.md`; a missing
`CLAUDE.md` is created as a one-line import), copies the pattern's skills to
`.agents/skills/<name>`, and adds a relative link from `.claude/skills/<name>`.
The copies are meant to be committed, so they work in worktrees, on other
machines, and in dispatched jobs. `.spindle/house.json` records the pattern and
each skill's digest; a later `setup --here` updates from the house and refuses
to overwrite a copy that was edited in the repository unless `--force` is given.
Add `--with-house-rules` to embed the full house rules in the repository for
environments that never run the machine-level setup.

## The catalog

`catalog.toml` lists sources. Nothing in it is installed.

```toml
[[source]]
slug = "ours"
path = "../packages"                 # a local directory, read in place

[[source]]
slug = "upstream"
ref = "github:owner/repo@<40-character commit>"
track = "main"
```

```bash
spindle catalog sync       # export pinned sources, rebuild the index
spindle catalog list
spindle catalog update     # what would a newer upstream commit change?
spindle catalog update upstream --apply
```

A Git source must pin a full commit. `sync` exports it through the same
non-executing snapshot path as `spindle inspect`: no hooks, no install scripts,
no package managers. The index records each skill's digest, whether it hard-codes
its own install location (and so cannot be used from a snapshot), and static
indicators of network, credential, or shell use. `update` compares the pin with
the tracked branch and reports added, changed, and removed skills and any new
static indicators; `--apply` rewrites the pin, which you review as an ordinary
diff to the house. Kernel skills are indexed but excluded from search because
they are already loaded.

## Sourcing: find, use, report

```bash
spindle find "debug a flaky test that only fails in CI"
spindle use upstream/systematic-debugging      # prints the SKILL.md path
spindle report --outcome accepted --helped upstream/systematic-debugging
spindle usage
```

`find` ranks by text match over each skill's name, description, and body,
weighted by how the skill has fared in earlier reports. Text match finds the
right neighbourhood but cannot tell "relevant" from "shares words with the
task", so without a judge `find` returns a *shortlist* marked `lexical` and
whoever receives it does the judging.

A commission and a skill description often share no words, so the house can name
a *search expander*:

```toml
[sourcing]
expand = "bin/skill-queries"     # relative to the house directory
```

It is any executable that reads the task on stdin and prints a few short search
phrases, one per line, naming the kinds of skill that would help; usually a
small model call. `find` ranks the catalog once per phrase and once for the task
text, then fuses the rankings by reciprocal rank. A missing command, a non-zero
exit, a timeout, or empty output means no expansion, and `--expand none` skips
it. Task text reaches whatever the command calls.

With a judge, `find` makes a selection. The built-in judge is the Jev decision
model: one call asks, per candidate, whether loading that skill would materially
improve the work, and gets back a calibrated probability. Candidates at or above
0.6 are selected, and selecting nothing is a valid answer. Enable it with
`TYPESAFE_API_KEY`, or name a key file with `SPINDLE_JEV_KEY_FILE` or
`jev_key_file = "..."` in `~/.spindle/house.toml`. The judge is advisory and
fail-soft: a missing key, a timeout, or a malformed answer falls back to the
lexical shortlist and says so. Task text is sent to the judge's provider; use
`--judge none` when that is not acceptable.

`use` hands over one skill as a path to read, which works in any harness that
can read files and needs no install, lease, or reload. `--print` emits the text
instead. Use a lease (`spindle try`, `spindle borrow`) only when a skill has to
appear in the harness's native skill list.

Every step appends to `~/.spindle/usage.jsonl`: what was offered and selected,
what was read, and how the work was judged. `report --helped` and `--hurt` are
direct verdicts; an outcome on a run that merely had a skill loaded counts as
weak evidence. `usage` shows the counts and the resulting prior for each skill.

## For runtimes that dispatch work

A job runner needs one call before dispatch and one after grading:

```bash
spindle brief --json --task-file - --repo "$WORKTREE" < commission.md
spindle report --selection "$SELECTION" --job "$JOB_ID" \
  --outcome accepted --loaded upstream/systematic-debugging
```

`brief` returns three things:

- `prompt_block`: a prompt section offering the selected skills. By default it
  lists each skill with the path to read, so the agent pays for a skill only if
  it uses it. `--inline` embeds the skill text for sandboxes that cannot read
  outside their workspace.
- `skills`: a compact record (selection id, how it was selected, delivery mode,
  and each offered skill's reference, digest, and judged probability). Store it
  beside the job's own receipt so a reviewer or evaluator can see what guidance
  the producer was given, and pin exactly which skill bytes were in play.
- `selection`: the id to pass to `report`.

Without a judge, `brief` does not offer its text matches: a shortlist built from
a whole commission is mostly noise. It returns a short "skills on demand" section
that tells the agent how to run `find` itself once it knows what it is about to
do (`--unjudged shortlist` or `--unjudged none` change that). Set `SPINDLE_JOB`
in the agent's environment and every `find` and `use` it runs is attributed to
the job, so the later `report --job` joins them without the agent passing ids.

`--inline` embeds at most two skills, and only ones the judge scored 0.7 or
higher: embedded text is paid for whether or not the agent uses it.

Add `--rules` to get the house rules in the same answer for runtimes that do not
load a harness instruction file. An empty `prompt_block` means nothing was
offered; treat any failure the same way. Skill sourcing should never gate a job.
