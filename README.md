# Spindle

**Spindle** is an evidence-bearing lifecycle and control plane for agent skills.

Inspect and try exact skill bytes before adopting them. Borrow them temporarily.
Compose the effective set for a project, verify it at harness startup, realize
the smallest evaluated instructions for each parent or child agent, and retain
the evidence needed to update, distill, roll back, or retire safely. See the
[vision](VISION.md), [roadmap](ROADMAP.md), and [completion goal](GOAL.md).

[![CI](https://github.com/lavallee/spindle/actions/workflows/ci.yml/badge.svg)](https://github.com/lavallee/spindle/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

📖 **Documentation site: <https://lavallee.github.io/spindle/>** — the lifecycle,
composition model, evaluation approach, and practical guide. Machine-readable
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

Spindle treats a skill as a behavioral dependency with a lifecycle, not as a
directory to copy and forget. Composition remains central: Spindle resolves a
tight subset per surface, checks it before anything lands, and realizes the
smallest suitable instructions independently for every parent or child model.
Around that, it adds temporary leases, exact ownership, startup reconciliation,
bounded evaluation, update-as-trial, and reversible custody.

The lifecycle is:

```text
inspect → try/borrow → compose → bootstrap → realize → activate → evaluate
                                                                  │
                                                 adopt, update, distill, retire
```

See the [rationale](https://lavallee.github.io/spindle/rationale.html) for the full
argument, including why that extra step pays for itself.

## Quick start: drive Spindle from your harness

```bash
uv sync --extra dev

# Preview and install the small project-local operator plus stable startup hooks.
spindle harness setup --harness codex --here --dry-run
spindle harness setup --harness codex --here

# Start a new session. In Codex, ask:  $spindle inspect a review skill for this task
# In Claude Code, ask:                /spindle inspect a review skill for this task
```

The operator skill is only the control surface: it asks
`spindle harness context --here --json` for current state and exact command
contracts instead of carrying a copy of the CLI manual in model context. Setup
snapshots its exact bytes, projects it to `.agents/skills/spindle` for Codex or
`.claude/skills/spindle` for Claude Code, and structurally merges stable startup
hooks. It preserves foreign harness state and does not adopt any other skill.
The operator projection is a machine-local generated symlink: do not commit it.
Review the generated project hook configuration separately; commit it when it is
shared team policy, or ignore it when the setup is intentionally local-only.

Use `spindle harness status --harness codex --here` to distinguish a current
operator, configured hooks, and a hook that a trusted harness session actually
ran. `configured-unverified`, `blocked`, and `restart-required` are not reported
as observed success. A nested Claude session launched from Codex (or the reverse)
is routed from the nearest harness process rather than inherited environment
markers alone.

## From the CLI: try before adopting

```bash
# Understand a local or pinned candidate without executing it.
spindle inspect ./candidate/review \
  --for "review this migration" --harness codex --here --json

# Preview, then run one disposable read-only session over the current blend.
spindle try ./candidate/review --harness codex \
  --task-file task.md --here --dry-run
spindle try ./candidate/review --harness codex \
  --task-file task.md --here

# Borrow the exact snapshot for two hours without adopting it.
spindle borrow ./candidate/review --harness codex \
  --until 2h --here --dry-run

# Verify exact desired state before starting the harness.
spindle bootstrap --harness codex --here --check
```

`inspect` is read-only. `try` and `borrow` operate on content-addressed snapshots
and create leases, not adoptions. Startup compares the surface lock with every
locally observable harness scope, repairs only receipt-owned drift, and preserves
foreign state. Promote a successful trial explicitly with `spindle adopt`.

If you author managed distributions, the composition workflow remains available:

```bash
spindle dist install examples/spindle-sample/distributions/spindle-sample
spindle dist activate spindle-sample
spindle bind /path/to/repo --harness claude
```

`bind` classifies the repository, resolves its channels into a coherent blend,
renders through harness/model profiles, checks guardrail preservation, and
records exact ownership for the harness-native projection.

## Documentation map

- [The skill lifecycle](docs/lifecycle.html) — the complete inspect-to-retire
  control loop.
- [Candidate inspection and leases](docs/local-lifecycle.md) — local and pinned
  sources, trust preflight, try, borrow, expiry, and quarantine.
- [Startup integrity](docs/startup-integrity.md) — desired versus effective
  state, stable native hooks, conflicts, repair, and restart semantics.
- [Runtime realization](docs/runtime-realization.md) — independent parent/child
  routing and activation/delegation receipts.
- [Behavioral evaluation](docs/skill-evaluations.md) — paired and named-arm
  experiments, runtime gates, minimalism, and distillation.
- [Adapter compatibility](docs/adapter-compatibility.md) — build-specific Claude
  and Codex certification.
- [Organization policy](docs/organization-policy.md) and [state
  custody](docs/migration-and-recovery.md) — authority constraints, migration,
  export/import, recovery, and GC.

## Runtime realization

A repository binding is shared, but its agent sessions need not use the same model.
A runtime-aware skill keeps its invariant core in `SKILL.md`, declares evaluated
session mappings in `spindle-realization.toml`, and stores minimal residues under
`overlays/`. Spindle resolves one immutable realization from the model actually
served to that agent:

```bash
spindle realize review \
  --session-id review-agent-7 \
  --harness codex \
  --model gpt-5.6-sol \
  --effort high \
  --role reviewer \
  --strict
```

Parents and subagents resolve independently; no command mutates the installed
package or a workspace-global “current model” file. Unknown or mismatched runtime
coordinates receive the conservative invariant core and an explicit unresolved
receipt. See [Runtime skill realization](docs/runtime-realization.md) for the
manifest, routing, adapter, and receipt contracts. The broader
[skill lifecycle UX](docs/skill-lifecycle-ux.md) documents intent-centered
discovery, zero-install trials, temporary leases, effective inventory, adoption,
maintenance, and retirement.

## Effective inventory and custody

`bind` writes an exact surface lock plus immutable ownership receipts for the
links it creates. Package identity and the rendered skill identity are recorded
separately, so an editable source changing beneath the same version is visible as
drift. A same-target link without a receipt remains foreign state; Spindle will
not adopt, overwrite, or remove it by inference.

Inspect the complete locally observable Claude or Codex discovery view without
changing it:

```bash
spindle inventory --effective --here --harness codex
spindle why review --effective --here --harness codex
spindle diff --effective --here --harness codex --strict
```

`inventory` and `why` are read-only. `doctor --startup` is also read-only unless
`--reconcile-owned` is explicit; even then it can remove only a stale or broken
symlink whose current path and target match an immutable Spindle ownership
receipt. Use `--dry-run` to see that plan. Plugin and managed/built-in scopes that
cannot yet be observed from local files are reported as `opaque`, not assumed
clean.

```bash
spindle doctor --startup --here --harness codex --reconcile-owned --dry-run
spindle package snapshot sample-planning --dry-run
```

Exact package snapshots live under `$SPINDLE_HOME/cache/packages`; surface locks,
ownership receipts, and their current-path indexes live under
`$SPINDLE_HOME/surface-locks`, `$SPINDLE_HOME/ownership-receipts`, and
`$SPINDLE_HOME/ownership`.

## Startup bootstrap and native hooks

Use the portable pre-discovery boundary to verify or ownership-safely repair the
exact locked blend before launching a harness:

```bash
spindle bootstrap --harness claude --here --check
spindle bootstrap --harness codex --here --reconcile-owned
spindle launch claude --here -- --model sonnet
```

Stable native hook kits then attest session start, resume/compaction, and
subagent start without embedding mutable package pins:

```bash
spindle hooks plan --harness claude --scope repo --here
spindle hooks install --harness claude --scope repo --here --dry-run
spindle hooks install --harness claude --scope repo --here
spindle hooks status --harness claude --scope repo --here --effective
spindle hooks remove --harness claude --scope repo --here --dry-run
```

An identical hook without a Spindle ownership receipt remains foreign. Hook
installation and removal structurally preserve unrelated configuration. A hook
heartbeat distinguishes “definition present” from “trusted and actually ran,”
and post-discovery drift reports `restart-required`.

Same-name foreign skills remain untouched and block until their collision is
removed or an exact, content-bound decision is explicit:

```bash
spindle conflict allow review --path /absolute/foreign/review \
  --reason "Intentional user-scoped alternate" --harness claude --here --dry-run
spindle conflict list --harness claude --here
```

See [Startup integrity and native hooks](docs/startup-integrity.md) for decision
semantics, trust gates, fast cache-only callbacks, receipts, and safe removal.

## Inspect, try, and borrow without adoption

Inspecting a candidate is read-only: no candidate code runs, no cache or lock is
written for local input, and package facts remain separate from contextual fit
hints. Remote inspection may populate only the verified source/provenance cache;
it never activates the candidate.

```bash
spindle inspect ./candidate/review \
  --for "review this migration" --harness codex --here --json

spindle inspect \
  'skills.sh:owner/repository@main#review' \
  --harness codex --here --json
```

Borrow an exact snapshot for a bounded time without creating adoption state, or
run one disposable read-only harness session and clean it up automatically:

```bash
spindle borrow ./candidate/review \
  --harness codex --here --until 2h --dry-run
spindle release sha256:... --harness codex --here --dry-run

spindle try ./candidate/review \
  --harness claude --model sonnet --task-file task.md --here --dry-run

spindle try \
  'github:owner/repository@0123456789abcdef0123456789abcdef01234567#review' \
  --offline --harness codex --model gpt-5.6-sol \
  --task-file task.md --here --dry-run
```

Leases overlay the current binding in the surface lock, point only at immutable
cached bytes, and name the exact owned projection they authorize. Startup
receipts report active and expired leases separately. Pre-launch reconciliation
cleans an expired lease; a resume/compact hook reports `restart-required`
instead of changing an already-discovered session. See
[Candidate inspection, pinned sources, trials, and expiring
leases](docs/local-lifecycle.md). Static preflight requires explicit flags for
executable, network, credential, and declared-tool authority. `spindle source
quarantine|unquarantine|status` controls future lease eligibility while
preserving historical receipts.

## Adopt, update, and retire deliberately

A zero-exit disposable trial can be promoted into durable repository ownership.
The preview names the exact package and skill digests, source pin, owner, update
channel, authority ceiling, prior adoption, surface-lock delta, and the run and
activation receipts that justify the transition:

```bash
spindle adopt sha256:<lease-id> --scope repo --here --dry-run --json
spindle adopt sha256:<lease-id> --scope repo --here
spindle health --harness codex --here
```

Pinned commits default to a manual update channel; a trial of a mutable Git ref
retains that ref as its refresh channel. Refreshes never replace the incumbent
directly. `update plan` resolves and preflights candidate bytes without changing
desired state, while `update try` exposes them under a temporary side-by-side
name and cleans them up after the run. Promote that successful update lease with
the same `adopt` command:

```bash
spindle update plan --harness codex --here --json
spindle update try review --harness codex --task-file task.md --here
spindle adopt sha256:<update-lease-id> --here
spindle rollback review --harness codex --reason "regression" --here
```

Evaluation claims belong to exact bytes and are deliberately not inherited by
an update. `health` reports unassessed contribution plus runtime, source,
package, cache, and inventory drift. `disable`, `enable`, `deprecate`, and
`retire` retain adoption and decision history; retirement removes only the
projection named by Spindle's ownership records. `vendor` and `distill` expose
read-only custody-path plans when continued upstream adoption is the wrong fit.

## Adapter certification and policy

Harness support is certified per build. The default capability matrix is
fail-closed for runtime facts until a digest-verified observation proves the
actual served models, tool/policy envelopes, and independent parent/child
activations:

```bash
spindle adapter matrix --harness codex --build 0.146.0 \
  --require model-identity
spindle adapter certify observation.json --dry-run --json
spindle adapter verify certification.json
```

The checked-in M7 evidence certifies Claude Code `2.1.220` with an Opus 5 parent
and Sonnet 5 child, and Codex CLI `0.146.0` with a GPT-5.6 Sol parent and Terra
child. These are exact adapter-contract coordinates, not evergreen harness or
model-quality claims. See [Adapter compatibility and
certification](docs/adapter-compatibility.md).

Organizations can constrain source providers, authority ceilings, required hook
scopes and attestations, exact adapter builds, and certification requirements in
`.spindle/policy.toml`:

```bash
spindle policy show --here --json
spindle policy check --here --harness codex --harness-build 0.146.0 --json
```

Policy is inspected without mutation and is enforced again at lease/adoption
boundaries. See [Organization lifecycle policy](docs/organization-policy.md).

## Migration and recovery

Legacy installs are audited and preserved, never silently converted into
adoptions. Immutable receipts can rebuild mutable indexes, and deterministic
state bundles merge only absent or byte-identical files:

```bash
spindle migrate plan --harness codex --here --json
spindle state export spindle-state.tar.gz --dry-run --json
spindle state import spindle-state.tar.gz --destination /new/state --dry-run
spindle state recover --json
spindle state gc --json
```

GC is a separate, exact-plan operation over unreferenced verified cache bytes;
it does not erase adoption or evaluation history. See [Migration, recovery, and
state custody](docs/migration-and-recovery.md).

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
| cache | Immutable package bytes available locally; no runtime or maintenance authority. |
| install | Durable compatibility path that installs a distribution and links its global skills; unlike a lease or adoption. |
| channel | A versioned `(scope × harness)` manifest listing the skills a surface should receive. |
| surface | A repo or agent that consumes a skill blend. |
| profile | A harness/model renderer such as `identity`, `terse`, or `trim`. |
| bind | Materialize one resolved surface blend and record exact ownership. |
| realization | An immutable invariant core plus at most one session-matched skill overlay. |
| activation | Evidence that one exact agent loaded a realization under the observed model, tools, and policy. |
| intent card | Read-only package facts plus separately labeled current-environment fit analysis. |
| lease | Content-addressed, expiring runtime authority that does not create adoption state. |
| evaluation | A bounded behavioral claim for exact artifact and runtime coordinates. |
| adoption | Durable maintenance custody promoted from a successful exact lease/trial. |
| retirement | Historical adoption retained while only its exactly owned runtime projection is removed. |
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
