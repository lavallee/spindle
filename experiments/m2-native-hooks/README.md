# Milestone 2 native-hook evidence

Captured 2026-07-31 against Claude Code 2.1.220 and Codex CLI 0.146.0.
`native-evidence.tar.gz` contains a `repo/` fixture with one unrelated
user-managed skill in each harness scope, four exact Spindle-owned projections,
and stable hook definitions. Its `state/` tree contains the content-addressed
plans, ownership records, conflict decisions, hook receipts, startup receipts,
and append-only heartbeat chronology produced by the runs. The deterministic
archive digest is
`sha256:370b2fe58c1393575425dddcd1ec52bf915fe172c17b40aa9e386b92f5da1b6f`.

The archive intentionally retains raw machine-local inventory evidence. Inspect
it as evidence rather than as a portable fixture. To restore the live symlink
layout, extract `repo/` and `state/` directly beneath this directory.

## Certified paths

- Claude `Setup --init-only`, fresh Sonnet 5, fresh Opus 5, Sonnet 5 resume,
  and a Sonnet 5 `Explore` subagent all invoked the native hook command.
- Codex fresh and resume sessions invoked the native hook command from a trusted
  repository layer with model `gpt-5.6-sol`.
- A pre-launch receipt and the following native heartbeat agreed on the exact
  surface lock and inventory digest for both harnesses.
- Deleting one exact owned Codex projection and running reconciliation restored
  only that link. The unrelated `ambient` skill retained SHA-256
  `cfb0646df29ec8aa67d5c3d08bf1e6c05002b362135af448254b7ff56b692aa9`
  before and after repair.
- Five real Claude user-scope name collisions were preserved, blocked startup,
  and were then admitted only through exact path-and-content conflict decisions.

## Anchor receipts

| Evidence | Receipt or digest |
| --- | --- |
| Claude hook install | `sha256:49b794f4a1eed51cc02753990dfeec8a2db2e408635a9a258f2af00e767c032e` |
| Claude pre-launch | `sha256:8a4137186636bb0a7f421950347397fe311fd7c0300231e2cd678f0c14f09c82` |
| Claude live Sonnet heartbeat | `sha256:3437e852bf89fa2f873ecdc78e557dd64979b5d07f3ba0b397a2c4591fe43e0d` |
| Claude live subagent heartbeat | `sha256:b15ad856cefc7d66328933ae2a220567da845ce10ebe8ad36b99c3b94970965a` |
| Claude locked inventory | `sha256:caf0d8845f60fc23e3e66c1bec19268b01c54e6078a3f42e0acfadca9a1161db` |
| Codex trusted-layer hook install | `sha256:c27627f6072fae62812ed2b68fb0330b424cc5223c550a7dad20c603afe30399` |
| Codex pre-launch | `sha256:4215fcb0f080064a12e3b42854f16033f44e30c8096fd5f70fa458df0761859f` |
| Codex live native heartbeat | `sha256:5362d0b080e87856d6a7628133b1e4640bc5e6caa441c3663b73fa803ccb0b69` |
| Codex locked inventory | `sha256:259f8370063b657bae29955883168d157b64fb0a0efcb9995e827f1b84ace8c0` |
| Owned-link repair | `sha256:9ef0f856cc073a043c9f58d368f14ef3e4a04085f9c6c6417e4eaad242752112` |

The direct native command path measured 0.142 seconds for Codex and 0.634
seconds for Claude in this environment. It used the metadata-keyed digest cache;
tests make any fallback to a deep content hash fail.

## Adapter facts discovered live

Claude Code 2.1.220 did not include `model` or `permission_mode` in the observed
`SessionStart` payload, although its subsequent initialization event reported
them. Its `SubagentStart` payload likewise did not identify the child model.
Those fields remain unknown in the startup receipt instead of being inferred;
activation/delegation evidence must join them later.

Codex ignored project-layer hook configuration until that repository layer was
trusted. Command trust bypass did not make an untrusted configuration layer
active. Hook configuration state and repository-layer trust are therefore
reported as distinct adapter facts.

The transient nested Git repository used to establish the Codex trust behavior
is intentionally absent from this evidence fixture. No user-managed skill was
removed or rewritten during collection.
