# Changelog

All notable changes to Spindle will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
