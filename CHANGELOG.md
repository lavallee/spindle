# Changelog

All notable changes to Spindle will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] - 2026-10-12

- Added the house: one versioned directory holding the rules every harness
  loads, a small kernel of always-installed skills, and named project patterns.
  `spindle house init|setup|status|rules|patterns` installs it per machine for
  Claude Code, Codex, and Hermes, and `spindle house setup --here --pattern`
  vendors a pattern's rules and skills into a repository.
- Added the catalog: `spindle catalog sync|list|update` indexes skills from
  commit-pinned Git sources and local directories without installing or running
  anything, and reports what a newer upstream commit would change before the
  pin moves.
- Added on-demand sourcing: `spindle find` ranks catalog skills for a task,
  `spindle use` hands one over as a path or text, `spindle report` records the
  outcome, and `spindle usage` shows per-skill results, which feed back into
  ranking. `spindle brief` gives a job runner the prompt section and the record
  for a commission in one call. An optional Jev judge turns the lexical
  shortlist into a selection. See `docs/house-and-sourcing.md`.

- Added an optional search expander for `spindle find` and `spindle brief`: a
  house-named command (`[sourcing] expand`) rewrites the task into short search
  phrases, and the per-phrase rankings are fused by reciprocal rank.

- Added `spindle house update`: fast-forward the house checkout, reinstall for
  the harnesses already set up, and rebuild the catalog index.
- `spindle brief --inline` embeds at most two skills and only those the judge
  scored 0.7 or higher.

## [0.3.0] - 2026-10-12

- Added conjunctive outcome gates for paired evaluations: an optional
  `[acceptance].required_variant_gates` list requires every held-out variant
  result to report each named gate as `{passed, evidence}`, and one missing,
  malformed, or false gate blocks promotion regardless of mean score. The CLI
  and receipt report the exact failed case/gate coordinates.
- Evaluation manifests now reject unknown top-level and `[acceptance]` keys
  instead of ignoring them.
- Added the `examples/outcome-uat` skill and frozen-receipt calibration: 16
  held-out cases across nine deterministic gates, including missing-data,
  wrong-grain, hidden-mobile-field, and evidence-state controls.
- Added job-scoped leases for external dispatchers: `spindle job
  grant|release|status --for-job <id>` leases an explicit skill set to one
  dispatched job over the standing surface binding, records the job id on each
  lease receipt (optional `job_id` on `spindle.lease/v1`; absent-field identity
  preserved for existing receipts), releases idempotently by job id, and leans
  on TTL plus startup reconciliation when a job dies without releasing. See
  `docs/job-scoped-leases.md` for the dispatcher bridge contract.
- Added `spindle harness setup|status|context|remove` and a minimal bundled
  operator skill for driving the lifecycle as `$spindle` in Codex or `/spindle`
  in Claude Code, with exact ownership, stable hooks, nested-harness routing,
  dry-run removal, and separate operator/configuration/heartbeat state.
- Binding and unbinding now preserve all non-binding lifecycle projections,
  including operator, lease, and adoption custody.

## [0.2.0] - 2026-07-31

- Added ownership-safe effective inventory, startup bootstrap, stable native
  Claude/Codex hooks, exact conflict decisions, and startup receipts.
- Added read-only intent inspection, pinned-source preflight, disposable trials,
  expiring borrow leases, and explicit lease-to-adoption promotion.
- Added update-as-trial, health, rollback, disable/deprecate/retire, tuple-bound
  minimalism evaluation, and bounded distillation staging.
- Added build-specific adapter conformance and certification, organization
  policy, deterministic state export/import, cache GC, migration audit, and
  immutable-receipt crash recovery.
- Reworked the README and documentation site around the implemented lifecycle,
  including a lifecycle overview, current operational guide, named-arm
  evaluation, and machine-readable documentation.

- Procedure evaluations can preserve exact Milton/Chip origin and explicit
  baseline/variant implementation-profile-model-harness tuples.
- Eligible evaluations can enter `record_evaluated_binding`; idempotent
  `spindle.procedure-promotion/v1` receipts bind evaluation custody to the
  resulting surface coordinate.

### Added

- `spindle chippability <package-or-skill-dir>` — a static, LLM-free scorer that
  flags skills hiding a chip-shaped behaviour (a refusing gate over durable
  cross-run state). Prints a compact table (or `--json`), appends a per-skill
  record to `$SPINDLE_HOME/chippability.jsonl`, and with `--emit-candidates`
  writes chip candidates in the public `candidates.jsonl` convention. Spindle
  imports no chip tooling and requires no chip host — it names strings and emits
  files, degrading gracefully when no chip side exists.
- Advisory `chip:` alias on composed skills (channel `[chips]` map or SKILL.md
  `chip:` frontmatter), mirroring the `tier` routing hint. It travels through
  resolve/render/materialize untouched; `spindle bind` emits a non-fatal
  advisory when a chip-annotated skill shows no guardrail line.
- Optional `chippable` / `chip_alias` keys on verdicts, surfaced by
  `spindle verdict list|show` (open dict, no enum enforcement).
- `spindle eval validate|run|show` for deterministic paired behavioral skill
  evaluations, held-out promotion gates, and durable evidence receipts.
- Public evaluation contract documentation and an offline sample runner.
- Documentation site under `docs/` (an [artoo](https://github.com/lavallee/artoo)
  artifact): rationale, how-it-works, evaluation, and guide pages, plus an
  `llms.txt` index and a single-file `bundle.md` for agents. Served by GitHub
  Pages from `/docs`.

## [0.1.0] - 2026-07-05

### Added

- Public Spindle project identity and `spindle` package/CLI.
- Pluggable package and distribution metadata under `[tool.spindle.package]` and
  `[tool.spindle.distribution]`.
- Public `examples/spindle-sample` distribution with one sample planning package,
  four skills, profiles, channels, doctrine, roster, scout, and verdict fixtures.
- Local reference task and decision-gate sinks using `$SPINDLE_HOME` JSONL queues.
- Environment-controlled private-layer skill alias seam via
  `SPINDLE_LEGACY_ALIAS_FROM` and `SPINDLE_LEGACY_ALIAS_TO`.

### Changed

- Project state now defaults to `~/.spindle` and uses `SPINDLE_*` environment
  variables.
- The public CLI and docs describe generic task, gate, scout, and distribution
  workflows rather than any private installation.

### Removed

- Private distribution content and private tooling assumptions from the public
  base repository.
