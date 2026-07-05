"""Thin subprocess wrapper around uv pip install / uninstall / lock.

All subprocess calls use argv lists — never shell=True. Raises ResolverError
(carrying stderr) on non-zero exit so callers can surface the failure cleanly.

Source format accepted by uv_install:
  - Local path:  ./some/dir  or  /abs/path  (must start with . or /)
  - Git URL:     git+https://...  or  git+ssh://...
  - PyPI name:   anything else (e.g. "sample-planning==0.1.0")
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


class ResolverError(Exception):
    """Raised when a uv subprocess exits non-zero."""

    def __init__(self, message: str, stderr: str = "") -> None:
        super().__init__(message)
        self.stderr = stderr


_GIT_URL_RE = re.compile(r"^git\+")
_PYPI_NAME_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?([=<>!~].+)?$")


def _classify_source(source: str) -> str:
    """Return 'local', 'git', or 'pypi' for a given source string."""
    if source.startswith("./") or source.startswith("/") or source.startswith("../"):
        return "local"
    if _GIT_URL_RE.match(source):
        return "git"
    if _PYPI_NAME_RE.match(source):
        return "pypi"
    raise ResolverError(
        f"Cannot determine source type for {source!r}. "
        "Expected a local path (./… or /…), a git URL (git+…), or a PyPI package name."
    )


def _run(argv: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode != 0:
        raise ResolverError(
            f"{argv[0]} exited with code {result.returncode}",
            stderr=result.stderr,
        )
    return result


def uv_install(source: str) -> tuple[str, str]:
    """Install a package via uv pip install.

    Local paths are installed editably (-e). Returns (stdout, stderr).
    Raises ResolverError on failure.
    """
    kind = _classify_source(source)
    if kind == "local":
        argv = ["uv", "pip", "install", "-e", source]
    else:
        argv = ["uv", "pip", "install", source]
    result = _run(argv)
    return result.stdout, result.stderr


def uv_uninstall(name: str) -> tuple[str, str]:
    """Uninstall a package by name via uv pip uninstall -y.

    Returns (stdout, stderr). Raises ResolverError on failure.
    """
    if not _PYPI_NAME_RE.match(name):
        raise ResolverError(
            f"Invalid package name {name!r}. Expected a PyPI-style name."
        )
    result = _run(["uv", "pip", "uninstall", name])
    return result.stdout, result.stderr


def uv_lock(dist_dir: Path) -> tuple[str, str]:
    """Run uv lock in a distribution directory.

    Returns (stdout, stderr). Raises ResolverError on failure.
    """
    result = _run(["uv", "lock"], cwd=dist_dir)
    return result.stdout, result.stderr
