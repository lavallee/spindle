"""Materialize a resolved Composition into a surface's harness-native skills dir.

This is the per-surface, *subset* materializer (eng-review #1: NOT
``skills.install_skills``, which symlinks every skill of a distribution into one
global dir). It symlinks exactly the composition's skills into the repo-local,
per-harness skills directory (D8) — `<repo>/.claude/skills` for claude — so
composition is genuinely per-surface and the harness's own project-skill
discovery finds them. It stays orthogonal to the global install flow.

Harnesses without repo-local discovery (hermes) instead get a dedicated,
spindle-owned directory inside their global skills tree — same symlink and
reconcile semantics, just a global target (see ``GLOBAL_HARNESS_DIR``).

Safety: it only ever removes symlinks it is told it previously owned (``previous``
= the prior binding's skill names). It never deletes real files or symlinks it
doesn't recognize, so a hand-added project skill is safe.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import paths as paths_mod
from .composition import ComposedSkill, Composition
from .lifecycle import (
    OwnershipRecord,
    OwnershipStore,
    content_id,
    digest_path,
    surface_id,
)

# Where each harness discovers project-local skills. Codex follows the Agent
# Skills standard and scans `.agents/skills` from CWD to the repository root.
HARNESS_SUBDIR = {
    "claude": ".claude/skills",
    "codex": ".agents/skills",
    "pi": ".pi/skills",
}

# Harnesses that only discover skills from a single global directory. Hermes
# walks ~/.hermes/skills recursively (following symlinks) and ignores
# repo-local .hermes dirs, so its bindings land in a dedicated, spindle-owned
# category dir there (see ``paths.hermes_skills_dir``). The repo argument still
# names the binding *surface*; only the materialization target is global.
GLOBAL_HARNESS_DIR = {
    "hermes": paths_mod.hermes_skills_dir,
}


def target_dir(repo_path: str | Path, harness: str) -> Path:
    global_dir = GLOBAL_HARNESS_DIR.get(harness)
    if global_dir is not None:
        return global_dir().expanduser()
    sub = HARNESS_SUBDIR.get(harness, f".{harness}/skills")
    return Path(repo_path) / sub


def materialize(
    comp: Composition,
    repo_path: str | Path,
    harness: str,
    *,
    previous: set[str] | None = None,
    dry_run: bool = False,
    ownership_store: OwnershipStore | None = None,
    creation_receipt_id: str | None = None,
    package_digests: dict[str, str] | None = None,
) -> list[tuple[str, str]]:
    """Symlink the composition's skills into the surface dir; reconcile against prior.

    Returns (skill_name, action) where action is one of: ``linked`` (new),
    ``updated`` (retargeted), ``kept`` (already correct), ``removed`` (was in
    ``previous``, no longer wanted), ``skipped:no-source`` (no source_dir),
    ``skipped:not-a-symlink`` (a real file is in the way — left untouched).
    """
    repo = Path(repo_path).resolve()
    tdir = target_dir(repo, harness)
    wanted = {s.name: s for s in comp.skills if s.source_dir}
    results: list[tuple[str, str]] = []
    store = ownership_store or OwnershipStore()
    sid = surface_id(repo, harness)
    owned = store.records(sid)
    receipt_id = creation_receipt_id or content_id(
        {
            "surface_id": sid,
            "skills": [
                {
                    "name": skill.name,
                    "source": str(Path(skill.source_dir).resolve()),
                    "digest": digest_path(skill.source_dir),
                }
                for skill in sorted(wanted.values(), key=lambda item: item.name)
            ],
        }
    )

    plans: list[tuple[str, str, Path, Path, ComposedSkill | None]] = []
    conflicts = False
    for name, skill in sorted(wanted.items()):
        link = tdir / name
        src = Path(skill.source_dir).resolve()
        record = owned.get(str(link.absolute()))
        if link.is_symlink():
            current = (link.parent / os.readlink(link)).resolve(strict=False)
            if current == src:
                if record is not None and record.matches_symlink(link):
                    action = "kept"
                else:
                    action = "skipped:unowned-symlink"
                    conflicts = True
            elif record is not None and record.matches_symlink(link):
                action = "updated"
            else:
                action = "skipped:foreign-symlink"
                conflicts = True
        elif link.exists():
            action = "skipped:not-a-symlink"
            conflicts = True
        else:
            action = "linked"
        plans.append((name, action, link, src, skill))

    for skill in comp.skills:
        if not skill.source_dir:
            plans.append(
                (skill.name, "skipped:no-source", tdir / skill.name, Path(), None)
            )
            conflicts = True

    previous_filter = previous if previous is not None else None
    removals: list[tuple[str, str, Path, OwnershipRecord]] = []
    for projection_path, record in sorted(owned.items()):
        if record.skill in wanted:
            continue
        if previous_filter is not None and record.skill not in previous_filter:
            continue
        link = Path(projection_path)
        if not link.exists() and not link.is_symlink():
            action = "forgot:missing"
        elif record.matches_symlink(link):
            action = "removed"
        else:
            action = "skipped:ownership-mismatch"
            conflicts = True
        removals.append((record.skill, action, link, record))

    # Preflight all desired targets before mutation so one foreign collision
    # cannot leave a partially materialized blend.
    if conflicts:
        return [
            *((name, action) for name, action, *_ in plans),
            *((name, action) for name, action, *_ in removals),
        ]

    if dry_run:
        return [
            *((name, action) for name, action, *_ in plans),
            *((name, action) for name, action, *_ in removals),
        ]

    tdir.mkdir(parents=True, exist_ok=True)

    for name, action, link, src, skill in plans:
        if skill is None:
            continue
        if action == "updated":
            if link.is_symlink():
                link.unlink()
            link.symlink_to(src)
        elif action == "linked":
            link.symlink_to(src)
        source_digest = digest_path(src)
        package_digest = (package_digests or {}).get(name, source_digest)
        store.record(
            OwnershipRecord(
                surface_id=sid,
                surface_name=comp.surface,
                harness=harness,
                skill=name,
                projection_path=str(link.absolute()),
                source_path=str(src),
                source_digest=source_digest,
                package_digest=package_digest,
                creation_receipt_id=receipt_id,
            )
        )
        results.append((name, action))

    # Reconcile only exact projections proven by immutable ownership receipts.
    for name, action, link, record in removals:
        if action == "forgot:missing":
            store.forget(sid, link, record.ownership_id)
        elif action == "removed":
            link.unlink()
            store.forget(sid, link, record.ownership_id)
        results.append((name, action))

    return results
