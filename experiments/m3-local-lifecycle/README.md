# Milestone 3 local-lifecycle evidence

Captured 2026-07-31 against Claude Code 2.1.220 (Sonnet) and Codex CLI
0.146.0 (`gpt-5.6-sol`). `candidate/spindle-lease-canary` is the exact local
candidate and `task.md` is the trial input. `state/` retains the package snapshot,
lease plans and grants, ownership/startup/activation receipts, cleanup events,
and run receipts.

Both actual harnesses returned exactly `SPINDLE_LEASE_CANARY_OK\n`. Its recorded
stdout digest is
`sha256:2f5c63dc5be09ad2557824a555277f784f9a11d4fbe4b8006bb8e2716fcae03d`
in both independent run receipts. Neither run left the canary in `.claude/skills`
or `.agents/skills`; the final surface locks contain no lease or projection.

| Evidence | Claude | Codex |
| --- | --- | --- |
| Lease | `sha256:06eaaf2e77b765cb816e1e788354a232ccfdb9cec745d832b96ba75cb4df6ea1` | `sha256:874c2e8a18b4a965a0c1d9c53e4fd893ac42c3278f17a48debc0c48fa938fcaa` |
| Activation startup | `sha256:b9754b4aa5a36ce93765194b2c861347370c67f40617b63d0c5b1f3c1555dc26` | `sha256:667a2b61f90a45322dd22a01121e8aec68a1cc7f50ed87b7f2123a1bd0e03096` |
| Activation | `c3dc3bb9d00220aad9436e2a96c1fe4d16231cc8777aaf4a6ffeca90add386cc` | `a9f1e54a7a4f9174665393773320cf353171c08928da84696e4134edb1fa5006` |
| Cleanup startup | `sha256:149115b442432f19d93e5f4590498edc6a64021e204710eb0d8cdc2376829df0` | `sha256:fe4b317392def8ce1904c93e77dbec672c97cfdba6f041ab18dbc40e3ff98bfd` |
| Cleanup event | `sha256:cba42784c9726b966ab00abcc413300e2e83b7b2978cec77dce32ebcdac249aa` | `sha256:d7188a5b7052239ffbbecef026e23459bc0f84417f9bd847623ee0d3f1d0ed21` |
| Trial run | `sha256:78c93da7d920d7385bd171af1a02e23716cb90f63883a054a37c54f491713795` | `sha256:816aef70cfb6a1286c44594ca181e9f6ef1e28178f83fc9bf7f8e8e4da309f64` |

The first Claude preflight used the real user discovery scope and correctly
blocked before caching or projection because two unrelated user skills already
had duplicate names. The successful Claude run isolated discovery HOME while
using the existing authenticated Claude configuration. This exposed a harness
side effect: Claude created `/home/marc/.claude/.claude.json` after first
reporting it missing. Spindle relocated that exact generated file intact to
`/tmp/spindle-generated-claude-config-20260731.json`; the older Claude backup and
all pre-existing user skills/configuration were left untouched. The temporary
isolated HOME, including harness-created npm cache data, was likewise relocated
out of the repository after the run.

Codex emitted unrelated MCP authentication errors on stderr for configured
services that were unavailable to the read-only run. The trial itself succeeded;
the stderr text is not retained, only its digest. This demonstrates why run exit,
stdout, stderr, activation, routing, authorization, and behavior must remain
separate evidence gates.
