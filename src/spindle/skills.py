"""Install / uninstall spindle skills as symlinks under ~/.claude/skills/.

Skills are discovered through installed spindle packages
(`spindle.packages.package_skill_dirs`); the symlink name comes from the
SKILL.md frontmatter `name:` field, falling back to the on-disk
directory name when frontmatter is absent or unparseable.

Symlinks (not copies) so editing a skill in its source repo is live
immediately. Uninstall only removes symlinks whose targets resolve to
a skill_dir we currently discover; real directories or third-party
links are left alone.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import active as active_mod
from .ledger import log_event
from .models import SkillSpec
from .packages import list_installed_packages, package_skill_dirs
from .paths import claude_skills_dir


_NAME_LINE = re.compile(r"^name:\s*(.+?)\s*$")


def _read_frontmatter(skill_dir: Path) -> dict[str, str]:
    """Read YAML-like frontmatter from <skill_dir>/SKILL.md, return dict of key: value."""
    skill_md = skill_dir / "SKILL.md"
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    fm: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            fm[key.strip()] = val.strip().strip('"').strip("'")
    return fm


def _read_skill_name(skill_dir: Path) -> str | None:
    """Return the `name:` field from <skill_dir>/SKILL.md frontmatter, or None."""
    skill_md = skill_dir / "SKILL.md"
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    for line in text[3:end].splitlines():
        m = _NAME_LINE.match(line)
        if m:
            return m.group(1).strip().strip('"').strip("'") or None
    return None


def _get_legacy_alias_name(skill_name: str) -> str | None:
    """Optional prefix mapping for private layers that need transition aliases."""
    old_prefix = os.environ.get("SPINDLE_LEGACY_ALIAS_FROM", "")
    new_prefix = os.environ.get("SPINDLE_LEGACY_ALIAS_TO", "")
    if old_prefix and new_prefix and skill_name.startswith(old_prefix):
        return skill_name.replace(old_prefix, new_prefix, 1)
    return None


def _create_or_update_alias(
    alias_link: Path, target_link: Path, name: str, dry_run: bool, results: list[tuple[str, str]]
) -> None:
    """Point an alias symlink at the main skill symlink. Idempotent."""
    if alias_link.is_symlink():
        current = os.readlink(alias_link)
        if current == str(target_link):
            results.append((f"{name} (alias)", "skipped:already-current"))
            return
        if not dry_run:
            alias_link.unlink()
            alias_link.symlink_to(target_link)
        results.append((f"{name} (alias)", "updated"))
    elif alias_link.exists():
        results.append((f"{name} (alias)", "skipped:exists-not-spindle"))
    else:
        if not dry_run:
            alias_link.symlink_to(target_link)
        results.append((f"{name} (alias)", "installed"))


def prune_legacy_symlinks(*, dry_run: bool = False) -> list[tuple[str, str]]:
    """Remove dead spindle-* symlinks left over from the old <repo>/skills/spindle-* layout.

    Returns (name, action) tuples where action is one of:
      'pruned' | 'skipped:alive' | 'skipped:not-legacy'
    """
    skills_dir = claude_skills_dir()
    if not skills_dir.exists():
        return []
    try:
        legacy_base = str(active_mod.source_dir() / "skills" / "spindle-")
    except active_mod.ActiveDistributionError:
        return []
    results: list[tuple[str, str]] = []
    for link in sorted(skills_dir.glob("spindle-*")):
        if not link.is_symlink():
            continue
        if link.exists():
            results.append((link.name, "skipped:alive"))
            continue
        try:
            raw = os.readlink(link)
        except OSError:
            continue
        if not raw.startswith(legacy_base):
            results.append((link.name, "skipped:not-legacy"))
            continue
        if not dry_run:
            link.unlink()
        results.append((link.name, "pruned"))
    return results


def discover_skills(distribution: str | None = None) -> list[SkillSpec]:
    """Skills shipped by installed spindle packages, optionally filtered to one distribution."""
    specs: list[SkillSpec] = []
    seen: set[str] = set()
    for pkg in list_installed_packages():
        if distribution is not None and pkg.distribution != distribution:
            continue
        for skill_dir in package_skill_dirs(pkg.name):
            name = _read_skill_name(skill_dir) or skill_dir.name
            if name in seen:
                continue
            seen.add(name)
            specs.append(SkillSpec(name=name, package=pkg.name, skill_dir=skill_dir))
    return sorted(specs, key=lambda s: s.name)


def read_skill_metadata(name: str) -> tuple[dict[str, str], SkillSpec] | None:
    """Look up a skill by name and return (frontmatter, spec) or None."""
    for spec in discover_skills():
        if spec.name == name:
            fm = _read_frontmatter(spec.skill_dir)
            return fm, spec
    return None


def install_skills(
    distribution: str | None = None, *, dry_run: bool = False, legacy_shim: bool = False
) -> list[tuple[str, str]]:
    """Symlink every discovered skill into ~/.claude/skills/.

    Returns (name, action) tuples where action is one of:
      'installed' | 'updated' | 'skipped:already-current' | 'skipped:exists-not-spindle'
      (+ '<alias> (alias)' rows when legacy_shim=True).
    """
    target = claude_skills_dir()
    target.mkdir(parents=True, exist_ok=True)
    results: list[tuple[str, str]] = prune_legacy_symlinks(dry_run=dry_run)
    for spec in discover_skills(distribution):
        link = target / spec.name
        skill_path = spec.skill_dir
        if link.is_symlink():
            current = os.readlink(link)
            if current == str(skill_path):
                results.append((spec.name, "skipped:already-current"))
            else:
                if not dry_run:
                    link.unlink()
                    link.symlink_to(skill_path)
                results.append((spec.name, "updated"))
        elif link.exists():
            results.append((spec.name, "skipped:exists-not-spindle"))
        else:
            if not dry_run:
                link.symlink_to(skill_path)
            results.append((spec.name, "installed"))

        if legacy_shim:
            legacy_name = _get_legacy_alias_name(spec.name)
            if legacy_name:
                _create_or_update_alias(
                    target / legacy_name, link, legacy_name, dry_run, results
                )

    if not dry_run:
        linked = [name for name, action in results if action in {"installed", "updated"}]
        if linked:
            log_event("skill_link", distribution=distribution or "", skills_linked=linked)

    return results


def uninstall_skills(
    distribution: str | None = None, *, dry_run: bool = False
) -> list[tuple[str, str]]:
    """Remove symlinks pointing at currently-discovered skill_dirs (spindle-owned)."""
    target = claude_skills_dir()
    if not target.exists():
        return []
    specs = discover_skills(distribution)
    owned_targets = {str(s.skill_dir) for s in specs}
    results: list[tuple[str, str]] = []
    for spec in specs:
        link = target / spec.name
        if link.is_symlink():
            current = os.readlink(link)
            if current in owned_targets:
                if not dry_run:
                    link.unlink()
                results.append((spec.name, "removed"))
            else:
                results.append((spec.name, "skipped:not-spindle-owned"))
        elif link.exists():
            results.append((spec.name, "skipped:not-a-symlink"))
        else:
            results.append((spec.name, "skipped:not-installed"))

        legacy_name = _get_legacy_alias_name(spec.name)
        if legacy_name:
            legacy_link = target / legacy_name
            if legacy_link.is_symlink():
                try:
                    current = os.readlink(legacy_link)
                except OSError:
                    continue
                if current == str(link):
                    if not dry_run:
                        legacy_link.unlink()
                    results.append((f"{legacy_name} (alias)", "removed"))
            elif legacy_link.exists():
                results.append((f"{legacy_name} (alias)", "skipped:not-a-symlink"))

    if not dry_run:
        removed = [name for name, action in results if action == "removed"]
        if removed:
            log_event("skill_unlink", distribution=distribution or "", skills_removed=removed)

    return results


def status_skills(distribution: str | None = None) -> list[tuple[str, str]]:
    """Per-skill install state: installed | installed:stale-link | not-installed | conflict:*."""
    target = claude_skills_dir()
    specs = discover_skills(distribution)
    owned_targets = {str(s.skill_dir) for s in specs}
    results: list[tuple[str, str]] = []
    for spec in specs:
        link = target / spec.name
        if link.is_symlink():
            current = os.readlink(link)
            if current == str(spec.skill_dir):
                results.append((spec.name, "installed"))
            elif current in owned_targets:
                results.append((spec.name, "installed:stale-link"))
            else:
                results.append((spec.name, "conflict:other-symlink"))
        elif link.exists():
            results.append((spec.name, "conflict:real-file"))
        else:
            results.append((spec.name, "not-installed"))

        legacy_name = _get_legacy_alias_name(spec.name)
        if legacy_name:
            legacy_link = target / legacy_name
            if legacy_link.is_symlink():
                current = os.readlink(legacy_link)
                if current == str(link):
                    results.append((f"{legacy_name} (alias)", "installed"))
                else:
                    results.append((f"{legacy_name} (alias)", "conflict:other-symlink"))
            elif legacy_link.exists():
                results.append((f"{legacy_name} (alias)", "conflict:real-file"))

    return results
