# Job-scoped leases: the dispatcher integration contract

Status: implemented CLI surface, 2026-08-17. Skill *selection* policy is
explicitly out of scope; the dispatcher passes an explicit skill list.

## Problem

A project surface usually carries one standing binding: the durable skill set
adopted for that repository. A job dispatcher (an external runner that sends
one agent into a repository to do one bounded task) often knows more than the
binding does: the work item's intent, kind, and lifetime. That job should be
able to run with a task-scoped subset of extra skills — leased for the job's
lifetime, keyed to the dispatcher's job id, and gone when the job ends —
without touching the project's standing binding.

Job-scoped leases are ordinary Spindle leases. They ride the existing borrow
machinery: exact content identity, preflight, surface-lock composition,
ownership receipts, startup reconciliation, and TTL expiry. The only new fact
is `job_id` on the lease receipt, plus a CLI surface that grants and releases
by job identity instead of lease identity.

## Composition with the standing binding

A job lease never replaces the surface's desired state; it overlays it:

- The surface lock keeps every binding- and adoption-authority projection.
  A job lease appends one projection per skill with authority
  `lease:<lease_id>`, exactly as `borrow` does.
- A job lease that collides with a standing projection or a foreign
  same-name skill is **blocked**, not merged. The standing state always wins.
- Release and expiry remove only projections whose authority names the job's
  leases and whose ownership receipts match the exact symlink on disk.
  Foreign and user-managed state is preserved (the standing crash-safety
  doctrine).
- Realized skills land in the same place the harness reads for the surface
  (for example `<repo>/.claude/skills/<skill>` for Claude Code or
  `<repo>/.agents/skills/<skill>` for Codex), so a dispatched agent's harness
  discovers them alongside the standing binding with no dispatcher-side
  plumbing.

## CLI contract

### Job start

```sh
spindle job grant \
  --for-job <job-id> \
  --skill <reference> [--skill <reference> ...] \
  --repo <workdir> \
  --harness <claude|codex> \
  [--until <duration-or-instant>] \
  [--posture read-only|sandboxed|full] \
  --json
```

- `--for-job` is the dispatcher's job identity: 1-128 characters of
  `A-Za-z0-9._:-`, starting alphanumeric. It is recorded verbatim on each
  lease receipt (`job_id`) and is the release key.
- `--skill` is repeatable and explicit: a skill directory path, an installed
  skill/package name, or `<package>#<skill>` — the same references `borrow`
  accepts. The dispatcher decides *which* skills; Spindle never guesses.
- `--until` defaults to `4h`. It is the job-lifetime ceiling, not a renewal
  loop: pick a value comfortably longer than the job's expected runtime.
- Each skill becomes one independent lease. The command continues past a
  blocked skill and reports per-skill results:
  `granted`, `already-granted` (idempotent retry), or `blocked` with the
  reason. Exit is `0` when nothing blocked, `2` otherwise.
- The grant is idempotent per `(job, surface, skill)`: re-running after a
  dispatcher crash re-reports `already-granted` instead of duplicating.

### Job end

```sh
spindle job release --for-job <job-id> --json
```

- Releases every lease recorded for the job, on every surface (scope to one
  surface with `--repo` if desired). Removes only lease-owned projections and
  writes a `released` lease event per lease.
- Idempotent and always safe to call: already-released leases and unknown
  job ids are no-ops with exit `0`.

### Inspection

```sh
spindle job status --for-job <job-id> --json
```

Reports each lease's skill, surface, expiry, attachment, and state
(`active`, `released`, or `expired`).

## Crash safety: TTL plus startup reconciliation

If the job dies (or the dispatcher does) without releasing:

1. The leases expire at `--until` by themselves; the receipts are immutable
   and the desired state is content-addressed, so nothing is left ambiguous.
2. The next startup reconciliation on the surface (`spindle bootstrap`, the
   native startup hooks, or any lease mutation) computes the effective lock
   with expired leases removed, deletes only the lease-owned projections,
   rewrites the surface lock, and records an `expired` lease event per lease.
3. `spindle job release` after the fact reports `already-released` — calling
   it late is still correct.

No dispatcher-side cleanup daemon is required.

## Failure semantics for the dispatcher bridge

The bridge in the dispatcher should treat Spindle as a best-effort enhancer,
never a gate:

- **Spindle unavailable or the grant fails (any exit code, timeout, or
  missing binary):** proceed with the surface's standing binding. A lease
  failure must never block a job.
- **Partial grant (exit 2 with some `granted` entries):** also proceed; the
  granted subset composes with the standing binding, and job release (or
  TTL) cleans up whatever was granted.
- **Release fails at job end:** log and move on; TTL plus startup
  reconciliation is the backstop.
- Parse `--json` output; treat only per-skill `action` values as facts.
  Record `lease_id`s if the dispatcher wants to attach them to its own job
  ledger, but nothing in the release path requires them — `--for-job` is the
  key.

A minimal bridge is therefore two calls:

```sh
# job start (before launching the agent in <workdir>)
spindle job grant --for-job "$JOB_ID" --repo "$WORKDIR" --harness "$HARNESS" \
  --skill "$SKILL_A" --skill "$SKILL_B" --until 4h --json || true

# job end (always, in a finally block)
spindle job release --for-job "$JOB_ID" --json || true
```

## Out of scope

- **Skill selection policy.** Mapping a work item's intent or kind to a
  skill list is the dispatcher's (future) concern; this contract only accepts
  an explicit list.
- **Renewal.** A job that outlives its TTL re-grants; leases are not
  auto-renewed.
- **New evaluation or marketplace machinery.** Job leases reuse the existing
  preflight, trust, and policy gates unchanged.

## Record shape

The only schema change is one optional field on `spindle.lease/v1`:
`job_id`, emitted only when present, so pre-existing lease receipts keep the
exact content identity they were recorded under. Lease plans, lease events,
surface locks, ownership receipts, and startup receipts are unchanged; a
job's history is recovered by filtering lease receipts on `job_id` and
following their `lease_id`s through plans and events.
