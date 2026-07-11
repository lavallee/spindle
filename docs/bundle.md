# Spindle — complete documentation bundle

> Single-file bundle intended for paste-in LLM context. It concatenates the whole
> Spindle documentation site into one Markdown document. Source of truth:
> https://github.com/lavallee/spindle · License: MIT · Describes Spindle v0.1.

Spindle composes source skills into tight, surface-specific blends. It is a small,
dependency-light Python toolchain for one loop: install skill **packages**, group
them into **distributions**, resolve the right subset for a repo or agent
**surface**, render that subset for a harness/model **profile**, lint it for
coherence, and materialize the result where the agent runtime loads it — then prove
a skill actually improves behavior (not merely that it loaded) with paired,
held-out behavioral evaluations.

---

## 1. Overview

Agent "skills" — the reusable instruction files a coding agent loads to do a job
well — multiply fast. Left unmanaged, every repository inherits the same growing
pile: skills it will never use, skills that quietly contradict each other, and a
context budget spent on instructions instead of work. Spindle treats a surface's
skill set as something you **compose** and **verify**, not something you accumulate.

The everyday workflow is one command:

```bash
# install the toolchain and a reference distribution of skills
uv sync --extra dev
spindle dist install examples/spindle-sample/distributions/spindle-sample
spindle dist activate spindle-sample

# see what you've got
spindle doctrine show
spindle skill list

# compose + render + materialize the right blend for a repo
spindle bind /path/to/repo --harness claude
# → resolved 4 skills · lint ok · rendered (identity) · linked → .claude/skills/
```

That last command is the whole idea in miniature: **classify** the repo, **select**
the channels it subscribes to, **resolve** them into one blend, **render** through
the harness/model profiles, **lint** for coherence, and **materialize** the
selected skills where the runtime can load them — failing closed if the blend isn't
coherent.

Packages and distributions are ordinary pip-installable projects that declare
themselves with `[tool.spindle.package]` and `[tool.spindle.distribution]`
metadata, so the whole ecosystem grows through packaging you already understand.
The public base ships a minimal reference distribution under
`examples/spindle-sample`. Everything private — an organization's own packages,
project registries, task sinks, marketplace providers — lives in separate adapter
packages that depend on Spindle, never inside its core.

---

## 2. Rationale — why compose skills at all?

Agent skills are one of the best ideas to arrive in coding agents: a small file of
hard-won instructions that makes the agent reliably good at a task. The trouble
starts not with any one skill but with the twentieth. The instinct is to install
every useful skill globally so it's always available. It's the right instinct and
the wrong result: a global pile is never vetted as a **set**. It was assembled one
convenient addition at a time, by different authors, for different situations. That
carries five hidden costs.

### Cost 1 — context budget

Every skill an agent loads is instruction it reads before it does any work. A pile
of forty skills is forty skills' worth of preamble competing with the task for
attention and tokens — most of it irrelevant to the repo in front of it. A React
app doesn't need the database-migration skill; a data pipeline doesn't need the
accessibility-audit skill. Spindle's materializer installs the *resolved subset*
for a surface — not every skill of a distribution. Fewer, sharper skills beat more,
vaguer ones.

### Cost 2 — incoherent blends (the "pidgin")

Skills authored independently combine in ways no author ever tested. Two skills
both bind the `/review` command. One assumes the output format another produces. A
planning skill says "always write tasks to the tracker" while a lightweight skill
says "never leave the working directory." When you pour many upstreams into one
agent, you get a **pidgin**: a combination that no single upstream ever vetted as a
whole. Spindle resolves a blend as a first-class object and *lints it* before
anything is written — catching command collisions and duplicate skills, recording
every override as a shadow, and refusing to materialize an incoherent set unless
forced. The check runs where it has the whole picture: the surface where the skills
will actually run together.

### Cost 3 — one-size-fits-all skills

There's a tempting way to make a skill "just work everywhere": keep adding caveats
and special cases until it covers every situation. The result is long, generic, and
slightly worse for every specific surface — it spends its words hedging instead of
helping, and never fully succeeds because the situations genuinely conflict.

Spindle takes the opposite position, and it is the load-bearing idea: **coherence
belongs at the composition layer — not inside ever-larger skills.** Keep each skill
small and canonical: write it once, for the case it's actually good at. Let
*composition* — which skills travel together, in what order, phrased for which
surface — carry the burden of making them work as a set.

### Cost 4 — the wrong surface

"The right skills" is surface-relative in three independent ways, and a flat global
pile can express none of them:

- **App type** — a Python network service and a React frontend want different
  skills. Spindle classifies the repo and resolves per-cluster channels.
- **Harness** — a Claude harness and a Codex harness phrase and locate skills
  differently. The harness is both a selection key and a rendering dialect.
- **Model** — a frontier model reads faster without restated context and worked
  examples a smaller model relies on. Rendering trims scaffolding by model tier.

Same source skill, three surfaces, three different materialized results — computed,
not hand-maintained.

### Cost 5 — guardrails you can't accidentally drop

The moment an agent can recompose its own skills, it can — in principle — compose
away its own safety rules. Spindle makes that structurally impossible in two places.
Absolutes (the `ALWAYS`/`NEVER` rules a channel puts in force) are *unioned* across
every layer and are never dropped by precedence: guardrails only accumulate. And at
render time, every guardrail clause present in a skill's source must survive, word
for word, in the rendered output — if a paraphrase or an LLM rewrite drops one, the
bind fails closed and materializes nothing.

### "But it adds a step"

It does — one command, `spindle bind`, between installing skills and using them.
Three reasons it earns its place:

1. **It's cheap and amortized.** A bind is deterministic and cached; re-binding an
   unchanged surface is nearly free. The **advance team** (`spindle advance run`)
   precomputes the blend for every known surface ahead of time, so a repo is
   already composed before anyone opens it — the step disappears into a warm cache.
2. **It's where the value is created.** It's the one moment with enough context to
   make the pile coherent, sized, phrased, and safe. Skip it and you haven't saved
   work — you've pushed that work onto the agent at runtime, where it's slower, less
   reliable, and unverifiable. When a surface needs something ad-hoc, the
   **liaison** logs the request as a demand signal, so today's one-off becomes
   tomorrow's precomputed skill.
3. **It separates availability from improvement.** Binding proves a skill is present
   and coherent, but never that it's good. Spindle answers the second question with
   real evidence (§4).

---

## 3. How it works — data model and the bind pipeline

Spindle is an assembly line. Authored skills become packages; packages ship in
distributions; channels select them per surface; resolution merges them into a
blend; profiles render it; a lint gates it; materialization writes it where the
agent loads it.

### 3.1 The vocabulary

Seven nouns carry the whole system, stacking from what an author writes to what an
agent loads: **skill → package → distribution → channel → blend → profile →
surface**, all governed by **doctrine**.

| Term | What it is | Declared / defined |
|---|---|---|
| **skill** | A directory with a `SKILL.md` (YAML frontmatter `name`/`description` + Markdown body). The canonical, authored-once unit, kept small on purpose. | On disk under a package, e.g. `<pkg>/<module>/skills/<name>/SKILL.md` |
| **package** | A pip-installable project that ships skills and advertises capabilities. | `[tool.spindle.package]` in the package's `pyproject.toml` |
| **distribution** | A pip-installable bundle that groups packages (as ordinary dependencies) and carries surface-wide assets — doctrine, channels, profiles. | `[tool.spindle.distribution]` in the dist `pyproject.toml`; `source_dir` roots everything else |
| **channel** | A versioned `(scope × harness)` manifest listing which skills a surface should receive at that scope, plus absolutes in force and optional tiers. | `channels/<scope>/<name>/<harness>/channel.toml` |
| **surface** | A repo or agent that consumes a blend. Carries name, harness, autonomy mode, app-class clusters, and target model. | in-memory `Surface` built by the binder |
| **profile** | A data-driven, versioned renderer. A *harness* profile sets dialect; a *model* profile sets density. | `profiles/<harness>/profile.toml`, `profiles/models/<key>/profile.toml` |
| **blend / composition** | The resolved skill subset for one surface + absolutes in force + recorded overrides (shadows). | produced by `composition.resolve` |
| **doctrine** | The versioned first-principles set (preferences, absolutes, meta-principles) skills are checked against. | `doctrine/doctrine.toml` |
| **scope** | Specificity of a channel/doctrine entry: `system` \| `cluster` \| `repo`. Drives selection order and precedence. | — |
| **harness** | The agent runtime dialect + install location: `claude` \| `codex` \| `pi` \| …. Both a selection key and a rendering axis. | — |
| **capability** | A free-form tag a package advertises (e.g. `technical-design`). | `[tool.spindle.package].capabilities` |

A **scope** (`system`, `cluster`, `repo`) drives both the order channels are
selected (broad → narrow) and which layer wins when two define the same skill
(narrow wins). Guardrails are the exception — they accumulate across all scopes.

### 3.2 The `bind` pipeline

`spindle bind <repo> --harness claude` runs six stages. It is **fail-closed**: if
rendering drops a guardrail or the lint finds a problem, nothing is materialized
(unless you pass `--force`).

**01 · Classify** (`appclass.py`) — read the checkout's `pyproject.toml` /
`package.json` into a `RepoSignal` (language, dependencies, notable files) and
classify it into an app-class with a single stable **cluster key** like
`lang:python|network-service|uses-llms`. A repo that changes shape gets re-clustered
on the next bind.

**02 · Select** (`channels.py`) — the surface subscribes to an ordered list of
channels, least- to most-specific: `(system, system)`, then one `(cluster, <key>)`
per cluster, then `(repo, <name>)`. Each resolves to a file under the active
distribution's `source_dir`:

```
channels/<scope>/<name>/<harness>/channel.toml
```

The harness is applied here — a Claude surface only reads `claude/` manifests.
Missing manifests are skipped. A channel manifest:

```toml
# channels/system/system/claude/channel.toml
version = "0.1.0"
absolutes = ["A1", "A2"]        # doctrine ids in force at this scope
skills = ["clarify", "design", "tasks", "review"]

[tiers]                         # optional routing hints (advisory)
clarify = "judgment"
design  = "judgment"
tasks   = "judgment"
review  = "judgment"
```

Skill names resolve through an index built from installed packages; a name with no
installed package is dropped (the cause of a `resolved 0 skills` warning). A
channel's `version` feeds the binding coordinate.

**03 · Resolve** (`composition.py`) — merge the selected layers into one
`Composition`. Each skill occupies a **slot** keyed by its command (falling back to
its name); a more-specific layer overrides a less-specific one for the same slot,
and every override is recorded as a **shadow** rather than silently dropped.
Absolutes are *unioned* across all layers and never lost to precedence — the
guardrail floor only rises. Default precedence: `system → cluster → repo`.

**04 · Render** (`render.py`) — rewrite each skill for the harness dialect, then the
model density (§3.3), and verify guardrails survived. Because rendering produces new
text, its output is written to a content-addressed store and the blend is repointed
at it (it can't be a symlink like selection).

**05 · Lint** (`composition.py`) — pure coherence checks over the blend's metadata:
no two skills may claim the same command, no skill may appear twice, and a genuinely
irreversible skill must carry the matching absolute. Problems stop the bind unless
forced. The linter inspects *structure*, not prose — which is why the guardrail
check lives in rendering.

**06 · Materialize** (`materialize.py`) — symlink each resolved skill into the
harness's native location and report a per-skill action
(`linked · updated · kept · removed · skipped`). Spindle reads the surface's
previous binding to know which links it owns and removes only those; a hand-added
file is never touched. Install locations: `claude → .claude/skills`,
`codex → .codex/skills`, `pi → .pi/skills` (fallback `.<harness>/skills`).

**Record** — the binding is recorded with a stable coordinate over the skills, the
doctrine, and the channel versions, appended to a per-surface history so any prior
coordinate is a rollback target. `spindle unbind` reverses it, removing exactly the
links Spindle owns.

### 3.3 Rendering & profiles

Selection decides *which* skills; rendering decides *what text* each becomes for
this surface. Two profile axes compose, dialect then density:

- **Harness profile (dialect)** — `profiles/<harness>/profile.toml`.
  - `identity` — verbatim (Claude is the reference dialect).
  - `terse` — deterministic whitespace collapse; content-preserving by
    construction, so guardrails always survive.
  - `llm` — an actual model rewrite into the harness dialect; **skipped** if no LLM
    client is configured (offline binds never fail on this).
- **Model profile (density)** — `profiles/models/<key>/profile.toml`, keyed by the
  surface's model.
  - `identity` — keep all scaffolding (what weaker models want).
  - `trim` — subtractively strip author-marked scaffold fences, then `terse`.
  - `llm` — model-driven densification.

```toml
# profiles/claude/profile.toml — harness dialect
version = "1"
transform = "identity"

# profiles/models/frontier/profile.toml — model density
version = "1"
transform = "trim"
tier = "frontier"
```

The `trim` transform is the "optimize things *out*" half of tuning. An author marks
a passage that only smaller models need; a frontier profile removes it — the same
canonical skill, rendered denser:

```
<!-- scaffold:examples -->
Worked example a smaller model benefits from…
<!-- /scaffold -->
```

Bumping a profile's `version` invalidates the render cache.

### 3.4 Doctrine

Doctrine is the coherent first-principles frame, kept as a versioned, hand-editable,
machine-readable TOML artifact. Three entry kinds:

- **preferences** — "favor X over Y," scoped, with a note and provenance.
- **absolutes** — `ALWAYS`/`NEVER` hard rules, scoped and rare; densest at system
  scope.
- **meta-principles** — rules about how the other principles are written.

```toml
# doctrine/doctrine.toml (excerpt)
version = "0.1.0"

[[preference]]
id = "P1"
scope = "system"
favor = "clear acceptance evidence"
over  = "performative process"

[[absolute]]
id = "A2"
scope = "system"
mode = "NEVER"
statement = "fabricate missing facts"
```

Doctrine makes "coherence" a defined, versioned, testable property. Its
**coordinate** — `<version>+<hash>` — is pinned into every render cache key and every
binding record, so a rollback can re-fetch the exact doctrine that produced a blend.
`spindle doctrine validate` refuses a malformed doctrine before it can render into
skills. The absolute *ids* (A1, A2, …) are the shared language between channels
(`absolutes = […]`) and doctrine.

### 3.5 The safety floor

Two mechanisms make it structurally hard to compose away safety:

1. **Absolutes accumulate** — because resolve unions them across every layer, a
   narrow channel can add a guardrail but never remove one.
2. **Rendering verifies preservation** — every guardrail clause in a skill's source
   (lines matching `ALWAYS`, `NEVER`, `MUST NOT`, or `DO NOT`) must survive,
   normalized, in the rendered output, or the bind fails closed
   (`render.verify_preserved`). The coherence linter reads metadata and can't catch
   a paraphrase that drops a clause, so this deterministic check is the backstop —
   and it holds even when an `llm` profile ignores its instructions.

### 3.6 Determinism & caching

Everything is content-addressed, which is what makes the "extra step" cheap to
repeat. A rendered skill is cached under
`sha256(doctrine × harness-profile version × model-profile version × skill content)`;
change any input and the cache invalidates, change nothing and the render is reused.
A binding's coordinate is `sha256(skills + doctrine + channel versions)`. Re-binding
an unchanged surface is nearly free, and every past coordinate is a precise rollback
target. This is why `spindle advance run` can precompute every surface ahead of
time.

---

## 4. Evaluation — availability is not improvement

A bind proves a skill loaded without losing guardrails or budget. It says nothing
about whether the skill made the agent *better*. Spindle draws a hard line and
refuses to let a bind stand in for an effectiveness claim.

| `spindle bind` — availability | `spindle eval` — improvement |
|---|---|
| Can this surface load the skill? | Does the skill improve behavior? |
| Without losing guardrails or budget? | On this task family, model, and harness? |
| Coherent with the rest of the blend? | Versus running without it? |
| Deterministic. **No model calls.** | Measured on **held-out** cases. |

> Rendering and binding prove a skill is available, not that it improves an agent.

### 4.1 The paired experiment

Every selected case runs *twice*: once as the **baseline** (skill off) and once as
the **variant** (skill on). Comparing the same case with and without the skill is
the only way to attribute a difference to the skill rather than the case. Case order
and within-pair arm order are both shuffled from the manifest's `seed` — randomized
to avoid ordering bias, yet reproducible.

```toml
# eval.toml (excerpt)
schema_version = 1
id = "diagnosing-bugs-v1"
skill = "diagnosing-bugs"
skill_path = "candidate/SKILL.md"
runner = ["python", "runner.py"]     # an argv contract, not a model client
seed = 20260711
min_held_out_cases = 10
min_improvement = 0.05

[dimensions]
harness = "isolated-executor"
model = "frozen-model-coordinate"

[[cases]]
id = "unseen-regression"
split = "held_out"
fixture = "fixtures/unseen-regression.json"
```

### 4.2 The held-out promotion gate

**Development** cases exist so you can iterate on fixtures and graders; they never
make a run promotion-eligible. Promotion is decided only on **held-out** cases. A run
may promote only if all four hold:

1. the configured minimum number of held-out cases is met;
2. zero runner errors;
3. complete baseline/variant pairs;
4. variant mean strictly above baseline (when `min_improvement = 0`), else at least
   the configured margin.

The held-out mean is a necessary gate, not the whole decision — review case-level
regressions, cost, latency, and human-correction time before adopting. Rejected and
null receipts are kept as evidence for that exact skill hash.

### 4.3 The runner is an argv contract

Spindle never calls a model provider. A manifest names an argv `runner`, and Spindle
invokes it once per case per arm — with no shell — passing everything through
environment variables. The runner may wrap an isolated executor, a benchmark
harness, or a deterministic local fixture; it writes one JSON result and exits.

| Variable | Meaning |
|---|---|
| `SPINDLE_EVAL_ARM` | `baseline` or `variant` |
| `SPINDLE_EVAL_SKILL_ENABLED` | `0` or `1` — must match the arm |
| `SPINDLE_EVAL_SKILL_FILE` | candidate skill path (variant); empty for baseline |
| `SPINDLE_EVAL_FIXTURE` | absolute path to the case fixture |
| `SPINDLE_EVAL_SPLIT` | `development` or `held_out` |
| `SPINDLE_EVAL_DIMENSIONS` | JSON of the frozen `[dimensions]` |
| `SPINDLE_EVAL_RESULT_PATH` | where the runner must write its JSON result |
| `SPINDLE_EVAL_ID` / `_RUN_ID` / `_CASE_ID` | evaluation, run, and case coordinates |

The result is small and validated: `score` bounded to `[0,1]`; `skill_invoked` must
match the arm; `evidence` must be non-empty. A timeout, nonzero exit, malformed
result, missing evidence, or arm mismatch is an evaluation error — and an error
blocks promotion.

```json
// the JSON the runner writes to $SPINDLE_EVAL_RESULT_PATH
{
  "score": 0.82,
  "passed": true,
  "skill_invoked": true,
  "evidence": {"grader": "exact-regression-check", "receipt": "…"},
  "metrics": {"false_positives": 0, "corrections": 1},
  "artifacts": [".../agent-output.txt"]
}
```

### 4.4 Receipts

Each run writes a receipt keeping input hashes, pair order, exit state, duration,
stdout/stderr *hashes*, scores, metrics, and the promotion decision — but not full
transcripts. Enough to audit and reproduce a decision for a specific skill hash
without hoarding potentially sensitive agent output.

```bash
spindle eval validate examples/evaluation-sample/eval.toml
spindle eval run      examples/evaluation-sample/eval.toml
spindle eval show     examples/evaluation-sample/receipts/<receipt>.json
```

### 4.5 Initial task families

- **Diagnosis** — exact symptom reproduction, loop determinism, pre-edit hypothesis
  testing, regression sensitivity, completion, time, cost.
- **Code review** — true findings, severity, false positives, spec-vs-standards
  attribution, missed seeded issues, correction time, with clean controls.
- **Handoff** — repeated exploration, missing decisions, invalid assumptions, time
  to first correct action, completion in a fresh context.

Spindle's skill optimizer (`spindle optimize`) consumes these same held-out scores,
so optimizing a skill's *prose* and evaluating its *behavior* run through one gate —
and a proposed edit that drops a guardrail is rejected outright.

---

## 5. Guide — install, bind, build, extend

### 5.1 Install & activate

```bash
uv sync --extra dev
spindle dist install examples/spindle-sample/distributions/spindle-sample
spindle dist activate spindle-sample

spindle dist list
spindle doctrine show
spindle skill list
spindle capability list
```

Installing a distribution links its skills into your global skills directory and
records the event. Activation writes the active distribution name into
`$SPINDLE_HOME` (default `~/.spindle`); with a single distribution installed,
Spindle uses it even before activation.

### 5.2 Bind a repo — the daily step

```bash
spindle bind /path/to/repo --harness claude
spindle bind /path/to/repo --harness claude --model frontier
spindle bind /path/to/repo --harness claude --dry-run
spindle appclass /path/to/repo         # see the classification without binding
spindle unbind /path/to/repo --harness claude
```

Materialized skills land in the harness's native directory (`.claude/skills/` for
Claude). Useful flags: `--dry-run` (compute, don't write), `--no-render` (select
only, skip profiles), `--force` (materialize despite lint problems — the escape
hatch past the fail-closed gate; use sparingly).

### 5.3 Work ahead: advance & liaison

```bash
spindle advance run --from-registry     # precompute blends for every known surface
spindle liaison request /path/to/repo --intent "audit accessibility" --bind
spindle liaison log repo                # a surface's demand stream
```

Because a bind is deterministic and cached, precomputing turns the per-repo step
into a single batch job. The liaison records what a surface asked for, so a
recurring one-off can graduate into a precomputed skill.

### 5.4 Build your own

```bash
spindle package new my-tools --dest ./packages/my-tools \
  --skill clarify --skill review --capabilities planning

spindle dist new my-dist --dest ./distributions/my-dist \
  --source-dir ../../ --package my-tools==0.1.0
```

**Author a skill** — a directory with a `SKILL.md`: frontmatter + a short, canonical
body. Keep it small; put guardrails as `ALWAYS`/`NEVER` lines so rendering protects
them.

```markdown
---
name: design
description: Convert a clarified request into an implementation design.
---

# design

Use after the request has a clear outcome and acceptance criteria.

1. Read the relevant code and existing conventions first.
2. Propose the smallest coherent change that satisfies the outcome.
3. Name the affected files, data contracts, and tests.

ALWAYS prefer existing local patterns over new abstractions.
```

**Declare the package**:

```toml
# packages/my-tools/pyproject.toml
[tool.spindle.package]
name = "my-tools"
version = "0.1.0"
distribution = "my-dist"
skills = ["clarify", "design", "review"]
capabilities = ["technical-design", "plan-review"]

[[tool.spindle.package.sources]]        # provenance, optional
peer = "upstream-lib"
url  = "https://github.com/org/upstream-lib"
transposed_at = "2026-07-11"
```

**Write a channel** — under the distribution's `source_dir` at
`channels/<scope>/<name>/<harness>/channel.toml`. The system channel is the broad
default; add cluster channels for app-types and a repo channel to override a single
surface (narrow wins; absolutes from every layer stay in force).

```toml
# channels/system/system/claude/channel.toml
version = "0.1.0"
absolutes = ["A1", "A2"]
skills = ["clarify", "design", "review"]

[tiers]
review = "judgment"
```

**Tune per surface with profiles** — add a harness profile (dialect) and a model
profile (density) to change how skills render without touching their source.

```toml
# profiles/codex/profile.toml
version = "1"
transform = "terse"

# profiles/models/frontier/profile.toml
version = "1"
transform = "trim"
tier = "frontier"
```

### 5.5 Evaluate a skill

```bash
spindle eval validate examples/evaluation-sample/eval.toml
spindle eval run      examples/evaluation-sample/eval.toml
spindle eval show     examples/evaluation-sample/receipts/<receipt>.json
```

See §4 for the full contract. To improve a skill's prose against the same gate, use
`spindle optimize`.

### 5.6 Extending Spindle (open core)

The compose-render-materialize-evaluate machinery and the contracts are public; the
infrastructure behind them is meant to be your own. The core ships local reference
sinks (JSONL files under `$SPINDLE_HOME`) and swaps them out through environment
variables and injectable callables. Private adapters depend on Spindle — never the
reverse.

| Seam | Env var | Default |
|---|---|---|
| State root | `SPINDLE_HOME` | `~/.spindle` |
| Active distribution | `SPINDLE_ACTIVE_DIST_NAME` / `_DIR` | the activated dist |
| Task sink | `SPINDLE_TASK_QUEUE` / `SPINDLE_TASK_URL` | local JSONL queue |
| Gate sink | `SPINDLE_GATE_QUEUE` | local JSONL queue |
| Scout runner | `SPINDLE_SCOUT_COMMAND` | illustrative default |
| LLM render / propose | `ANTHROPIC_API_KEY` | absent → those steps skip, not fail |

Around the core sits an *optional* learning & marketplace layer — `scout`, `peers`,
`verdict`, `roster`, `broker`, `gate`, `ingest`, `fleet`. Treat it as a set of
extension seams: discovery passes, a judgment store, a marketplace facade,
decision-gate and task queues, and cross-machine ledger sync. **These modules are
intentionally skeletal — contracts and reference stubs, not finished
infrastructure.** Build the adapters your organization needs against them.

### 5.7 CLI reference

| Area | Commands |
|---|---|
| Distributions | `dist list · show · install · uninstall · activate · new` |
| Packages / skills | `package list · show · new` · `skill list · show` · `capability list · show` |
| Compose | `appclass` · `bind` · `unbind` · `advance run` · `liaison request · log` |
| Doctrine | `doctrine show · validate` |
| Evaluate / tune | `eval validate · run · show` · `optimize` · `rate` |
| Learn / market | `peers` · `verdict` · `roster` · `broker` · `acquisitions` · `scout` |
| Infra sinks | `ingest` · `gate file · from-result` · `fleet status · sync` |
| Housekeeping | `status` · `preempt · unpreempt` · `state show · rebuild` |

Run any command with `--help` for its flags.

---

## 6. Worked example — `examples/spindle-sample`

```
examples/spindle-sample/
  packages/sample-planning/          # [tool.spindle.package] sample-planning==0.1.0
    sample_planning/skills/{clarify,design,tasks,review}/SKILL.md
  distributions/spindle-sample/      # [tool.spindle.distribution] spindle-sample==0.1.0
    pyproject.toml (source_dir = "../../")
  channels/system/system/claude/channel.toml
  doctrine/doctrine.toml
  profiles/{claude,codex}/profile.toml, profiles/models/frontier/profile.toml
```

1. **Install** — `spindle dist install …/spindle-sample` installs the distribution
   and its `sample-planning` dependency, then links the four skills (`clarify`,
   `design`, `tasks`, `review`) into your global skills dir and logs the event.
2. **Activate** — `spindle dist activate spindle-sample` writes the active pointer;
   `active.source_dir()` now resolves to `examples/spindle-sample/`, the root every
   later read uses.
3. **Bind** — `spindle bind /path/to/repo --harness claude` classifies the repo,
   subscribes to `system/system` (the only channel present; cluster/repo are
   skipped), resolves the 4 skills with `absolutes = [A1, A2]`, renders them
   `identity` (verifying each skill's guardrail survives), lints clean, and
   symlinks `.claude/skills/{clarify,design,tasks,review}` — then records the
   binding coordinate. `spindle unbind` removes exactly those four links.

Net files that land: global skill symlinks + `$SPINDLE_HOME/events.jsonl` &
`state.json` (install); `$SPINDLE_HOME/active` (activate); rendered cache under
`$SPINDLE_HOME/rendered/<key>/`; and per-surface `<repo>/.claude/skills/*` +
`$SPINDLE_HOME/bindings/<surface>.json` (bind).

---

*Built as an [artoo](https://github.com/lavallee/artoo) artifact with the artoo-kit
design system, hand-authored from the Spindle source. Describes Spindle v0.1 — a
point-in-time snapshot of a young, evolving toolchain. MIT licensed.*
