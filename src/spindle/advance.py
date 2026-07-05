"""The advance team — precompute compositions across surfaces, ahead of time.

The warm-cache tier of the two-tier delivery model (concept §6b): rather than wait
for a surface to ask, the advance team binds every known surface on a schedule so
the common case is already composed and coherent when the surface loads. It is
just the binder run in a loop over the factory's surfaces — the same
select→resolve→render→lint→materialize→record pipeline, applied proactively.

Surfaces are read from ``<source_dir>/advance/surfaces.toml`` or a TOML project
registry. App-class clusters are derived fresh per repo at precompute time, so a
repo that changed shape gets re-clustered on the next run.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from . import active as active_mod
from . import appclass as appclass_mod
from . import binder as binder_mod
from .channels import Surface


@dataclass(frozen=True)
class Target:
    """A surface to precompute: a repo on disk under a harness + autonomy mode."""

    name: str
    path: str
    harness: str = "claude"
    autonomy_mode: str = "deterministic"


def target_to_surface(target: Target) -> Surface:
    """Build a Surface, deriving app-class clusters from the repo as it is now."""
    sig = appclass_mod.signal_from_repo(target.path)
    cls = appclass_mod.classify(sig)
    return Surface(
        name=target.name,
        harness=target.harness,
        autonomy_mode=target.autonomy_mode,
        clusters=(cls.cluster_key(),),
    )


def load_targets(source_dir: Path | None = None) -> list[Target]:
    """Read ``<source_dir>/advance/surfaces.toml`` → list of Targets."""
    root = Path(source_dir) if source_dir is not None else active_mod.source_dir()
    manifest = root / "advance" / "surfaces.toml"
    if not manifest.exists():
        return []
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    out: list[Target] = []
    for s in data.get("surface", []):
        out.append(Target(
            name=str(s["name"]),
            path=str(s["path"]),
            harness=str(s.get("harness", "claude")),
            autonomy_mode=str(s.get("autonomy", "deterministic")),
        ))
    return out


def default_repo_root() -> Path:
    """Where local checkouts live for registry enumeration."""
    env = os.environ.get("SPINDLE_PROJECTS_ROOT")
    if env:
        return Path(env).expanduser()
    for c in (Path.home() / "projects", Path.home() / "Projects"):
        if c.is_dir():
            return c
    return Path.home() / "projects"


def targets_from_registry(projects_dir: Path | None = None, *,
                          repo_root: Path | None = None) -> list[Target]:
    """Enumerate advance-team targets from a TOML project registry.

    Reads ``<projects_dir>/*.toml`` (one record per project). A project yields
    one Target per declared harness, but only when it is ``active``, lists
    harnesses, and has a local checkout at ``repo_root/<name>``.

    ``projects_dir`` defaults to ``$SPINDLE_PROJECTS_DIR``; returns [] if unset
    or missing.
    """
    if projects_dir is None:
        env = os.environ.get("SPINDLE_PROJECTS_DIR")
        if not env:
            return []
        projects_dir = Path(env).expanduser()
    projects_dir = Path(projects_dir)
    if not projects_dir.is_dir():
        return []
    root = Path(repo_root) if repo_root is not None else default_repo_root()

    targets: list[Target] = []
    for toml_path in sorted(projects_dir.glob("*.toml")):
        try:
            data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if data.get("status", "active") != "active":
            continue
        harnesses = data.get("harnesses") or []
        name = data.get("name") or toml_path.stem
        checkout = root / name
        if not harnesses or not checkout.is_dir():
            continue
        for harness in harnesses:
            targets.append(Target(name=name, path=str(checkout), harness=str(harness)))
    return targets


def precompute(targets: list[Target], provider, doctrine, *,
               render=None, force: bool = False, dry_run: bool = False
               ) -> list[tuple[str, "binder_mod.BindResult"]]:
    """Bind every target ahead of time. Returns (target name, BindResult) per surface.

    A failing surface does not stop the run — its problems are in its BindResult so
    the whole factory still gets precomputed and the failures surface together.
    """
    results: list[tuple[str, binder_mod.BindResult]] = []
    for target in targets:
        surface = target_to_surface(target)
        kwargs = {"force": force, "dry_run": dry_run}
        if render is not None:
            kwargs["render"] = render
        result = binder_mod.bind(surface, target.path, provider, doctrine, **kwargs)
        results.append((target.name, result))
    return results
