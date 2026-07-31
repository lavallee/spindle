"""Deterministic effective skill inventory and ownership-safe reconciliation."""

from __future__ import annotations

import json
import os
import stat
import tomllib
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable

from . import paths
from .lifecycle import (
    LifecycleError,
    OwnershipRecord,
    OwnershipStore,
    SurfaceLock,
    content_id,
    digest_path,
    surface_id,
)

EFFECTIVE_INVENTORY_SCHEMA = "spindle.effective-inventory/v1"
INVENTORY_DIGEST_CACHE_SCHEMA = "spindle.inventory-digest-cache-entry/v1"


class InventoryState(StrEnum):
    EXPECTED_OWNED = "expected-owned"
    STALE_OWNED = "stale-owned"
    FOREIGN = "foreign"
    CONFLICTING = "conflicting"
    DISABLED = "disabled"
    BROKEN = "broken"
    OPAQUE = "opaque"
    MISSING = "missing"
    AMBIGUOUS_OWNERSHIP = "ambiguous-ownership"


@dataclass(frozen=True)
class DiscoveryRoot:
    scope: str
    path: Path | None
    kind: str = "skill"
    precedence: int = 0
    detail: str = ""


@dataclass(frozen=True)
class InventoryEntry:
    name: str
    scope: str
    path: str | None
    kind: str
    state: InventoryState
    reason: str
    precedence: int = 0
    enabled: bool | None = True
    link_target: str | None = None
    resolved_target: str | None = None
    content_digest: str | None = None
    ownership_id: str | None = None
    expected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "scope": self.scope,
            "path": self.path,
            "kind": self.kind,
            "state": self.state.value,
            "reason": self.reason,
            "precedence": self.precedence,
            "enabled": self.enabled,
            "link_target": self.link_target,
            "resolved_target": self.resolved_target,
            "content_digest": self.content_digest,
            "ownership_id": self.ownership_id,
            "expected": self.expected,
        }


@dataclass(frozen=True)
class EffectiveInventory:
    surface_id: str
    surface_name: str
    repo_path: str
    harness: str
    lock_id: str | None
    entries: tuple[InventoryEntry, ...]

    @property
    def inventory_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": EFFECTIVE_INVENTORY_SCHEMA,
            "surface_id": self.surface_id,
            "surface_name": self.surface_name,
            "repo_path": self.repo_path,
            "harness": self.harness,
            "lock_id": self.lock_id,
            "entries": [entry.to_dict() for entry in self.entries],
        }
        if include_id:
            payload = {"inventory_id": self.inventory_id, **payload}
        return payload

    def entries_for(self, skill: str) -> tuple[InventoryEntry, ...]:
        return tuple(entry for entry in self.entries if entry.name == skill)

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for entry in self.entries:
            result[entry.state.value] = result.get(entry.state.value, 0) + 1
        return dict(sorted(result.items()))

    def blocking_entries(self) -> tuple[InventoryEntry, ...]:
        blocking = {
            InventoryState.STALE_OWNED,
            InventoryState.CONFLICTING,
            InventoryState.MISSING,
            InventoryState.AMBIGUOUS_OWNERSHIP,
        }
        return tuple(
            entry
            for entry in self.entries
            if entry.state in blocking
            or (
                entry.state in {InventoryState.DISABLED, InventoryState.BROKEN}
                and (entry.expected or entry.ownership_id is not None)
            )
        )


@dataclass(frozen=True)
class ReconcileAction:
    skill: str
    projection_path: str
    action: str
    ownership_id: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class DisabledRules:
    names: frozenset[str] = frozenset()
    paths: frozenset[str] = frozenset()

    def disables(self, name: str, path: Path) -> bool:
        return name in self.names or str(path.absolute()) in self.paths


class InventoryDigestCache:
    """Immutable content-digest cache for startup's metadata-only fast path.

    The cache key includes both the resolved source path and a recursive lstat
    fingerprint. A cache miss is never treated as proof: fast inventory leaves
    the content digest unknown, while a deep inventory computes and records it.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or paths.inventory_digest_cache_dir()

    def get(self, source: str | Path, metadata_digest: str | None) -> str | None:
        if metadata_digest is None:
            return None
        source_path = str(Path(source).resolve(strict=False))
        cache_id = content_id(
            {"source_path": source_path, "metadata_digest": metadata_digest}
        )
        target = self.root / f"{_digest_hex(cache_id)}.json"
        if not target.is_file():
            return None
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if (
            raw.get("schema") != INVENTORY_DIGEST_CACHE_SCHEMA
            or raw.get("cache_id") != cache_id
            or raw.get("source_path") != source_path
            or raw.get("metadata_digest") != metadata_digest
        ):
            return None
        digest = raw.get("content_digest")
        return digest if _is_content_id(digest) else None

    def record(
        self,
        source: str | Path,
        metadata_digest: str | None,
        content_digest: str,
    ) -> None:
        if metadata_digest is None or not _is_content_id(content_digest):
            return
        source_path = str(Path(source).resolve(strict=False))
        cache_id = content_id(
            {"source_path": source_path, "metadata_digest": metadata_digest}
        )
        payload = {
            "schema": INVENTORY_DIGEST_CACHE_SCHEMA,
            "cache_id": cache_id,
            "source_path": source_path,
            "metadata_digest": metadata_digest,
            "content_digest": content_digest,
        }
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{_digest_hex(cache_id)}.json"
        serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if target.exists():
            if target.read_text(encoding="utf-8") != serialized:
                raise LifecycleError(f"inventory digest cache collision at {target}")
            return
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if target.read_text(encoding="utf-8") != serialized:
                raise LifecycleError(f"inventory digest cache collision at {target}")
            return
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())

    def resolve(self, source: str | Path, *, mode: str) -> str | None:
        if mode not in {"deep", "cache-only"}:
            raise LifecycleError(f"unsupported inventory digest mode: {mode}")
        source_path = Path(source)
        metadata_digest = _metadata_digest(source_path)
        digest = self.get(source_path, metadata_digest)
        if digest is not None or mode == "cache-only":
            return digest
        try:
            digest = digest_path(source_path)
        except LifecycleError:
            return None
        self.record(source_path, metadata_digest, digest)
        return digest


def default_discovery_roots(
    repo_path: str | Path,
    harness: str,
    *,
    home: Path | None = None,
    admin_root: Path | None = None,
    additional_roots: Iterable[DiscoveryRoot] = (),
) -> tuple[DiscoveryRoot, ...]:
    """Return the locally observable discovery scopes for a reference harness."""

    repo = Path(repo_path).resolve()
    user_home = (home or Path.home()).resolve()
    vcs_root = _repository_root(repo)
    ancestors: list[Path] = []
    cursor = repo
    while True:
        ancestors.append(cursor)
        if cursor == vcs_root or cursor.parent == cursor:
            break
        cursor = cursor.parent

    roots: list[DiscoveryRoot] = []
    seen: set[tuple[str, str]] = set()

    def add(root: DiscoveryRoot) -> None:
        key = (root.kind, str(root.path) if root.path is not None else root.scope)
        if key not in seen:
            seen.add(key)
            roots.append(root)

    if harness == "codex":
        for depth, ancestor in enumerate(ancestors):
            add(
                DiscoveryRoot(
                    scope=f"repo:{_relative_scope(ancestor, vcs_root)}",
                    path=ancestor / ".agents" / "skills",
                    precedence=100 - depth,
                )
            )
        add(
            DiscoveryRoot(
                scope="user", path=user_home / ".agents" / "skills", precedence=50
            )
        )
        add(
            DiscoveryRoot(
                scope="admin",
                path=(admin_root or Path("/etc/codex")) / "skills",
                precedence=200,
            )
        )
        add(
            DiscoveryRoot(
                scope="plugins",
                path=None,
                kind="opaque",
                precedence=150,
                detail="enabled Codex plugin skills require harness-reported inventory",
            )
        )
        add(
            DiscoveryRoot(
                scope="system",
                path=None,
                kind="opaque",
                precedence=300,
                detail="Codex built-in skills are harness-managed",
            )
        )
    elif harness == "claude":
        for depth, ancestor in enumerate(ancestors):
            label = f"repo:{_relative_scope(ancestor, vcs_root)}"
            add(
                DiscoveryRoot(
                    scope=label,
                    path=ancestor / ".claude" / "skills",
                    precedence=100 - depth,
                )
            )
            add(
                DiscoveryRoot(
                    scope=f"{label}:commands",
                    path=ancestor / ".claude" / "commands",
                    kind="command",
                    precedence=90 - depth,
                )
            )
        add(
            DiscoveryRoot(
                scope="user", path=user_home / ".claude" / "skills", precedence=200
            )
        )
        add(
            DiscoveryRoot(
                scope="user:commands",
                path=user_home / ".claude" / "commands",
                kind="command",
                precedence=190,
            )
        )
        add(
            DiscoveryRoot(
                scope="plugins",
                path=None,
                kind="opaque",
                precedence=150,
                detail="Claude plugin skills are namespaced and harness-managed",
            )
        )
        add(
            DiscoveryRoot(
                scope="managed",
                path=None,
                kind="opaque",
                precedence=300,
                detail="Claude managed and bundled skills require harness-reported inventory",
            )
        )
    else:
        raise LifecycleError(
            f"effective inventory adapter is unavailable for {harness!r}"
        )

    for root in additional_roots:
        add(root)
    return tuple(roots)


def scan_effective_inventory(
    repo_path: str | Path,
    harness: str,
    *,
    surface_name: str | None = None,
    lock: SurfaceLock | None = None,
    ownership_store: OwnershipStore | None = None,
    roots: Iterable[DiscoveryRoot] | None = None,
    disabled: DisabledRules | None = None,
    home: Path | None = None,
    admin_root: Path | None = None,
    digest_mode: str = "deep",
    digest_cache: InventoryDigestCache | None = None,
) -> EffectiveInventory:
    if digest_mode not in {"deep", "cache-only"}:
        raise LifecycleError(f"unsupported inventory digest mode: {digest_mode}")
    repo = Path(repo_path).resolve()
    sid = surface_id(repo, harness)
    if lock is not None and lock.surface_id != sid:
        raise LifecycleError("surface lock does not describe this repo/harness")
    store = ownership_store or OwnershipStore()
    ownership = store.records(sid)
    expected_by_path = {
        str(Path(item.projection_path).absolute()): item
        for item in (lock.projections if lock is not None else ())
    }
    expected_names = {item.skill for item in expected_by_path.values()}
    rules = disabled or load_disabled_rules(repo, harness, home=home)
    selected_roots = tuple(
        roots
        if roots is not None
        else default_discovery_roots(repo, harness, home=home, admin_root=admin_root)
    )

    entries: list[InventoryEntry] = []
    observed_paths: set[str] = set()
    for root in selected_roots:
        if root.kind == "opaque":
            entries.append(
                InventoryEntry(
                    name=f"__{root.scope}__",
                    scope=root.scope,
                    path=None,
                    kind="opaque",
                    state=InventoryState.OPAQUE,
                    reason=root.detail or "scope cannot be inspected locally",
                    precedence=root.precedence,
                    enabled=None,
                )
            )
            continue
        if root.path is None or not root.path.is_dir():
            continue
        for path in _root_entries(root):
            entry = _observe_entry(
                path,
                root,
                expected_by_path=expected_by_path,
                expected_names=expected_names,
                ownership=ownership,
                disabled=rules,
                digest_mode=digest_mode,
                digest_cache=digest_cache,
            )
            entries.append(entry)
            if entry.path is not None:
                observed_paths.add(entry.path)

    entries = _mark_duplicate_conflicts(entries, expected_names)
    for projection_path, expected in sorted(expected_by_path.items()):
        if projection_path not in observed_paths:
            record = ownership.get(projection_path)
            entries.append(
                InventoryEntry(
                    name=expected.skill,
                    scope="expected",
                    path=projection_path,
                    kind="skill",
                    state=InventoryState.MISSING,
                    reason="desired projection is absent",
                    enabled=False,
                    content_digest=None,
                    ownership_id=record.ownership_id if record is not None else None,
                    expected=True,
                )
            )

    ordered = tuple(
        sorted(
            entries,
            key=lambda item: (
                item.name,
                -item.precedence,
                item.scope,
                item.path or "",
                item.kind,
            ),
        )
    )
    return EffectiveInventory(
        surface_id=sid,
        surface_name=surface_name or repo.name,
        repo_path=str(repo),
        harness=harness,
        lock_id=lock.lock_id if lock is not None else None,
        entries=ordered,
    )


def reconcile_owned(
    inventory: EffectiveInventory,
    *,
    ownership_store: OwnershipStore | None = None,
    dry_run: bool = False,
) -> tuple[ReconcileAction, ...]:
    """Remove only stale/broken projections whose exact ownership still matches."""

    store = ownership_store or OwnershipStore()
    ownership = store.records(inventory.surface_id)
    actions: list[ReconcileAction] = []
    eligible = {InventoryState.STALE_OWNED, InventoryState.BROKEN}
    for entry in inventory.entries:
        if (
            entry.state not in eligible
            or entry.path is None
            or entry.ownership_id is None
        ):
            continue
        record = ownership.get(entry.path)
        if record is None or record.ownership_id != entry.ownership_id:
            continue
        if not record.matches_symlink(entry.path):
            actions.append(
                ReconcileAction(
                    skill=entry.name,
                    projection_path=entry.path,
                    action="preserved:ownership-mismatch",
                    ownership_id=record.ownership_id,
                    reason="current projection no longer matches its ownership receipt",
                )
            )
            continue
        action = "would-remove" if dry_run else "removed"
        if not dry_run:
            Path(entry.path).unlink()
            if not store.forget(inventory.surface_id, entry.path, record.ownership_id):
                raise LifecycleError(
                    f"ownership index changed while reconciling {entry.path}"
                )
        actions.append(
            ReconcileAction(
                skill=entry.name,
                projection_path=entry.path,
                action=action,
                ownership_id=record.ownership_id,
                reason=entry.reason,
            )
        )
    return tuple(actions)


def load_disabled_rules(
    repo_path: str | Path, harness: str, *, home: Path | None = None
) -> DisabledRules:
    repo = Path(repo_path).resolve()
    user_home = (home or Path.home()).resolve()
    if harness == "claude":
        names: dict[str, str] = {}
        files = [
            user_home / ".claude" / "settings.json",
            repo / ".claude" / "settings.json",
            repo / ".claude" / "settings.local.json",
        ]
        for path in files:
            if not path.is_file():
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            overrides = raw.get("skillOverrides") if isinstance(raw, dict) else None
            if isinstance(overrides, dict):
                names.update(
                    {str(name): str(value) for name, value in overrides.items()}
                )
        return DisabledRules(
            names=frozenset(name for name, value in names.items() if value == "off")
        )
    if harness == "codex":
        disabled_paths: set[str] = set()
        config_files = [
            user_home / ".codex" / "config.toml",
            repo / ".codex" / "config.toml",
        ]
        for config in config_files:
            if not config.is_file():
                continue
            try:
                raw = tomllib.loads(config.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                continue
            skills = raw.get("skills") if isinstance(raw, dict) else None
            rows = skills.get("config") if isinstance(skills, dict) else None
            if not isinstance(rows, list):
                continue
            for row in rows:
                if (
                    isinstance(row, dict)
                    and row.get("enabled") is False
                    and isinstance(row.get("path"), str)
                ):
                    path = Path(row["path"]).expanduser()
                    if not path.is_absolute():
                        path = config.parent / path
                    skill_path = path.parent if path.name == "SKILL.md" else path
                    disabled_paths.add(str(skill_path.absolute()))
        return DisabledRules(paths=frozenset(disabled_paths))
    return DisabledRules()


def _root_entries(root: DiscoveryRoot) -> tuple[Path, ...]:
    assert root.path is not None
    if root.kind == "command":
        return tuple(
            sorted(path for path in root.path.iterdir() if path.suffix == ".md")
        )
    return tuple(sorted(root.path.iterdir()))


def _observe_entry(
    path: Path,
    root: DiscoveryRoot,
    *,
    expected_by_path: dict[str, Any],
    expected_names: set[str],
    ownership: dict[str, OwnershipRecord],
    disabled: DisabledRules,
    digest_mode: str,
    digest_cache: InventoryDigestCache | None,
) -> InventoryEntry:
    absolute = str(path.absolute())
    expected = expected_by_path.get(absolute)
    record = ownership.get(absolute)
    broken = path.is_symlink() and not path.exists()
    link_target = os.readlink(path) if path.is_symlink() else None
    resolved = (
        str((path.parent / link_target).resolve(strict=False))
        if link_target is not None
        else str(path.resolve(strict=False))
    )
    name = _entry_name(path, root.kind)
    digest: str | None = None
    if not broken:
        content_path = Path(resolved) if path.is_symlink() else path
        if content_path.exists():
            if digest_cache is not None:
                digest = digest_cache.resolve(content_path, mode=digest_mode)
            elif digest_mode == "deep":
                try:
                    digest = digest_path(content_path)
                except LifecycleError:
                    digest = None

    is_disabled = disabled.disables(name, path)
    if is_disabled:
        state = InventoryState.DISABLED
        reason = "disabled by effective harness settings"
    elif record is not None and not record.matches_symlink(path):
        state = InventoryState.AMBIGUOUS_OWNERSHIP
        reason = "ownership index exists but the current projection target differs"
    elif broken:
        state = InventoryState.BROKEN
        reason = "symlink target does not exist"
    elif record is not None:
        exact = (
            expected is not None
            and resolved == str(Path(expected.source_path).resolve(strict=False))
            and digest == expected.source_digest
            and record.source_digest == expected.source_digest
            and record.package_digest == expected.package_digest
        )
        if exact:
            state = InventoryState.EXPECTED_OWNED
            reason = "projection and content match desired state and ownership"
        else:
            state = InventoryState.STALE_OWNED
            reason = "owned projection is absent from or differs from desired state"
    elif expected is not None or name in expected_names:
        state = InventoryState.CONFLICTING
        reason = "unowned entry collides with desired state"
    else:
        state = InventoryState.FOREIGN
        reason = "entry is outside Spindle ownership"

    return InventoryEntry(
        name=name,
        scope=root.scope,
        path=absolute,
        kind=root.kind,
        state=state,
        reason=reason,
        precedence=root.precedence,
        enabled=not is_disabled,
        link_target=link_target,
        resolved_target=resolved,
        content_digest=digest,
        ownership_id=record.ownership_id if record is not None else None,
        expected=expected is not None,
    )


def _mark_duplicate_conflicts(
    entries: list[InventoryEntry], expected_names: set[str]
) -> list[InventoryEntry]:
    active_by_name: dict[str, list[int]] = {}
    inactive = {
        InventoryState.DISABLED,
        InventoryState.OPAQUE,
        InventoryState.MISSING,
    }
    for index, entry in enumerate(entries):
        if entry.state not in inactive and not entry.name.startswith("__"):
            active_by_name.setdefault(entry.name, []).append(index)
    updated = list(entries)
    for name, indexes in active_by_name.items():
        if len(indexes) < 2 and name not in expected_names:
            continue
        for index in indexes:
            entry = updated[index]
            if entry.state in {
                InventoryState.FOREIGN,
                InventoryState.CONFLICTING,
            }:
                updated[index] = replace(
                    entry,
                    state=InventoryState.CONFLICTING,
                    reason="same-name entry overlaps another effective scope",
                )
    return updated


def _entry_name(path: Path, kind: str) -> str:
    if kind == "command":
        return path.stem
    skill_md = path / "SKILL.md"
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return path.name
    if not text.startswith("---"):
        return path.name
    end = text.find("\n---", 3)
    if end < 0:
        return path.name
    for line in text[3:end].splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() == "name" and value.strip():
            return value.strip().strip('"').strip("'")
    return path.name


def _repository_root(path: Path) -> Path:
    cursor = path if path.is_dir() else path.parent
    for candidate in (cursor, *cursor.parents):
        if (candidate / ".git").exists():
            return candidate
    return cursor


def _relative_scope(path: Path, root: Path) -> str:
    if path == root:
        return "."
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _metadata_digest(path: Path) -> str | None:
    """Fingerprint a tree without reading file content or following symlinks."""

    records: list[dict[str, Any]] = []
    stack: list[tuple[Path, str]] = [(path, ".")]
    try:
        while stack:
            current, relative = stack.pop()
            info = current.lstat()
            row: dict[str, Any] = {
                "path": relative,
                "mode": info.st_mode,
                "size": info.st_size,
                "mtime_ns": info.st_mtime_ns,
                "ctime_ns": info.st_ctime_ns,
            }
            if stat.S_ISLNK(info.st_mode):
                row["link_target"] = os.readlink(current)
            records.append(row)
            if stat.S_ISDIR(info.st_mode):
                children = sorted(current.iterdir(), key=lambda child: child.name)
                for child in reversed(children):
                    child_relative = (
                        child.name if relative == "." else f"{relative}/{child.name}"
                    )
                    stack.append((child, child_relative))
    except OSError:
        return None
    return content_id(records)


def _is_content_id(value: object) -> bool:
    if not isinstance(value, str):
        return False
    prefix, separator, digest = value.partition(":")
    return separator == ":" and prefix == "sha256" and len(digest) == 64


def _digest_hex(identity: str) -> str:
    if not _is_content_id(identity):
        raise LifecycleError(f"invalid content identity: {identity}")
    return identity.removeprefix("sha256:")
