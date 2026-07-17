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
    return Path(os.environ.get("CLAUDE_SKILLS_DIR", str(Path.home() / ".claude" / "skills")))


def claude_md_path() -> Path:
    return Path(os.environ.get("CLAUDE_MD_PATH", str(Path.home() / ".claude" / "CLAUDE.md")))


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


def chippability_ledger_path() -> Path:
    """Append-only record of chippability assessments (touchpoint C).

    One JSON line per assessed skill: ``{at, skill, package, score, hint}``.
    A local emit — it names strings and writes a file; it never imports chip
    tooling or requires a chip host."""
    return _env_path("SPINDLE_CHIPPABILITY_LEDGER", spindle_home() / "chippability.jsonl")


def candidates_dir() -> Path:
    """Draft candidate verdicts waiting for human review (output of scout cron pass)."""
    return spindle_home() / "verdicts" / "_candidates"


def task_queue_file() -> Path:
    """Reference task-sink queue used when no external task service is configured."""
    return _env_path("SPINDLE_TASK_QUEUE", spindle_home() / "tasks.jsonl")


def gate_queue_file() -> Path:
    """Reference decision-gate queue used when no external gate service is configured."""
    return _env_path("SPINDLE_GATE_QUEUE", spindle_home() / "gates.jsonl")
