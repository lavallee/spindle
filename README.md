# Spindle

**Spindle** composes source skills into tight, surface-specific blends.

[![CI](https://github.com/lavallee/spindle/actions/workflows/ci.yml/badge.svg)](https://github.com/lavallee/spindle/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

📖 **Documentation site: <https://lavallee.github.io/spindle/>** — the rationale,
how it works, the evaluation model, and a practical guide. Machine-readable
surface for agents: [`llms.txt`](https://lavallee.github.io/spindle/llms.txt) and a
single-file [`bundle.md`](https://lavallee.github.io/spindle/bundle.md).

## Why

Agent "skills" — the reusable instruction files a coding agent loads to do a job
well — multiply fast. The instinct is to install every useful skill globally so
it's always available. That instinct is right; the result is not. A global **pile**
is never vetted as a *set*: it spends context budget on skills the repo will never
use, combines skills from different authors in ways no author tested (a "pidgin"),
pushes each skill toward one-size-fits-all bloat, ignores that different surfaces
want different skills phrased differently, and lets guardrails erode.

Spindle keeps each skill small and canonical and puts coherence at the
**composition layer**. It resolves a tight subset per surface, renders it for the
target harness and model, checks it before anything lands — and, separately, proves
a skill actually *improves behavior* rather than merely being present. One command
does it:

```bash
spindle bind /path/to/repo --harness claude
# classify → select → resolve → render → lint → materialize → record  (fails closed)
```

See the [rationale](https://lavallee.github.io/spindle/rationale.html) for the full
argument, including why that extra step pays for itself.

## Quick start

```bash
uv sync --extra dev

spindle dist install examples/spindle-sample/distributions/spindle-sample
spindle dist activate spindle-sample

spindle doctrine show
spindle skill list
spindle bind /path/to/repo --harness claude
```

`spindle bind` classifies the target repo, selects the channels it subscribes to,
resolves them into one blend, renders through the active harness/model profiles,
lints the blend for coherence, and materializes the selected skills into the
surface's harness-native skills directory (`.claude/skills/`, `.agents/skills/`, …).

## Harnesses

Most harnesses discover project skills repo-locally, so `bind` symlinks into a
directory inside the target repo:

| Harness | Materialization target |
| --- | --- |
| `claude` | `<repo>/.claude/skills/` |
| `codex` | `<repo>/.agents/skills/` |
| `pi` | `<repo>/.pi/skills/` |
| `hermes` | `~/.hermes/skills/spindle/` (global) |

### Hermes

Hermes only discovers skills by recursively walking its global
`~/.hermes/skills/` tree (following symlinks); it does not read repo-local
`.hermes/skills` directories. `spindle bind <repo> --harness hermes` therefore
symlinks the blend into a dedicated, spindle-owned category directory —
`~/.hermes/skills/spindle/` by default, overridable with
`SPINDLE_HERMES_SKILLS_DIR` — so hand-curated Hermes categories are never
touched. The repo argument still names the binding surface; only the target
directory is global, and reconcile/unbind semantics are identical to the other
harnesses (only spindle-owned symlinks are ever removed).

Caveat: because the target is one shared directory, skills from different
surfaces bound with `--harness hermes` share a namespace there. And there is no
hermes dialect profile yet — skills land in their claude-reference dialect;
rendering/profile transforms for hermes are future work.

## Concepts

| Term | Meaning |
| --- | --- |
| package | A pip-installable project that declares skills and capabilities in `[tool.spindle.package]`. |
| distribution | A pip-installable bundle that declares `[tool.spindle.distribution]` and depends on packages. |
| channel | A versioned `(scope × harness)` manifest listing the skills a surface should receive. |
| surface | A repo or agent that consumes a skill blend. |
| profile | A harness/model renderer such as `identity`, `terse`, or `trim`. |
| blend | The resolved skill subset for a surface, plus the absolutes in force. |
| doctrine | The versioned first-principles set (preferences, absolutes, meta-principles) skills are checked against. |

Full walkthrough of the data model and the pipeline:
[How it works](https://lavallee.github.io/spindle/how-it-works.html).

## Reference layout

```text
examples/spindle-sample/
  packages/sample-planning/              # [tool.spindle.package]
  distributions/spindle-sample/          # [tool.spindle.distribution]
  channels/system/system/claude/         # sample channel
  profiles/                              # harness/model render profiles
  doctrine/                              # minimal doctrine used by lint/render
  peers/ verdicts/ scout/ roster/        # optional learning/marketplace scaffolds
```

## Build your own

```bash
spindle package new my-tools --dest ./packages/my-tools \
  --skill clarify --skill review --capabilities planning

spindle dist new my-dist --dest ./distributions/my-dist \
  --source-dir ../../ \
  --package my-tools==0.1.0
```

Spindle discovers installed packages through `[tool.spindle.package]` metadata and
installed distributions through `[tool.spindle.distribution]`. The
[guide](https://lavallee.github.io/spindle/guide.html) covers authoring skills,
writing channels, and tuning per-surface profiles.

## Pluggable sinks

The OSS base includes local reference implementations; private infrastructure lives
in separate adapter packages that depend on Spindle rather than being imported by
Spindle core.

- `spindle ingest` writes a topo-ordered task queue to `SPINDLE_TASK_QUEUE` or
  `$SPINDLE_HOME/tasks.jsonl` unless `SPINDLE_TASK_URL` is set.
- `spindle gate file` writes decision gates to `SPINDLE_GATE_QUEUE` or
  `$SPINDLE_HOME/gates.jsonl`.
- `spindle scout` materializes per-peer prompts and emits commands from
  `SPINDLE_SCOUT_COMMAND`.

## Behavioral evaluation

Rendering and binding prove that a skill is *available*, not that it *improves* an
agent. Spindle evaluation manifests run the same cases with and without a skill,
randomize pair order from a seed, and write a receipt whose promotion gate uses only
held-out behavioral scores.

```bash
spindle eval validate examples/evaluation-sample/eval.toml
spindle eval run examples/evaluation-sample/eval.toml
spindle eval show examples/evaluation-sample/receipts/<receipt>.json
```

The runner is an argv contract rather than a built-in model client. A local test
harness or isolated executor can implement it while Spindle owns the manifest,
hashes, pairing, evidence validation, and promotion decision. See
[Behavioral Skill Evaluations](docs/skill-evaluations.md) and the
[evaluation overview](https://lavallee.github.io/spindle/evaluation.html).

For tasks where one failure must not be averaged away, a manifest may name
`[acceptance].required_variant_gates`. Every held-out variant must pass every named
gate, with evidence, before its score can count toward promotion. The runner or
package defines each gate's meaning and oracle; Spindle only enforces the
conjunction. See the deterministic
[`outcome-uat` example](examples/outcome-uat/eval.toml).

## Documentation site

The site under [`docs/`](docs/) is an [artoo](https://github.com/lavallee/artoo)
artifact (see [`artifact.toml`](artifact.toml)). It is served by GitHub Pages
directly from the `/docs` folder on `main` — no build step — so
**Settings → Pages → Source = Deploy from a branch, `main` / `docs`** is all it
needs. Edit the pages in `docs/` and push.

## Development

```bash
uv run --extra dev pytest
```

MIT licensed. Contributions welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).
Release process and versioning: [RELEASING.md](RELEASING.md).
