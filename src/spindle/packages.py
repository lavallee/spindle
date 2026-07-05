"""Discover installed packages that declare `[tool.spindle.package]`.

Discovery walks `importlib.metadata.distributions()` and tries two
strategies to find each distribution's `pyproject.toml`:

  1. `Distribution.locate_file("pyproject.toml")` — works for wheel
     installs where pyproject ships next to the package.
  2. `direct_url.json` (PEP 610) — for editable installs the URL
     points at the original source dir, where `pyproject.toml` lives.

Editable installs in a monorepo subdir only resolve via strategy 2, so both
are required.
"""

from __future__ import annotations

import datetime
import importlib.metadata
import json
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlparse

from .models import PackageMetadata, Source


def _resolve_pyproject(dist: importlib.metadata.Distribution) -> Path | None:
    """Return the source pyproject.toml for an installed distribution, or None."""
    candidate = dist.locate_file("pyproject.toml")
    if candidate is not None and Path(candidate).is_file():
        return Path(candidate)

    raw = dist.read_text("direct_url.json")
    if not raw:
        return None
    try:
        info = json.loads(raw)
    except json.JSONDecodeError:
        return None
    url = info.get("url", "")
    if not url.startswith("file://"):
        return None
    source_dir = Path(unquote(urlparse(url).path))
    pyproject = source_dir / "pyproject.toml"
    return pyproject if pyproject.is_file() else None


def _parse_source(raw: dict) -> Source:
    transposed = raw.get("transposed_at", "")
    if isinstance(transposed, datetime.date):
        date = transposed
    else:
        date = datetime.date.fromisoformat(str(transposed)) if transposed else datetime.date.min
    return Source(
        peer=str(raw.get("peer", "")),
        url=str(raw.get("url", "")),
        transposed_at=date,
        notes=str(raw.get("notes", "")),
    )


def _parse_package_metadata(pyproject_path: Path) -> PackageMetadata | None:
    """Parse `[tool.spindle.package]` out of a pyproject.toml. Returns None if absent or malformed."""
    try:
        data = tomllib.loads(pyproject_path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None
    tool = data.get("tool", {})
    spindle = tool.get("spindle", {}) if isinstance(tool, dict) else {}
    pkg = spindle.get("package") if isinstance(spindle, dict) else None
    if not isinstance(pkg, dict):
        return None

    project = data.get("project", {}) if isinstance(data.get("project"), dict) else {}
    name = pkg.get("name") or project.get("name")
    version = pkg.get("version") or project.get("version")
    if not name or not version:
        return None

    sources_raw = pkg.get("sources", []) or []
    sources = [_parse_source(s) for s in sources_raw if isinstance(s, dict)]

    return PackageMetadata(
        name=str(name),
        version=str(version),
        distribution=pkg.get("distribution"),
        skills=list(pkg.get("skills", []) or []),
        capabilities=list(pkg.get("capabilities", []) or []),
        sources=sources,
        package_dir=pyproject_path.parent,
    )


def list_installed_packages() -> list[PackageMetadata]:
    """All installed distributions that declare `[tool.spindle.package]`."""
    results: list[PackageMetadata] = []
    seen: set[str] = set()
    for dist in importlib.metadata.distributions():
        pyproject = _resolve_pyproject(dist)
        if pyproject is None:
            continue
        meta = _parse_package_metadata(pyproject)
        if meta is None or meta.name in seen:
            continue
        seen.add(meta.name)
        results.append(meta)
    return sorted(results, key=lambda m: m.name)


def read_package_metadata(name: str) -> PackageMetadata | None:
    """Look up a single installed package by name."""
    try:
        dist = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return None
    pyproject = _resolve_pyproject(dist)
    if pyproject is None:
        return None
    return _parse_package_metadata(pyproject)


def package_skill_dirs(name: str) -> list[Path]:
    """Absolute directories (each containing SKILL.md) for skills shipped by `name`."""
    meta = read_package_metadata(name)
    if meta is None:
        return []
    importable_root = meta.package_dir / meta.name.replace("-", "_")
    dirs: list[Path] = []
    for skill in meta.skills:
        candidates = [
            importable_root / "skills" / skill,
            meta.package_dir / skill,
            meta.package_dir / "skills" / skill,
        ]
        for candidate in candidates:
            if (candidate / "SKILL.md").is_file():
                dirs.append(candidate)
                break
    return dirs
