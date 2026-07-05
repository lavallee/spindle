"""Aggregate capability metadata across installed spindle packages.

Pure read — no datastore, no side effects.  All data comes from
`[tool.spindle.package].capabilities` and `[[tool.spindle.package.sources]]`
in each installed package's pyproject.toml.
"""

from __future__ import annotations

import dataclasses

from .packages import list_installed_packages
from .models import Source


def list_capabilities() -> dict[str, list[str]]:
    """Return capability → [package-name, ...] for every installed package.

    If no packages declare capabilities, returns an empty dict.
    """
    result: dict[str, list[str]] = {}
    for pkg in list_installed_packages():
        for cap in pkg.capabilities:
            result.setdefault(cap, []).append(pkg.name)
    return result


def show_capability(name: str) -> dict:
    """Return a detail dict for one capability.

    Keys:
      name        — the capability string
      packages    — list of package names that provide it
      sources     — list of source dicts (from any providing package)

    Returns an empty-packages / empty-sources dict if the capability is
    not found; never raises.
    """
    packages: list[str] = []
    sources: list[dict] = []

    for pkg in list_installed_packages():
        if name not in pkg.capabilities:
            continue
        packages.append(pkg.name)
        for src in pkg.sources:
            sources.append(dataclasses.asdict(src))

    return {"name": name, "packages": packages, "sources": sources}
