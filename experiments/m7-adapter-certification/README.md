# M7 adapter certification evidence

Date: 2026-07-31. This directory is the privacy-safe evidence anchor for
Spindle's current 0.x Claude Code and Codex reference adapters.

## Certified coordinates

| Harness | Build | Parent | Child | Certification |
| --- | --- | --- | --- | --- |
| Claude Code | `2.1.220` | `claude-opus-5` | `claude-sonnet-5` | `sha256:96c11b9de1ad6f9623fc78a5b8b681edea1ab643b6b126dfc41f85246b38805c` |
| Codex CLI | `0.146.0` | `gpt-5.6-sol` (`xhigh`) | `gpt-5.6-terra` (`medium`) | `sha256:f4093c3fc577da9ec35e1da502e9e51ad27001683140a468c6276338bef6f48c` |

The canary package digest is
`sha256:f240e43d42b60249b578cc78056ec2868fef9d8a126fa2f81bce723da2bcfaa1`.
Each parent and child received a distinct activation receipt:

- Claude parent `19e0ec73…`, child `641a6317…`;
- Codex parent `ebf17edd…`, child `f91b9c06…`.

## What was observed

Claude's stream init directly reported build, Opus model, plan permission mode,
and the `Task`/`Skill` tool surface. The parent invoked the canary through
`Skill`, invoked the named custom agent, and the forwarded Sonnet child invoked
the canary through its own `Skill` call under the Agent tool-use ID. The result
accounted for Opus and Sonnet and reported no permission denials. The child's
one-tool envelope and inherited plan policy are derived from the exact custom
agent definition joined to that runtime event, and are labeled `derived` in the
receipt.

Codex wrote independent parent and child session records. Each turn context
reported its actual model, reasoning effort, CLI build, approval policy,
read-only sandbox, managed filesystem/network policy, and tool-composition
identity. The parent actually called `spawn_agent`, `wait_agent`, and `exec`; the
child actually called `exec`. Both independently read a `SKILL.md` whose tool
result contained the canary token. Codex's complete tool list is opaque here;
the receipt retains the harness composition identity plus the calls actually
observed rather than inventing a list.

## Privacy and reproduction

`build_evidence.py` reduces raw Claude stream JSON and Codex rollout JSONL into
the files under `evidence/`, writes activation receipts and observations, and
runs the public conformance certifier. Raw transcripts and debug logs can contain
prompts, ambient configuration, and other local context, so they are not checked
in. Their SHA-256 digests remain in the sanitized evidence. The release test
asserts that no `.jsonl` or `.log` appears in this directory.

The deterministic conformance fixtures and prior live hook/source archives are
bound in `evidence/conformance-suite.json`. Verify the release evidence with:

```bash
uv run pytest -q tests/test_conformance.py tests/test_acceptance_journey.py \
  tests/test_release_evidence.py
uv run spindle adapter verify certifications/96c11b9d*.json
uv run spindle adapter verify certifications/f4093c3f*.json
```

The full 0.x checkpoint is `832 passed`, `ruff check .` clean, and `git diff
--check` clean. A fresh-wheel smoke test produced:

- wheel SHA-256 `3a844163b26cda7103e46f17cd8f6f6e19d9703cc23ba569f3e7898f881c54d4`;
- source archive SHA-256 `aca502cc2555b217a9e74b3d49c573185f0fec4f06fc2e74766b6643ddedc6d3`.

These artifact digests describe this worktree build, not a published release.
Any changed source tree, harness build, model, tool composition, policy, active
blend, or canary digest requires fresh evidence.
