# Startup integrity and native hooks

Spindle treats a harness discovery directory as observed state, not desired
state. A surface lock names the exact projections Spindle expects; immutable
ownership receipts prove which links Spindle may repair or remove. Everything
else is preserved as foreign state.

## Harness-native operator

For the ordinary in-session UX, preview and install the bundled operator plus
the stable repo-scoped hook kit together:

```bash
spindle harness setup --harness codex --here --dry-run
spindle harness setup --harness codex --here
spindle harness status --harness codex --here

# after starting a new session
# Codex:       $spindle show current skill state
# Claude Code: /spindle show current skill state
```

Setup caches exact operator bytes and creates a receipt-owned project skill. It
does not treat unrelated ambient conflicts as a reason to withhold the diagnostic
surface: the operator may be `current` while the full surface remains `blocked`.
`status` keeps operator custody, hook definition, trust/enablement, and observed
heartbeat separate. Remove with `spindle harness remove --harness <name> --here
--dry-run`; only the exact owned projection and hook fragments are eligible.

## Portable pre-launch boundary

Run bootstrap before the harness discovers skills:

```bash
spindle bootstrap --harness claude --here --check
spindle bootstrap --harness codex --here --reconcile-owned
spindle launch claude --here -- --model sonnet
spindle launch codex --here -- --model gpt-5.6-sol
```

`--check` never changes a projection. `--reconcile-owned` may create, update, or
remove a projection only when the surface lock supplies an immutable source
digest and the current ownership receipt permits that exact action. Planning,
mutation under a per-surface process lock, and post-apply observation are
separate phases. The content-addressed plan and receipt paths are printed after
each run.

Decisions have distinct meanings:

| Decision | Meaning |
| --- | --- |
| `ok` | Desired state is exact and no warning remains. |
| `warn` | Desired state is exact, but preserved foreign or opaque state remains. |
| `blocked` | An unresolved conflict, missing proof, disabled expected skill, or ownership ambiguity prevents a clean launch. |
| `restart-required` | A native post-discovery hook found drift that must be reconciled before a new harness session. |

`spindle launch` runs the harness only after an `ok` or `warn` preflight. A
native hook is an observer after discovery; it never claims an in-place repair
made the current session clean.

## Stable native hook kits

Inspect and install the small stable adapter definitions separately from skill
pins and leases:

```bash
spindle hooks plan --harness claude --scope repo --here --json
spindle hooks install --harness claude --scope repo --here --dry-run
spindle hooks install --harness claude --scope repo --here

spindle hooks status --harness claude --scope repo --here --effective
spindle hooks remove --harness claude --scope repo --here --dry-run
spindle hooks remove --harness claude --scope repo --here
```

The Claude kit structurally merges `SessionStart`, `Setup`, and
`SubagentStart` groups into `.claude/settings.json`. The Codex kit merges
`SessionStart` and `SubagentStart` into `.codex/hooks.json`. If a Codex repo
already defines inline `[hooks]` in `.codex/config.toml`, installation blocks
instead of creating a second representation at the same layer.

An identical pre-existing command is foreign unless an immutable Spindle hook
receipt proves Spindle added that exact group. Removal deletes only exact owned
groups, preserves every unrelated key and handler, and blocks if an owned group
was edited. Hook definitions call only:

```text
spindle bootstrap --hook <harness> --event <event>
```

Changing a package pin, lease, or surface lock therefore does not change the
trusted hook definition.

`hooks status` keeps three facts separate:

- **configured:** the exact definitions are present;
- **enabled/trusted:** static controls do not disable them, while runtime trust
  remains unproven until the harness runs them; and
- **observed:** a chronological heartbeat points to an immutable startup
  receipt.

`configured-unverified`, `observed-warn`, `restart-required`, and `blocked` are
not reported as a clean observation. `doctor --startup` includes this hook state
and blocks when hooks are statically disabled or a latest heartbeat is blocked.
Codex project hook definitions also require the project config layer and exact
command definition to be trusted in the harness. Claude and Codex expose their
configured sources through their respective hook inspectors.

## Fast session and resume checks

A deep bootstrap computes exact content digests and warms immutable cache entries
keyed by resolved path plus a recursive filesystem metadata fingerprint. Native
session, resume/compact, and subagent callbacks use cache-only verification:
they do no network access, behavioral evaluation, or content re-hashing. A cache
miss or changed fingerprint is unknown evidence, never success.

Active and expired lease IDs are resolved from immutable lease receipts on every
startup event. An expired projection is absent from the effective lock. A
pre-launch reconcile removes only its exactly owned link and records an expiry
event; resume/compact and other post-discovery hooks report `restart-required`
without mutating the current session. Cached package retention is independent of
runtime lease expiry.

The hook compares the current inventory with the latest successful pre-launch
receipt. It emits one short context marker and stores details in the immutable
receipt. A separate append-only observation log provides chronology without
putting timestamps into reproducible receipt identity.

## Explicit foreign conflicts

Same-name foreign entries are preserved and block strict startup. If coexistence
is intentional, record a reviewable, exact allowance:

```bash
spindle conflict allow review \
  --path /absolute/path/to/foreign/review \
  --reason "The user-scoped reviewer intentionally coexists here." \
  --harness claude --here --dry-run

spindle conflict allow review \
  --path /absolute/path/to/foreign/review \
  --reason "The user-scoped reviewer intentionally coexists here." \
  --harness claude --here

spindle conflict list --harness claude --here
spindle conflict revoke sha256:... --harness claude --here --dry-run
```

The decision binds the surface, harness, skill name, absolute observed path, and
full content digest. A content or path change invalidates it automatically.
Revocation removes the decision from desired state but retains its immutable
historical receipt. No conflict decision transfers ownership of the foreign
artifact to Spindle.

## State and audit files

Under `$SPINDLE_HOME`, startup uses:

- `surface-locks/` for mutable current desired state with content identity;
- `ownership-receipts/` and `ownership/` for projection custody;
- `conflict-receipts/` for exact foreign-state decisions;
- `lease-receipts/`, `lease-plans/`, and `lease-events/` for temporary authority
  and cleanup history;
- `startup-plans/` and `startup-receipts/` for immutable attestations;
- `startup-observations.jsonl` for explicitly non-addressed chronology;
- `cache/inventory-digests/` for immutable fast-path digest proofs;
- `hook-receipts/` and `hooks.json` for native hook custody; and
- `startup-locks/` for process serialization.

Claude hook behavior is documented in the
[Claude Code hooks reference](https://code.claude.com/docs/en/hooks). Codex hook
locations, trust, inputs, and outputs are documented in the
[Codex hooks reference](https://developers.openai.com/codex/hooks).
