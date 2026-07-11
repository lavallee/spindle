# Spindle

**Spindle** composes source skills into surface-specific blends.

[![CI](https://github.com/lavallee/spindle/actions/workflows/ci.yml/badge.svg)](https://github.com/lavallee/spindle/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

It is a small Python toolchain for installing skill packages, grouping them into
distributions, resolving the right subset for a repo or agent surface, rendering
that subset for a harness/model profile, and materializing the result where the
agent runtime can load it.

The public base ships with a minimal reference distribution under
`examples/spindle-sample`. Private organizations can publish their own packages,
distributions, project registries, task sinks, gate sinks, scout runners, and
marketplace providers without changing Spindle core.

## Quick Start

```bash
uv sync --extra dev

spindle dist install examples/spindle-sample/distributions/spindle-sample
spindle dist activate spindle-sample

spindle doctrine show
spindle skill list
spindle bind /path/to/repo --harness claude
```

`spindle bind` classifies the target repo, resolves the channels it subscribes to,
lints the blend for coherence, renders through the active harness/model profiles,
and materializes the selected skills into the surface's harness-native skills
directory.

## Concepts

| Term | Meaning |
| --- | --- |
| package | A pip-installable project that declares skills and capabilities in `[tool.spindle.package]`. |
| distribution | A pip-installable bundle that declares `[tool.spindle.distribution]` and depends on packages. |
| channel | A versioned `(scope x harness)` manifest listing the skills a surface should receive. |
| surface | A repo or agent that consumes a skill blend. |
| profile | A harness/model renderer such as `identity`, `terse`, or `trim`. |
| blend | The resolved skill subset for a surface. |

## Reference Layout

```text
examples/spindle-sample/
  packages/sample-planning/              # [tool.spindle.package]
  distributions/spindle-sample/          # [tool.spindle.distribution]
  channels/system/system/claude/         # sample channel
  profiles/                              # harness/model render profiles
  doctrine/                              # minimal doctrine used by lint/render
  peers/ verdicts/ scout/ roster/        # optional learning/marketplace scaffolds
```

## Build Your Own

```bash
spindle package new my-tools --dest ./packages/my-tools \
  --skill clarify --skill review --capabilities planning

spindle dist new my-dist --dest ./distributions/my-dist \
  --source-dir ../../ \
  --package my-tools==0.1.0
```

Spindle discovers installed packages through `[tool.spindle.package]` metadata and
installed distributions through `[tool.spindle.distribution]`.

## Pluggable Sinks

The OSS base includes local reference implementations:

- `spindle ingest` writes a topo-ordered task queue to `SPINDLE_TASK_QUEUE` or
  `$SPINDLE_HOME/tasks.jsonl` unless `SPINDLE_TASK_URL` is set.
- `spindle gate file` writes decision gates to `SPINDLE_GATE_QUEUE` or
  `$SPINDLE_HOME/gates.jsonl`.
- `spindle scout` materializes per-peer prompts and emits commands from
  `SPINDLE_SCOUT_COMMAND`.

Private infrastructure should live in separate adapter packages that depend on
Spindle rather than being imported by Spindle core.

## Behavioral Evaluation

Rendering and binding prove that a skill is available, not that it improves an
agent. Spindle evaluation manifests run the same cases with and without a skill,
randomize pair order, and write a receipt whose promotion gate uses only held-out
behavioral scores.

```bash
spindle eval validate examples/evaluation-sample/eval.toml
spindle eval run examples/evaluation-sample/eval.toml
spindle eval show examples/evaluation-sample/receipts/<receipt>.json
```

The runner is an argv contract rather than a built-in model client. A local test
harness or isolated executor can implement it while Spindle owns the manifest,
hashes, pairing, evidence validation, and promotion decision. See
[Behavioral Skill Evaluations](docs/skill-evaluations.md).

## Development

```bash
uv run --extra dev pytest
```

MIT licensed. Contributions welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).
Release process and versioning: [RELEASING.md](RELEASING.md).
