"""Discover installed distributions that declare `[tool.spindle.distribution]`.

A distribution is any pip-installable package whose pyproject.toml contains a
`[tool.spindle.distribution]` table.  Discovery re-uses the same two-strategy
pyproject resolution already in `spindle.packages` (locate_file + direct_url.json).
"""

from __future__ import annotations

import importlib.metadata
import re
import tomllib
from pathlib import Path

from .models import DistributionMetadata
from .packages import _resolve_pyproject


def _parse_distribution_metadata(pyproject_path: Path) -> DistributionMetadata | None:
    """Parse `[tool.spindle.distribution]` out of a pyproject.toml. Returns None if absent."""
    try:
        data = tomllib.loads(pyproject_path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None

    tool = data.get("tool", {})
    spindle = tool.get("spindle", {}) if isinstance(tool, dict) else {}
    dist_cfg = spindle.get("distribution") if isinstance(spindle, dict) else None
    if not isinstance(dist_cfg, dict):
        return None

    project = data.get("project", {}) if isinstance(data.get("project"), dict) else {}
    name = project.get("name")
    version = project.get("version")
    if not name or not version:
        return None

    source_dir = (pyproject_path.parent / dist_cfg.get("source_dir", ".")).resolve()

    preempt_raw = dist_cfg.get("preempt_snippet")
    preempt_snippet = (source_dir / preempt_raw) if preempt_raw else None

    deps_raw = project.get("dependencies", []) or []
    packages = [re.split(r"[>=<!@\s]", dep)[0].strip() for dep in deps_raw if dep.strip()]

    return DistributionMetadata(
        name=str(name),
        version=str(version),
        display_name=str(dist_cfg.get("display_name", name)),
        description=str(dist_cfg.get("description", "")),
        source_dir=source_dir,
        preempt_snippet=preempt_snippet,
        home_url=dist_cfg.get("home_url") or None,
        packages=packages,
    )


def list_installed_distributions() -> list[DistributionMetadata]:
    """All installed distributions that declare `[tool.spindle.distribution]`."""
    results: list[DistributionMetadata] = []
    seen: set[str] = set()
    for dist in importlib.metadata.distributions():
        pyproject = _resolve_pyproject(dist)
        if pyproject is None:
            continue
        meta = _parse_distribution_metadata(pyproject)
        if meta is None or meta.name in seen:
            continue
        seen.add(meta.name)
        results.append(meta)
    return sorted(results, key=lambda m: m.name)


def read_distribution_metadata(name: str) -> DistributionMetadata | None:
    """Look up a single installed distribution by name."""
    try:
        dist = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return None
    pyproject = _resolve_pyproject(dist)
    if pyproject is None:
        return None
    return _parse_distribution_metadata(pyproject)


def distribution_source_dir(name: str) -> Path | None:
    """Absolute resolved source_dir for an installed distribution, or None."""
    meta = read_distribution_metadata(name)
    return meta.source_dir if meta is not None else None
