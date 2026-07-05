"""Platform data shapes — pure dataclasses, no I/O.

All classes here are value types consumed by packages, distributions,
skills, and ledger modules. Nothing in this module touches the filesystem,
network, or subprocess.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Source:
    """Provenance record for a skill or capability."""

    peer: str
    url: str
    transposed_at: datetime.date
    notes: str = ""


@dataclass(frozen=True)
class SkillSpec:
    """A single skill discovered from an installed package."""

    name: str       # frontmatter `name:` field
    package: str    # which package ships it
    skill_dir: Path  # absolute path to the directory containing SKILL.md


@dataclass
class PackageMetadata:
    """Mirrors [tool.spindle.package] from a package's pyproject.toml."""

    name: str
    version: str
    distribution: str | None  # owning distribution name; None for standalone packages
    skills: list[str]         # skill subdirectory names shipped by this package
    capabilities: list[str]   # capability tags
    sources: list[Source]     # provenance records
    package_dir: Path         # resolved installation source directory


@dataclass
class DistributionMetadata:
    """Mirrors [tool.spindle.distribution] + [project] from a distribution's pyproject.toml."""

    name: str
    version: str
    display_name: str
    description: str
    source_dir: Path              # resolved absolute path (peers/, verdicts/, scout/ live here)
    preempt_snippet: Path | None  # preempt.md path relative to source_dir; None if absent
    home_url: str | None
    packages: list[str]           # pinned package deps from [project].dependencies


@dataclass
class LedgerEvent:
    """A single append-only record written to events.jsonl."""

    ts: str      # ISO 8601 UTC timestamp
    machine: str  # stable machine UUID
    kind: str    # "dist_install" | "dist_uninstall" | "skill_link" | "skill_unlink" | "preempt" | "rate"
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class InstalledDistributionState:
    """Per-distribution slice within MaterializedState."""

    version: str
    installed_at: str        # ISO 8601 timestamp of the install event
    packages: dict[str, str]  # package name → version
    skills_linked: list[str]  # skill names currently symlinked under ~/.claude/skills/


@dataclass
class MaterializedState:
    """Fold of events.jsonl; persisted as state.json and rebuilt on demand."""

    machine_id: str
    rebuilt_at: str   # ISO 8601 timestamp of last rebuild
    distributions: dict[str, InstalledDistributionState] = field(default_factory=dict)
    preempted_by: str | None = None
