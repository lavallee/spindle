"""App-type classification for a repo.

Spindle clusters projects by characteristic (front-end? network service? uses
LLMs directly? what language?) to decide which skill composition each surface
benefits from. The classifier accepts local repo manifests directly and can also
adapt a generic derived-project manifest from a registry.

Structure:
  - ``classify(signal) -> AppClass``         — pure; the thing that would move.
  - ``signal_from_repo(path, ...)``          — I/O: read a checkout's manifests.
  - ``signal_from_derive(derive, ...)``      — adapter over a derived manifest.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

# Evidence sets — dependency names (normalized) that signal a characteristic.
_LLM_DEPS = frozenset({
    "anthropic", "openai", "somm", "langchain", "langchain-core", "litellm",
    "google-generativeai", "google-genai", "cohere", "mistralai", "ollama",
})
_FRONTEND_DEPS = frozenset({
    "react", "react-dom", "next", "vite", "svelte", "vue", "@angular/core",
    "solid-js", "astro", "remix",
})
_SERVICE_DEPS = frozenset({
    "fastapi", "flask", "starlette", "uvicorn", "django", "express",
    "aiohttp", "hypercorn", "gunicorn",
})
_MCP_DEPS = frozenset({"mcp", "modelcontextprotocol", "fastmcp"})


@dataclass(frozen=True)
class RepoSignal:
    """Raw, language-agnostic signal about a repo. The classifier's only input."""

    name: str = ""
    language: str = "unknown"          # python | javascript | typescript | unknown
    deps: frozenset[str] = field(default_factory=frozenset)
    files: frozenset[str] = field(default_factory=frozenset)  # notable basenames present
    registry_kind: str | None = None   # registry kind, if known (library/service/...)


@dataclass(frozen=True)
class AppClass:
    """The derived characterization. ``tags`` is the stable cluster input."""

    name: str
    language: str
    uses_llms: bool
    network_service: bool
    frontend: bool
    agent_instrumented: bool
    is_mcp: bool
    registry_kind: str | None = None

    @property
    def tags(self) -> list[str]:
        out = [f"lang:{self.language}"]
        if self.registry_kind:
            out.append(f"kind:{self.registry_kind}")
        if self.uses_llms:
            out.append("uses-llms")
        if self.network_service:
            out.append("network-service")
        if self.frontend:
            out.append("frontend")
        if self.agent_instrumented:
            out.append("agent-instrumented")
        if self.is_mcp:
            out.append("mcp")
        return sorted(out)

    def cluster_key(self) -> str:
        """Stable app-class key for grouping repos with the same characteristics."""
        return "|".join(self.tags)


# ---- the pure classifier ------------------------------------------------

def classify(signal: RepoSignal) -> AppClass:
    deps = signal.deps
    files = {f.lower() for f in signal.files}
    is_mcp = (
        signal.name.endswith("-mcp")
        or bool(deps & _MCP_DEPS)
    )
    return AppClass(
        name=signal.name,
        language=signal.language,
        uses_llms=bool(deps & _LLM_DEPS) or ".somm" in files,
        network_service=bool(deps & _SERVICE_DEPS) or "dockerfile" in files
        or signal.registry_kind == "service",
        frontend=bool(deps & _FRONTEND_DEPS),
        agent_instrumented="claude.md" in files or "agents.md" in files,
        is_mcp=is_mcp,
        registry_kind=signal.registry_kind,
    )


# ---- I/O: build a RepoSignal --------------------------------------------

def _norm_dep(raw: str) -> str:
    """'anthropic>=0.40' / 'React' → 'anthropic' / 'react' (name token, lowercased)."""
    name = raw.strip().lower()
    for sep in (" ", ">", "<", "=", "~", "!", "[", ";", "@"):
        # keep scoped npm names like @angular/core intact: only split @ when not leading
        if sep == "@" and name.startswith("@"):
            continue
        name = name.split(sep, 1)[0]
    return name.strip()


def _read_pyproject_deps(path: Path) -> set[str]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return set()
    deps: set[str] = set()
    proj = data.get("project", {})
    for d in proj.get("dependencies", []) or []:
        deps.add(_norm_dep(str(d)))
    for group in (proj.get("optional-dependencies", {}) or {}).values():
        for d in group or []:
            deps.add(_norm_dep(str(d)))
    return {d for d in deps if d}


def _read_package_json_deps(path: Path) -> tuple[set[str], bool]:
    """Return (deps, has_typescript)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set(), False
    deps: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        for name in (data.get(key) or {}):
            deps.add(_norm_dep(str(name)))
    return {d for d in deps if d}, "typescript" in deps


_NOTABLE_FILES = ("Dockerfile", "CLAUDE.md", "AGENTS.md", "package.json", "pyproject.toml")


def signal_from_repo(repo_path: Path, *, name: str | None = None,
                     registry_kind: str | None = None) -> RepoSignal:
    """Read a local checkout into a RepoSignal (Path-B primary path)."""
    repo_path = Path(repo_path)
    name = name or repo_path.name
    files: set[str] = set()
    for f in _NOTABLE_FILES:
        if (repo_path / f).exists():
            files.add(f)
    if (repo_path / ".somm").exists():
        files.add(".somm")

    deps: set[str] = set()
    language = "unknown"
    pyproject = repo_path / "pyproject.toml"
    pkg = repo_path / "package.json"
    if pyproject.exists():
        deps |= _read_pyproject_deps(pyproject)
        language = "python"
    if pkg.exists():
        js_deps, has_ts = _read_package_json_deps(pkg)
        deps |= js_deps
        # Don't clobber python for mixed repos; only set if not already python.
        if language == "unknown":
            language = "typescript" if has_ts else "javascript"

    return RepoSignal(
        name=name,
        language=language,
        deps=frozenset(deps),
        files=frozenset(files),
        registry_kind=registry_kind,
    )


def signal_from_derive(derive: dict, *, deps: set[str] | None = None,
                       registry_kind: str | None = None) -> RepoSignal:
    """Adapt a derived project manifest into a RepoSignal.

    derive shape: ``{repo_path, git: {...}, artifacts: [{label, present, path}]}``.
    The manifest gives presence of governance/build artifacts but **not**
    dependency contents — so callers that need uses_llms/frontend/etc. pass
    ``deps`` (read from the checkout), or use ``signal_from_repo`` directly. This
    adapter is the seam between an external registry and Spindle's classifier.
    """
    present = {
        a.get("label"): a
        for a in derive.get("artifacts", [])
        if a.get("present")
    }
    files: set[str] = set()
    if "agents" in present:
        # Derived manifests can collapse CLAUDE.md/AGENTS.md to the 'agents' label; the path
        # tells which file it found.
        p = (present["agents"].get("path") or "").lower()
        files.add("agents.md" if "agents" in p else "claude.md")
    language = "unknown"
    if "build" in present:
        p = (present["build"].get("path") or "").lower()
        if p.endswith("pyproject.toml"):
            language = "python"
            files.add("pyproject.toml")
        elif p.endswith("package.json"):
            language = "javascript"
            files.add("package.json")

    name = Path(derive.get("repo_path", "")).name
    return RepoSignal(
        name=name,
        language=language,
        deps=frozenset(deps or set()),
        files=frozenset(files),
        registry_kind=registry_kind,
    )
