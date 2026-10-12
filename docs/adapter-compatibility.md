# Adapter compatibility and certification

Spindle treats harness support as a claim about one named build, not a permanent
property of a harness name. A certification joins deterministic conformance
cases to live activation receipts for the actual parent and child agents.

## Capability statuses

`spindle adapter matrix` reports each capability as:

- `pass`: the supplied observation contains digest-verified evidence;
- `partial`: the reference adapter implements only part of the contract;
- `fail`: the capability was tested and failed; or
- `unknown`: the observation could not establish it.

The default matrix fails closed for runtime facts. Projection mechanics,
inventory, bootstrap, reload, restart, and receipt integrity are implemented by
the reference adapters; model identity, effective tools, effective policy, and
subagent independence remain `partial` until a build-specific observation is
supplied.

```bash
spindle adapter matrix --harness codex --build 0.146.0 \
  --require model-identity

spindle adapter matrix --harness claude --build 2.1.220 \
  --observation experiments/m7-adapter-certification/claude-observation.json \
  --require subagent-independence
```

## Reference certifications

The 2026-07-31 evidence set certifies these exact coordinates:

| Harness build | Parent | Child | Certification |
| --- | --- | --- | --- |
| Claude Code `2.1.220` | `claude-opus-5` | `claude-sonnet-5` | `sha256:96c11b9d…` |
| Codex CLI `0.146.0` | `gpt-5.6-sol` | `gpt-5.6-terra` | `sha256:f4093c3f…` |

Both parent and child loaded the same content-addressed canary independently.
Claude directly reported the parent tool list and both `Skill` invocations; the
child tool restriction and inherited plan-mode policy are derived from the exact
custom-agent contract joined to the forwarded child event. Codex independently
reported each thread's model, reasoning effort, approval mode, read-only sandbox,
managed filesystem/network policy, and tool-composition identity. Each thread
also produced its own observed `SKILL.md` read and canary token. The Codex tool
composition remains opaque apart from its harness-reported identity and the
calls actually observed.

This is an adapter-contract certification, not a general model-quality claim.
Changing the harness build, model, tool composition, policy, package digest, or
active blend reopens the corresponding evidence.

Verify the checked-in receipts without trusting prose:

```bash
spindle adapter verify \
  experiments/m7-adapter-certification/certifications/96c11b9d*.json
spindle adapter verify \
  experiments/m7-adapter-certification/certifications/f4093c3f*.json
```

To certify another build, produce a `spindle.adapter-conformance-observation/v1`
file with every published case and independent activation receipts, then run:

```bash
spindle adapter certify observation.json --dry-run --json
spindle adapter certify observation.json --json
```

Passing cases must have digest-valid artifacts. Activation receipts must prove
`projection_loaded = true`, served model, harness build, effective tools, and
effective policy with observed or explicitly derived authority. Parent and child
receipts cannot be shared, and their harness/build must match the observation.

## Reproducing the evidence reduction

The reducer at
`experiments/m7-adapter-certification/build_evidence.py` accepts raw Claude
stream JSON and Codex parent/child rollout logs. It checks the canary and runtime
relations, writes only sanitized structural facts, and binds them to the raw-log
SHA-256 digests. It deliberately does not copy prompts, responses, debug logs,
credentials, or ambient skill inventories into the repository.

Run the deterministic contract suite and receipt verification from a fresh
checkout with:

```bash
uv sync --extra dev
uv run pytest -q tests/test_conformance.py tests/test_acceptance_journey.py
uv run pytest -q
uv run ruff check .
git diff --check
```

Live recertification additionally requires the named harness builds and valid
harness authentication. A newer build is a new coordinate and must not reuse the
certification merely because the adapter command line still works.
