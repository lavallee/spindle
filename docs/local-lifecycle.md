# Candidate inspection, pinned sources, trials, and expiring leases

Spindle can evaluate a local skill candidate without first turning it into a
maintained dependency. Inspection, caching, temporary runtime authority, durable
adoption, and harness activation are separate operations.

## Inspect without activation

```bash
spindle inspect ./candidate/review \
  --for "review this database migration" \
  --harness codex --here --json

# A local package with more than one skill needs an exact fragment.
spindle inspect ./candidate-package#review --harness claude --here
```

Inspection reads candidate files and the effective harness inventory. It does
not import candidate modules, execute scripts, populate the package cache, write
Spindle state, create a projection, or change desired state. The intent card
keeps two sections distinct:

- `package_facts` reports outcome/trigger metadata, the first stated behavioral
  delta, file inventory, local references and missing references, estimated
  always-visible context, exact provenance, runtime-profile declarations,
  freshness basis, and executable/tool authority indicators;
- `fit_analysis` reports deterministic structural/name fit and labeled lexical
  overlap with `--for`. It explicitly leaves behavioral fit `unassessed`.

That distinction matters: a matching description is not evidence that a skill
improves the task, and an executable-looking resource is not permission to run
it.

Local references may name a skill directory, its `SKILL.md`, an installed skill
or package, or `<path-or-package>#<skill>`. Every result resolves to a full
package digest and a separate skill digest.

## Inspect a pinned remote source

GitHub and skills.sh-compatible Git sources use an explicit provider, revision,
and optional skill fragment:

```bash
spindle inspect \
  'skills.sh:owner/repository@main#review' \
  --harness codex --here --json

spindle inspect \
  'github:owner/repository@0123456789abcdef0123456789abcdef01234567#review' \
  --offline --harness codex --here --json

# Generic HTTPS/SSH/file Git URLs and absolute local Git repositories:
spindle inspect 'git+https://example.test/skills.git@v2#review' --here
spindle inspect 'git:/absolute/repository@main#review' --here
```

A mutable revision such as `main`, a tag, or `HEAD` is resolved to a full Git
commit before any lease is constructed. Spindle keeps a bare object cache and a
safe exported snapshot, writes an immutable source receipt joining provider,
locator, requested revision, commit, tree, and complete package digest, then
builds the intent card from that snapshot. Export rejects traversal, special
files, duplicate paths, escaping symlinks, excessive size/count, malformed
receipts, and snapshot digest drift. `--offline` can reuse an already verified
commit without contacting the source; a cache miss fails closed.

Remote inspection does write source-cache, source-receipt, snapshot, and
preflight evidence. It does not populate the runtime package cache, create a
surface lock, project a skill, execute bundled code, or adopt anything. This is
the deliberate difference from zero-write local inspection.

The static preflight checks the selected skill's structure, references,
realization manifest, executable/script-like files, network/credential/process
indicators, declared tools, package license artifacts, and current composition.
Named `--attestation NAME=PATH` inputs are stored only as opaque artifact
digests; they are evidence inputs, never proof. A future lease requires explicit
approval for every indicated expansion:

```bash
spindle borrow 'skills.sh:owner/repository@<commit>#review' \
  --until 2h --allow-executable --allow-network \
  --allow-credentials --allow-tool Bash --here --dry-run
```

These flags authorize the lease plan's ceiling. They do not claim that the
harness granted the authority; configured and observed runtime permissions stay
separate evidence facts.

## Borrow without adoption

```bash
spindle borrow ./candidate/review \
  --harness codex --here --until 2h --dry-run --json

spindle borrow ./candidate/review \
  --harness codex --here --until 2h

spindle release sha256:... --harness codex --here --dry-run
spindle release sha256:... --harness codex --here
```

`borrow` first exposes a content-addressed `LeasePlan`. On apply it snapshots the
exact local package into `$SPINDLE_HOME/cache/packages`, writes an immutable lease
grant, adds one projection authorized as `lease:<lease-id>` to the existing
surface lock, and runs ownership-safe startup reconciliation. It does not create
an adoption record or alter the incumbent binding. A normal bind preserves
non-colliding active lease projections and blocks before mutation if it wants the
same skill name.

The default posture is `read-only`. `--posture sandboxed|full` records an
explicitly broader authority ceiling; it does not silently reconfigure a running
harness's permissions. Runtime permission evidence remains a separate adapter
fact.

`--until` accepts an ISO-8601 timestamp or `30m`, `2h`, and `7d`-style durations.
At each startup, resume, or compaction check, Spindle loads the immutable lease
receipt and evaluates it against the event time:

- an active lease remains in the effective lock and appears in the startup
  receipt;
- an expired lease is excluded from effective desired state;
- pre-launch reconciliation removes its exact owned link, updates the lock, and
  writes an expiry event;
- a post-discovery native hook leaves the link alone and reports
  `restart-required`.

The package bytes remain in the cache after release or expiry. Runtime
availability and cache retention are intentionally different facts.

## Try for one disposable session

```bash
spindle try ./candidate/review \
  --harness claude --model sonnet \
  --task-file ./task.md --here --dry-run --json

spindle try ./candidate/review \
  --harness codex --model gpt-5.6-sol \
  --task-file ./task.md --here
```

`try` creates a session-scoped lease over the actual incumbent lock, reconciles
and attests the projection, writes an activation receipt, and explicitly invokes
the candidate in the task prompt. The reference adapters enforce a read-only
launch posture:

- Claude uses print mode, plan permissions, an allowlist of read tools, and no
  session persistence;
- Codex uses `exec --ephemeral`, a read-only sandbox, and no approvals.

The lease is released in a `finally` cleanup path even when harness launch
fails. The content-addressed run receipt retains the task digest, redacted command
shape, harness exit code, startup receipt, activation receipt, and cleanup event.
It also records stdout/stderr digests without retaining their potentially
sensitive text, and it does not retain the task text. If the Spindle process is
terminated before cleanup can run, the bounded expiry remains in desired state
and the next pre-launch reconciliation can recover it.

The activation receipt proves that the exact projection was present in the
post-apply inventory. It does not claim that the model routed to or benefited
from the skill; those are independent activation/routing and behavioral gates
that require harness observation and evaluation evidence.

## Promote only successful trial bytes

`adopt` is the only trial command that adds durable adoption state:

```bash
spindle adopt sha256:<lease-id> --scope repo --here --dry-run --json
spindle adopt sha256:<lease-id> --scope repo --here
```

Promotion requires an immutable lease-creation plan, a zero-exit run receipt,
an activation receipt, completed trial cleanup, intact cached bytes, and a
currently non-quarantined package. The content-addressed `AdoptionRecord` binds
those receipts to the owner, repository surface, harness, exact source/package/
skill identities, authority ceiling, update channel, retirement policy, and any
explicit evaluation claims. The dry-run writes nothing and shows that the
current implementation changes the surface lock only; distribution and channel
changes are explicitly `null`.

A trial of an explicitly pinned commit defaults to a `manual` update channel. A
trial of a mutable Git revision records that reference as a refreshable channel,
while the adopted bytes remain pinned to the commit actually tried.

## Treat every update as another trial

```bash
spindle update plan --harness codex --here --json
spindle update try review --harness codex --task-file task.md --here
spindle adopt sha256:<successful-update-lease-id> --here
```

Planning fetches, pins, statically preflights, and compares the candidate without
changing desired state. A changed candidate is projected beside the incumbent as
`review--candidate-<digest>` for one read-only harness session; cleanup removes
only that alias. Promotion replaces the incumbent only after a successful update
trial. The new adoption links to its predecessor, but its evaluation-claim list
starts empty. Package names never transfer behavioral evidence between digests.

Rollback restores the predecessor's exact lock identity and projection set:

```bash
spindle rollback review --harness codex --reason "regression" --here --dry-run
spindle rollback review --harness codex --reason "regression" --here
```

## Inspect health and end custody safely

```bash
spindle health --harness codex --here --json
spindle disable review --harness codex --reason "pause rollout" --here
spindle enable review --harness codex --reason "resume rollout" --here
spindle deprecate review --harness codex --reason "replacement ready" --here
spindle retire review --harness codex --reason "migration complete" --here

spindle vendor review --harness codex --destination ./skills/review --here --json
spindle distill review --harness codex --here --json
```

Health keeps availability, evidence, and freshness distinct. It reports current
or retained status; last activation and behavioral claim; cache and projection
integrity; effective-inventory conflicts; and drift in model, harness build,
toolset, permission policy, source revision, or package digest when those current
coordinates are supplied. Disabled, deprecated, quarantined, and retired state
does not erase receipts. Retirement changes desired state and reconciles only
the exact adoption-owned projection; unrelated harness files survive unchanged.

## Quarantine and durable records

Quarantine changes whether a package may receive a future lease without
rewriting source, preflight, lease, activation, or run history:

```bash
spindle source quarantine sha256:... \
  --reason "upstream revocation" --actor security --dry-run
spindle source quarantine sha256:... \
  --reason "upstream revocation" --actor security
spindle source status sha256:... --json
spindle source unquarantine sha256:... \
  --reason "reviewed replacement" --actor security
```

Each decision is an immutable event linked to the previous decision. The small
mutable index represents only current policy. Active and historical leases are
not rewritten; lease creation rechecks the index immediately before mutation.

The local lifecycle adds these `$SPINDLE_HOME` stores:

- `lease-receipts/`: immutable temporary authority grants;
- `lease-plans/`: immutable borrow, try, release, and expiry plans;
- `lease-events/`: immutable release/expiry cleanup history;
- `trial-run-receipts/`: immutable disposable-run outcomes;
- `source-receipts/` and `source-snapshots/`: pinned Git provenance and verified
  exported bytes;
- `preflight-receipts/`: static structure, risk, composition, authority, license,
  and attestation facts;
- `quarantine-events/` and `quarantine.json`: immutable policy history and the
  current future-lease decision; and
- `adoption-receipts/` and `adoption-plans/`: immutable durable custody and exact
  transition previews;
- `maintenance-events/` and `maintenance.json`: immutable decision history and
  the small current lifecycle index; and
- the existing package cache, surface locks, ownership receipts, startup
  receipts, and activation receipts.

All identities are full SHA-256 content addresses. Observation time is an input
to lease/event identity; no mutable status is rewritten into historical grants.

Remote input is never treated as a local editable path merely to bypass
provenance, cache verification, preflight, or authority checks.
