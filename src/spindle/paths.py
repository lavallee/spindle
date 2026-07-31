"""Filesystem locations used by spindle — platform-only paths."""

from __future__ import annotations

import os
from pathlib import Path


def _env_path(primary: str, default: Path) -> Path:
    raw = os.environ.get(primary)
    if raw:
        return Path(raw)
    return default


def spindle_home() -> Path:
    """Per-machine state directory (machine.id, fleet clone, events.jsonl)."""
    return _env_path("SPINDLE_HOME", Path.home() / ".spindle")


def machine_id_file() -> Path:
    return spindle_home() / "machine.id"


def events_file() -> Path:
    return spindle_home() / "events.jsonl"


def state_file() -> Path:
    return spindle_home() / "state.json"


def fleet_repo() -> Path:
    """Local clone of the shared git repo that aggregates per-machine event logs."""
    return _env_path("SPINDLE_FLEET_REPO", spindle_home() / "fleet")


def claude_skills_dir() -> Path:
    """User's Claude Code skills directory; what `spindle install` symlinks into."""
    return Path(
        os.environ.get("CLAUDE_SKILLS_DIR", str(Path.home() / ".claude" / "skills"))
    )


def claude_md_path() -> Path:
    return Path(
        os.environ.get("CLAUDE_MD_PATH", str(Path.home() / ".claude" / "CLAUDE.md"))
    )


def hermes_skills_dir() -> Path:
    """Spindle-owned category inside the global Hermes skills tree.

    Hermes discovers skills by recursively walking ``~/.hermes/skills``
    (following symlinks) — it does not read repo-local ``.hermes/skills``
    directories. Spindle therefore materializes hermes-harness bindings into a
    dedicated ``spindle`` category dir so it never touches hand-curated
    categories. Override with ``SPINDLE_HERMES_SKILLS_DIR``.
    """
    return _env_path(
        "SPINDLE_HERMES_SKILLS_DIR", Path.home() / ".hermes" / "skills" / "spindle"
    )


def feedback_dir() -> Path:
    return spindle_home() / "feedback"


def ledger_path() -> Path:
    return spindle_home() / "ledger.jsonl"


def realizations_dir() -> Path:
    """Immutable, content-addressed skill realizations for agent sessions."""
    return _env_path("SPINDLE_REALIZATIONS_DIR", spindle_home() / "realizations")


def realization_receipts_dir() -> Path:
    """Audit receipts connecting session coordinates to skill realizations."""
    return _env_path(
        "SPINDLE_REALIZATION_RECEIPTS_DIR",
        spindle_home() / "realization-receipts",
    )


def activation_receipts_dir() -> Path:
    """Intent-plus-runtime evidence for one projected agent realization."""
    return _env_path(
        "SPINDLE_ACTIVATION_RECEIPTS_DIR",
        spindle_home() / "activation-receipts",
    )


def delegation_receipts_dir() -> Path:
    """Receipts joining independently activated parent and child agents."""
    return _env_path(
        "SPINDLE_DELEGATION_RECEIPTS_DIR",
        spindle_home() / "delegation-receipts",
    )


def package_cache_dir() -> Path:
    """Immutable package revisions fetched or snapshotted before activation."""
    return _env_path("SPINDLE_PACKAGE_CACHE_DIR", spindle_home() / "cache" / "packages")


def source_cache_dir() -> Path:
    """Provider metadata/object stores used to resolve immutable source revisions."""
    return _env_path("SPINDLE_SOURCE_CACHE_DIR", spindle_home() / "cache" / "sources")


def source_snapshots_dir() -> Path:
    """Safely exported immutable source trees, separate from Git metadata."""
    return _env_path(
        "SPINDLE_SOURCE_SNAPSHOTS_DIR", spindle_home() / "source-snapshots"
    )


def source_receipts_dir() -> Path:
    """Content-addressed remote resolution and provenance receipts."""
    return _env_path("SPINDLE_SOURCE_RECEIPTS_DIR", spindle_home() / "source-receipts")


def preflight_receipts_dir() -> Path:
    """Content-addressed structural, authority, and static-risk reports."""
    return _env_path(
        "SPINDLE_PREFLIGHT_RECEIPTS_DIR", spindle_home() / "preflight-receipts"
    )


def quarantine_events_dir() -> Path:
    """Immutable package quarantine/revocation decisions."""
    return _env_path(
        "SPINDLE_QUARANTINE_EVENTS_DIR", spindle_home() / "quarantine-events"
    )


def quarantine_index_file() -> Path:
    """Mutable current quarantine index; historical events remain immutable."""
    return _env_path(
        "SPINDLE_QUARANTINE_INDEX_FILE", spindle_home() / "quarantine.json"
    )


def adoption_receipts_dir() -> Path:
    """Immutable durable skill custody records."""
    return _env_path("SPINDLE_ADOPTION_RECEIPTS_DIR", spindle_home() / "adoptions")


def adoption_plans_dir() -> Path:
    """Content-addressed adoption and maintenance mutation plans."""
    return _env_path("SPINDLE_ADOPTION_PLANS_DIR", spindle_home() / "adoption-plans")


def maintenance_events_dir() -> Path:
    """Immutable adoption, update, disable, rollback, and retirement events."""
    return _env_path(
        "SPINDLE_MAINTENANCE_EVENTS_DIR", spindle_home() / "maintenance-events"
    )


def maintenance_index_file() -> Path:
    """Current lifecycle status index; historical facts remain immutable."""
    return _env_path(
        "SPINDLE_MAINTENANCE_INDEX_FILE", spindle_home() / "maintenance.json"
    )


def adapter_certifications_dir() -> Path:
    """Evidence-backed capability matrices for exact harness builds."""
    return _env_path(
        "SPINDLE_ADAPTER_CERTIFICATIONS_DIR",
        spindle_home() / "adapter-certifications",
    )


def hardening_receipts_dir() -> Path:
    """Immutable recovery, migration, and cache-custody decisions."""
    return _env_path(
        "SPINDLE_HARDENING_RECEIPTS_DIR",
        spindle_home() / "hardening-receipts",
    )


def surface_locks_dir() -> Path:
    """Resolved desired state for individual surface/harness coordinates."""
    return _env_path("SPINDLE_SURFACE_LOCKS_DIR", spindle_home() / "surface-locks")


def ownership_receipts_dir() -> Path:
    """Immutable receipts proving which projections Spindle created."""
    return _env_path(
        "SPINDLE_OWNERSHIP_RECEIPTS_DIR",
        spindle_home() / "ownership-receipts",
    )


def ownership_index_dir() -> Path:
    """Mutable indexes from current projection paths to ownership receipts."""
    return _env_path("SPINDLE_OWNERSHIP_INDEX_DIR", spindle_home() / "ownership")


def conflict_receipts_dir() -> Path:
    """Immutable explicit decisions for exact observed foreign conflicts."""
    return _env_path(
        "SPINDLE_CONFLICT_RECEIPTS_DIR", spindle_home() / "conflict-receipts"
    )


def lease_receipts_dir() -> Path:
    """Immutable temporary-authority grants keyed by exact lease content."""
    return _env_path("SPINDLE_LEASE_RECEIPTS_DIR", spindle_home() / "lease-receipts")


def lease_plans_dir() -> Path:
    """Content-addressed plans for lease creation and release."""
    return _env_path("SPINDLE_LEASE_PLANS_DIR", spindle_home() / "lease-plans")


def lease_events_dir() -> Path:
    """Immutable lifecycle receipts for release, expiry, and cleanup."""
    return _env_path("SPINDLE_LEASE_EVENTS_DIR", spindle_home() / "lease-events")


def trial_run_receipts_dir() -> Path:
    """Content-addressed outcomes for disposable trial harness runs."""
    return _env_path(
        "SPINDLE_TRIAL_RUN_RECEIPTS_DIR", spindle_home() / "trial-run-receipts"
    )


def startup_plans_dir() -> Path:
    """Immutable desired-versus-observed startup plans."""
    return _env_path("SPINDLE_STARTUP_PLANS_DIR", spindle_home() / "startup-plans")


def startup_receipts_dir() -> Path:
    """Content-addressed startup check/apply receipts."""
    return _env_path(
        "SPINDLE_STARTUP_RECEIPTS_DIR", spindle_home() / "startup-receipts"
    )


def startup_observations_file() -> Path:
    """Append-only chronology pointing to immutable startup receipts."""
    return _env_path(
        "SPINDLE_STARTUP_OBSERVATIONS_FILE",
        spindle_home() / "startup-observations.jsonl",
    )


def startup_locks_dir() -> Path:
    """Per-surface serialization locks for startup mutation."""
    return _env_path("SPINDLE_STARTUP_LOCKS_DIR", spindle_home() / "startup-locks")


def inventory_digest_cache_dir() -> Path:
    """Content digests keyed by path plus a cheap filesystem metadata fingerprint."""
    return _env_path(
        "SPINDLE_INVENTORY_DIGEST_CACHE_DIR",
        spindle_home() / "cache" / "inventory-digests",
    )


def hook_receipts_dir() -> Path:
    """Immutable receipts proving which native hook fragments Spindle installed."""
    return _env_path("SPINDLE_HOOK_RECEIPTS_DIR", spindle_home() / "hook-receipts")


def hook_index_file() -> Path:
    """Current target-file index for owned native hook fragments."""
    return _env_path("SPINDLE_HOOK_INDEX_FILE", spindle_home() / "hooks.json")


def chippability_ledger_path() -> Path:
    """Append-only record of chippability assessments (touchpoint C).

    One JSON line per assessed skill: ``{at, skill, package, score, hint}``.
    A local emit — it names strings and writes a file; it never imports chip
    tooling or requires a chip host."""
    return _env_path(
        "SPINDLE_CHIPPABILITY_LEDGER", spindle_home() / "chippability.jsonl"
    )


def candidates_dir() -> Path:
    """Draft candidate verdicts waiting for human review (output of scout cron pass)."""
    return spindle_home() / "verdicts" / "_candidates"


def task_queue_file() -> Path:
    """Reference task-sink queue used when no external task service is configured."""
    return _env_path("SPINDLE_TASK_QUEUE", spindle_home() / "tasks.jsonl")


def gate_queue_file() -> Path:
    """Reference decision-gate queue used when no external gate service is configured."""
    return _env_path("SPINDLE_GATE_QUEUE", spindle_home() / "gates.jsonl")
