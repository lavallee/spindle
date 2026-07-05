"""Materialize a resolved Composition into a surface's harness-native skills dir.

This is the per-surface, *subset* materializer (eng-review #1: NOT
``skills.install_skills``, which symlinks every skill of a distribution into one
global dir). It symlinks exactly the composition's skills into the repo-local,
per-harness skills directory (D8) — `<repo>/.claude/skills` for claude — so
composition is genuinely per-surface and the harness's own project-skill
discovery finds them. It stays orthogonal to the global install flow.

Safety: it only ever removes symlinks it is told it previously owned (``previous``
= the prior binding's skill names). It never deletes real files or symlinks it
doesn't recognize, so a hand-added project skill is safe.
"""

from __future__ import annotations

from pathlib import Path

from .composition import Composition

# Where each harness discovers project-local skills.
HARNESS_SUBDIR = {
    "claude": ".claude/skills",
    "codex": ".codex/skills",
    "pi": ".pi/skills",
}


def target_dir(repo_path: str | Path, harness: str) -> Path:
    sub = HARNESS_SUBDIR.get(harness, f".{harness}/skills")
    return Path(repo_path) / sub


def materialize(
    comp: Composition,
    repo_path: str | Path,
    harness: str,
    *,
    previous: set[str] | None = None,
    dry_run: bool = False,
) -> list[tuple[str, str]]:
    """Symlink the composition's skills into the surface dir; reconcile against prior.

    Returns (skill_name, action) where action is one of: ``linked`` (new),
    ``updated`` (retargeted), ``kept`` (already correct), ``removed`` (was in
    ``previous``, no longer wanted), ``skipped:no-source`` (no source_dir),
    ``skipped:not-a-symlink`` (a real file is in the way — left untouched).
    """
    tdir = target_dir(repo_path, harness)
    wanted = {s.name: s for s in comp.skills if s.source_dir}
    results: list[tuple[str, str]] = []

    if not dry_run:
        tdir.mkdir(parents=True, exist_ok=True)

    for name, s in sorted(wanted.items()):
        link = tdir / name
        src = Path(s.source_dir)
        if link.is_symlink():
            if link.resolve() == src.resolve():
                results.append((name, "kept"))
                continue
            if not dry_run:
                link.unlink()
                link.symlink_to(src)
            results.append((name, "updated"))
        elif link.exists():
            results.append((name, "skipped:not-a-symlink"))
        else:
            if not dry_run:
                link.symlink_to(src)
            results.append((name, "linked"))

    for s in comp.skills:
        if not s.source_dir:
            results.append((s.name, "skipped:no-source"))

    # Reconcile: remove only symlinks we previously owned and no longer want.
    for name in sorted((previous or set()) - set(wanted)):
        link = tdir / name
        if link.is_symlink():
            if not dry_run:
                link.unlink()
            results.append((name, "removed"))

    return results
