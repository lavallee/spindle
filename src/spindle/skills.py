"""Discover and project installed Spindle skills into Claude's user scope.

Links keep editable skill sources live. Every link Spindle creates receives an
immutable ownership receipt; a matching target alone is never treated as proof
of ownership. Uninstall and legacy cleanup therefore preserve real directories,
foreign links, and user-retargeted links.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import active as active_mod
from .ledger import log_event
from .lifecycle import (
    LifecycleError,
    OwnershipRecord,
    OwnershipStore,
    content_id,
    digest_path,
    surface_id,
)
from .models import SkillSpec
from .packages import (
    list_installed_packages,
    package_skill_dirs,
    resolve_package_revision,
)
from .paths import claude_skills_dir


_NAME_LINE = re.compile(r"^name:\s*(.+?)\s*$")


def _read_frontmatter(skill_dir: Path) -> dict[str, str]:
    """Read YAML-like frontmatter from ``SKILL.md``."""
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
    frontmatter: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            frontmatter[key.strip()] = value.strip().strip('"').strip("'")
    return frontmatter


def _read_skill_name(skill_dir: Path) -> str | None:
    """Return the frontmatter ``name`` or ``None``."""
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
        match = _NAME_LINE.match(line)
        if match:
            return match.group(1).strip().strip('"').strip("'") or None
    return None


def _get_legacy_alias_name(skill_name: str) -> str | None:
    """Optional prefix mapping for private layers that need transition aliases."""
    old_prefix = os.environ.get("SPINDLE_LEGACY_ALIAS_FROM", "")
    new_prefix = os.environ.get("SPINDLE_LEGACY_ALIAS_TO", "")
    if old_prefix and new_prefix and skill_name.startswith(old_prefix):
        return skill_name.replace(old_prefix, new_prefix, 1)
    return None


def _global_surface_id(target: Path) -> str:
    return surface_id(target, "claude-user")


def _package_digest(spec: SkillSpec, cache: dict[str, str]) -> str:
    if spec.package not in cache:
        try:
            cache[spec.package] = resolve_package_revision(spec.package).content_digest
        except (ValueError, LifecycleError):
            cache[spec.package] = digest_path(spec.skill_dir)
    return cache[spec.package]


def _plan_link(link: Path, source: Path, record: OwnershipRecord | None) -> str:
    if link.is_symlink():
        current = (link.parent / os.readlink(link)).resolve(strict=False)
        if current == source.resolve(strict=False):
            if record is not None and record.matches_symlink(link):
                return "skipped:already-current"
            return "skipped:unowned-symlink"
        if record is not None and record.matches_symlink(link):
            return "updated"
        return "skipped:foreign-symlink"
    if link.exists():
        return "skipped:exists-not-spindle"
    return "installed"


def _record_projection(
    store: OwnershipStore,
    sid: str,
    *,
    name: str,
    link: Path,
    source: Path,
    package_digest: str,
    creation_receipt_id: str,
) -> None:
    store.record(
        OwnershipRecord(
            surface_id=sid,
            surface_name="claude-user",
            harness="claude",
            skill=name,
            projection_path=str(link.absolute()),
            source_path=str(source.absolute()),
            source_digest=digest_path(source),
            package_digest=package_digest,
            creation_receipt_id=creation_receipt_id,
        )
    )


def _create_or_update_alias(
    alias_link: Path,
    target_link: Path,
    name: str,
    dry_run: bool,
    results: list[tuple[str, str]],
    *,
    ownership_store: OwnershipStore | None = None,
    global_surface_id: str | None = None,
    package_digest: str | None = None,
    creation_receipt_id: str | None = None,
) -> None:
    """Point an owned alias at a main skill link without taking over foreign state."""
    store = ownership_store or OwnershipStore()
    sid = global_surface_id or _global_surface_id(alias_link.parent)
    record = store.records(sid).get(str(alias_link.absolute()))
    action = _plan_link(alias_link, target_link, record)
    results.append((f"{name} (alias)", action))
    if dry_run or (
        action.startswith("skipped:") and action != "skipped:already-current"
    ):
        return
    if action == "updated":
        alias_link.unlink()
    if action in {"updated", "installed"}:
        alias_link.symlink_to(target_link)
    source_digest = digest_path(target_link)
    _record_projection(
        store,
        sid,
        name=name,
        link=alias_link,
        source=target_link,
        package_digest=package_digest or source_digest,
        creation_receipt_id=creation_receipt_id
        or content_id({"alias": name, "target": str(target_link.absolute())}),
    )


def prune_legacy_symlinks(*, dry_run: bool = False) -> list[tuple[str, str]]:
    """Remove dead legacy links only when an exact receipt proves ownership."""
    skills_dir = claude_skills_dir()
    if not skills_dir.exists():
        return []
    try:
        legacy_base = str(active_mod.source_dir() / "skills" / "spindle-")
    except active_mod.ActiveDistributionError:
        legacy_base = ""
    store = OwnershipStore()
    sid = _global_surface_id(skills_dir)
    owned = store.records(sid)
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
        if legacy_base and not raw.startswith(legacy_base):
            results.append((link.name, "skipped:not-legacy"))
            continue
        record = owned.get(str(link.absolute()))
        if record is None:
            results.append((link.name, "skipped:unverified-ownership"))
            continue
        if not record.matches_symlink(link):
            results.append((link.name, "skipped:ownership-mismatch"))
            continue
        if not dry_run:
            link.unlink()
            store.forget(sid, link, record.ownership_id)
        results.append((link.name, "pruned"))
    return results


def discover_skills(distribution: str | None = None) -> list[SkillSpec]:
    """Skills shipped by installed Spindle packages."""
    specs: list[SkillSpec] = []
    seen: set[str] = set()
    for package in list_installed_packages():
        if distribution is not None and package.distribution != distribution:
            continue
        for skill_dir in package_skill_dirs(package.name):
            name = _read_skill_name(skill_dir) or skill_dir.name
            if name in seen:
                continue
            seen.add(name)
            specs.append(
                SkillSpec(name=name, package=package.name, skill_dir=skill_dir)
            )
    return sorted(specs, key=lambda skill: skill.name)


def read_skill_metadata(name: str) -> tuple[dict[str, str], SkillSpec] | None:
    """Look up a skill by name and return ``(frontmatter, spec)``."""
    for spec in discover_skills():
        if spec.name == name:
            return _read_frontmatter(spec.skill_dir), spec
    return None


def install_skills(
    distribution: str | None = None, *, dry_run: bool = False, legacy_shim: bool = False
) -> list[tuple[str, str]]:
    """Project discovered skills into Claude's user scope, ownership-safely."""
    target = claude_skills_dir()
    specs = discover_skills(distribution)
    store = OwnershipStore()
    sid = _global_surface_id(target)
    owned = store.records(sid)
    package_digests: dict[str, str] = {}
    receipt_id = content_id(
        {
            "operation": "install-skills",
            "surface_id": sid,
            "distribution": distribution,
            "skills": [
                {
                    "name": spec.name,
                    "source": str(spec.skill_dir.resolve()),
                    "package_digest": _package_digest(spec, package_digests),
                }
                for spec in specs
            ],
        }
    )
    plans: list[tuple[str, Path, Path, str, str, bool]] = []
    for spec in specs:
        link = target / spec.name
        source = spec.skill_dir.resolve()
        digest = _package_digest(spec, package_digests)
        plans.append(
            (
                spec.name,
                link,
                source,
                _plan_link(link, source, owned.get(str(link.absolute()))),
                digest,
                False,
            )
        )
        if legacy_shim:
            alias_name = _get_legacy_alias_name(spec.name)
            if alias_name:
                alias = target / alias_name
                plans.append(
                    (
                        alias_name,
                        alias,
                        link,
                        _plan_link(alias, link, owned.get(str(alias.absolute()))),
                        digest,
                        True,
                    )
                )

    results = prune_legacy_symlinks(dry_run=True)
    results.extend(
        (f"{name} (alias)" if alias else name, action)
        for name, _link, _source, action, _digest, alias in plans
    )
    conflicts = any(
        action.startswith("skipped:") and action != "skipped:already-current"
        for _name, _link, _source, action, _digest, _alias in plans
    )
    if dry_run or conflicts:
        return results

    target.mkdir(parents=True, exist_ok=True)
    prune_legacy_symlinks()
    for name, link, source, action, digest, _alias in plans:
        if action == "updated":
            link.unlink()
        if action in {"updated", "installed"}:
            link.symlink_to(source)
        _record_projection(
            store,
            sid,
            name=name,
            link=link,
            source=source,
            package_digest=digest,
            creation_receipt_id=receipt_id,
        )

    linked = [name for name, action in results if action in {"installed", "updated"}]
    if linked:
        log_event("skill_link", distribution=distribution or "", skills_linked=linked)
    return results


def uninstall_skills(
    distribution: str | None = None, *, dry_run: bool = False
) -> list[tuple[str, str]]:
    """Remove only projections proven by exact Spindle ownership receipts."""
    target = claude_skills_dir()
    if not target.exists():
        return []
    specs = discover_skills(distribution)
    store = OwnershipStore()
    sid = _global_surface_id(target)
    owned = store.records(sid)
    plans: list[tuple[str, Path, OwnershipRecord | None, bool]] = []
    for spec in specs:
        alias_name = _get_legacy_alias_name(spec.name)
        if alias_name:
            alias = target / alias_name
            plans.append((alias_name, alias, owned.get(str(alias.absolute())), True))
        link = target / spec.name
        plans.append((spec.name, link, owned.get(str(link.absolute())), False))

    evaluated: list[tuple[str, Path, OwnershipRecord | None, str, bool]] = []
    for name, link, record, alias in plans:
        if link.is_symlink():
            if record is None:
                action = "skipped:not-spindle-owned"
            elif record.matches_symlink(link):
                action = "removed"
            else:
                action = "skipped:ownership-mismatch"
        elif link.exists():
            action = "skipped:not-a-symlink"
        elif record is not None:
            action = "forgot:missing"
        else:
            action = "skipped:not-installed"
        evaluated.append((name, link, record, action, alias))

    results = [
        (f"{name} (alias)" if alias else name, action)
        for name, _link, _record, action, alias in evaluated
    ]
    if not dry_run:
        for _name, link, record, action, _alias in evaluated:
            if action == "removed":
                link.unlink()
            if action in {"removed", "forgot:missing"} and record is not None:
                store.forget(sid, link, record.ownership_id)
        removed = [name for name, action in results if action == "removed"]
        if removed:
            log_event(
                "skill_unlink",
                distribution=distribution or "",
                skills_removed=removed,
            )
    return results


def status_skills(distribution: str | None = None) -> list[tuple[str, str]]:
    """Report global install state with ownership distinguished from coincidence."""
    target = claude_skills_dir()
    specs = discover_skills(distribution)
    store = OwnershipStore()
    sid = _global_surface_id(target)
    owned = store.records(sid)
    results: list[tuple[str, str]] = []
    for spec in specs:
        link = target / spec.name
        record = owned.get(str(link.absolute()))
        if link.is_symlink():
            current = (link.parent / os.readlink(link)).resolve(strict=False)
            if (
                current == spec.skill_dir.resolve(strict=False)
                and record is not None
                and record.matches_symlink(link)
            ):
                results.append((spec.name, "installed"))
            elif record is not None and record.matches_symlink(link):
                results.append((spec.name, "installed:stale-owned"))
            elif record is not None:
                results.append((spec.name, "conflict:ownership-mismatch"))
            else:
                results.append((spec.name, "conflict:unowned-symlink"))
        elif link.exists():
            results.append((spec.name, "conflict:real-file"))
        else:
            results.append((spec.name, "not-installed"))

        alias_name = _get_legacy_alias_name(spec.name)
        if alias_name:
            alias = target / alias_name
            alias_record = owned.get(str(alias.absolute()))
            if alias.is_symlink():
                current = (alias.parent / os.readlink(alias)).resolve(strict=False)
                if (
                    current == link.resolve(strict=False)
                    and alias_record is not None
                    and alias_record.matches_symlink(alias)
                ):
                    results.append((f"{alias_name} (alias)", "installed"))
                elif alias_record is not None:
                    results.append(
                        (f"{alias_name} (alias)", "conflict:ownership-mismatch")
                    )
                else:
                    results.append(
                        (f"{alias_name} (alias)", "conflict:unowned-symlink")
                    )
            elif alias.exists():
                results.append((f"{alias_name} (alias)", "conflict:real-file"))
    return results
