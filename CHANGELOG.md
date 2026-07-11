# Changelog

All notable changes to Spindle will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `spindle eval validate|run|show` for deterministic paired behavioral skill
  evaluations, held-out promotion gates, and durable evidence receipts.
- Public evaluation contract documentation and an offline sample runner.

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
