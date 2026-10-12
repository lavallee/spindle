# Harness-native operator forward test

Date: 2026-07-31. The raw harness streams remained in temporary local storage;
only bounded facts and their SHA-256 anchors are recorded here.

## Contract under test

1. `spindle harness setup --dry-run` writes nothing.
2. Setup snapshots one exact bundled operator, creates a receipt-owned native
   project skill, structurally merges stable hooks, and preserves foreign state.
3. A fresh harness discovers `$spindle` (Codex) or `/spindle` (Claude Code).
4. The operator executes `spindle harness context --here --json` and reports its
   returned state rather than inventing lifecycle facts.
5. Installed operator, configured hook, observed heartbeat, and behavioral
   response remain separate gates.
6. When a child harness inherits its parent's markers, the active child routes
   from the nearest harness process.

The operator package digest was
`sha256:6c9a14bd5c467efccea1384b9782edb0ee3eaa07dcb8839328779911d3d9623a`.

## Observed runs

| Harness coordinate | Invocation and observed behavior | Startup evidence |
| --- | --- | --- |
| Codex CLI 0.146.0, requested `gpt-5.6-terra` | `$spindle` was discovered; the agent executed exactly `spindle harness context --here --json` and returned `codex`, `environment`, `current`, `configured-unverified`, and the first recommended command. | The project hook definition was present, but noninteractive `codex exec` produced no heartbeat. This remains `configured-unverified`; project-layer and command trust are not inferred. |
| Claude Code 2.1.220, served `claude-sonnet-5`, `dontAsk` | `/spindle` was discovered; the agent executed exactly `spindle harness context --here --json` and returned `claude`, `process-tree`, `current`, the blocked hook state, and the first recommended command in two turns. | `SessionStart` executed. It honestly recorded `blocked` because four pre-existing user-scope same-name conflicts remained; no foreign entry was changed. |

The first nested Claude run exposed both `CODEX_THREAD_ID` and Claude markers and
failed closed as ambiguous. After process-aware routing, the same nested shape
selected Claude from the nearest ancestor. A separate setup attempt against the
polluted Claude inventory initially withheld the operator because strict startup
was blocked; setup was then separated from full-surface cleanliness so the
diagnostic surface can be installed without weakening the blocked startup fact.

## Raw anchors

- Codex JSONL: `af7dc0c70484e9ff1426286b3c7d8b84449a7762cf5e7284934b02c49c80c72b`
- Codex final response: `47d0c65cc324258b9816b427c3b6aa80aa234e1ef2a073b6d198b20c326e0745`
- Claude stream JSONL: `b4f7b688d72ca51df21d683464c0dc7562dc2a26ef00a5bc80899bc55b698729`
- Claude setup JSON: `f8dca0719597cee8f323d08b3992d8c82c31feec462225e7d4caa2535d456d17`

## Product conclusions

- The harness skill should remain a small adapter to live state, not a second
  documentation bundle.
- Operator availability is valuable even on a blocked surface; it gives the
  harness the exact evidence needed to explain and repair the block.
- Runtime routing needs active-process evidence because environment inheritance
  is normal in mixed-harness orchestration.
- A setup command must never collapse definition presence into hook execution.
  `configured-unverified` is an expected, actionable state.
- Full-surface cleanliness, operator custody, action authorization, and task
  behavior are independent acceptance gates.
