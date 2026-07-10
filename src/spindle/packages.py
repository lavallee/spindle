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


DATA_FILE = "spindle-package.toml"


def _data_file_metadata(dist: importlib.metadata.Distribution) -> PackageMetadata | None:
    """Wheel-friendly discovery: a `<module>/spindle-package.toml` data file.

    Wheels do not ship pyproject.toml, so packages installed from an index
    (PyPI) are invisible to the pyproject strategies. A package can instead
    ship the same `[tool.spindle.package]` table as a data file inside its
    importable module — it travels in every wheel/sdist with no site-packages
    pollution. name/version fall back to the distribution's own metadata.
    """
    files = dist.files or []
    for f in files:
        parts = f.parts
        if len(parts) == 2 and parts[1] == DATA_FILE:
            located = dist.locate_file(f)
            path = Path(str(located))
            if not path.is_file():
                continue
            try:
                data = tomllib.loads(path.read_text())
            except (OSError, tomllib.TOMLDecodeError):
                return None
            tool = data.get("tool", {})
            spindle = tool.get("spindle", {}) if isinstance(tool, dict) else {}
            pkg = spindle.get("package") if isinstance(spindle, dict) else None
            if not isinstance(pkg, dict):
                return None
            name = pkg.get("name") or dist.metadata["Name"]
            version = pkg.get("version") or dist.version
            if not name or not version:
                return None
            sources_raw = pkg.get("sources", []) or []
            return PackageMetadata(
                name=str(name),
                version=str(version),
                distribution=pkg.get("distribution"),
                skills=list(pkg.get("skills", []) or []),
                capabilities=list(pkg.get("capabilities", []) or []),
                sources=[_parse_source(s) for s in sources_raw if isinstance(s, dict)],
                # parent of the module dir (site-packages), so the standard
                # <package_dir>/<module>/skills/<skill> candidate resolves.
                package_dir=path.parent.parent,
            )
    return None


def list_installed_packages() -> list[PackageMetadata]:
    """All installed distributions that declare `[tool.spindle.package]`
    (via pyproject.toml for source/editable installs, or a bundled
    spindle-package.toml data file for wheel installs)."""
    results: list[PackageMetadata] = []
    seen: set[str] = set()
    for dist in importlib.metadata.distributions():
        meta = None
        pyproject = _resolve_pyproject(dist)
        if pyproject is not None:
            meta = _parse_package_metadata(pyproject)
        if meta is None:
            meta = _data_file_metadata(dist)
        if meta is None or meta.name in seen:
            continue
        seen.add(meta.name)
        results.append(meta)
    return sorted(results, key=lambda m: m.name)


def read_package_metadata(name: str) -> PackageMetadata | None:
    """Look up a single installed package by its spindle-package name.

    The spindle-package name (`[tool.spindle.package] name`) need not equal
    the pip distribution name — e.g. the `flip` spindle package ships in the
    `flip-notebook` distribution because the bare name was taken on PyPI. Try
    the fast path (distribution named `name`) first, then fall back to
    scanning every installed distribution for a matching spindle name.
    """
    try:
        dist = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        dist = None
    if dist is not None:
        pyproject = _resolve_pyproject(dist)
        if pyproject is not None:
            meta = _parse_package_metadata(pyproject)
            if meta is not None and meta.name == name:
                return meta
    for meta in list_installed_packages():
        if meta.name == name:
            return meta
    return None


def package_skill_dirs(name: str) -> list[Path]:
    """Absolute directories (each containing SKILL.md) for skills shipped by `name`.

    Candidate layouts, in order: flat module (`<pkg>/skills/<skill>`),
    src layout (`src/<pkg>/skills/<skill>`), and the two legacy spots at the
    project root.
    """
    meta = read_package_metadata(name)
    if meta is None:
        return []
    module = meta.name.replace("-", "_")
    dirs: list[Path] = []
    for skill in meta.skills:
        candidates = [
            meta.package_dir / module / "skills" / skill,
            meta.package_dir / "src" / module / "skills" / skill,
            meta.package_dir / skill,
            meta.package_dir / "skills" / skill,
        ]
        for candidate in candidates:
            if (candidate / "SKILL.md").is_file():
                dirs.append(candidate)
                break
    return dirs
