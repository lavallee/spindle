# Migration, recovery, and state custody

Spindle 0.x separates immutable history from rebuildable indexes. Surface locks,
ownership receipts, leases, adoption records, activation evidence, and lifecycle
events are durable custody records. Files such as the ownership, maintenance,
quarantine, and hook indexes are materialized views and can be recovered.

## Audit legacy state

Migration is deliberately not implicit adoption:

```bash
spindle migrate plan --harness codex --here --json
spindle migrate apply sha256:<plan-id> --harness codex --here --json
```

The plan inventories existing bindings and ambient harness skills. Current
surface locks remain current. Foreign and legacy skills are preserved and
reported with `inspect and try` as the next step. A legacy v1 adoption that lacks
trial and activation provenance is blocked; re-try the exact cached bytes before
creating a v2 adoption. `migrate apply` writes only an immutable audit event—it
does not move, delete, project, or adopt a skill.

## Export and import

Create a deterministic custody or diagnostic bundle:

```bash
spindle state export spindle-state.tar.gz --dry-run --json
spindle state export spindle-state.tar.gz
spindle state export spindle-state-with-cache.tar.gz --include-cache
```

The manifest names every file, byte count, digest, and durable schema. Archive
ordering, metadata, and gzip timestamp are deterministic. Package bytes are
excluded unless `--include-cache` is explicit.

Import verifies the archive, rejects traversal and links, enforces size and file
count limits, and merges only absent or byte-identical files:

```bash
spindle state import spindle-state.tar.gz --destination /new/state --dry-run
spindle state import spindle-state.tar.gz --destination /new/state
```

An existing different file is a conflict; import never overwrites it.

## Crash recovery

Plan and apply index reconstruction from immutable receipts:

```bash
spindle state recover --json
spindle state recover --apply sha256:<plan-id> --dry-run --json
spindle state recover --apply sha256:<plan-id> --json
```

Recovery validates content identities, receipt chains, ownership targets, and
surface locks before proposing replacement indexes. Apply rechecks the exact
plan under a state lock and records a recovery event. A corrupt or ambiguous
receipt blocks recovery rather than being guessed around.

## Package-cache garbage collection

Cache means immutable locally available bytes; it does not mean installed,
bound, leased, or adopted. GC removes only verified digest directories that are
unreferenced by current locks, active leases, or adoption history:

```bash
spindle state gc --json
spindle state gc --apply sha256:<plan-id> --dry-run --json
spindle state gc --apply sha256:<plan-id> --json
```

The apply command recomputes the plan under a lock. Unknown entries, symlinks,
digest mismatches, or newly created references block removal. Historical
receipts remain even when unreferenced package bytes are reclaimed.

## Rollback and runtime cleanup

`spindle rollback` creates a new lifecycle decision pointing to the exact prior
adoption; it does not rewrite history. `disable` and `deprecate` retain custody.
`retire` removes only a projection whose current path and target still match a
Spindle ownership receipt. Foreign and user-managed files are preserved in all
of these workflows.
