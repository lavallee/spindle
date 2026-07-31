"""State export/import, cache custody, migration audit, and crash recovery."""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from . import hooks, inventory, maintenance, paths, trust
from .lifecycle import (
    LifecycleError,
    OwnershipRecord,
    SurfaceLock,
    content_id,
    digest_path,
    read_surface_lock,
    surface_id,
)

BUNDLE_SCHEMA = "spindle.state-bundle/v1"
IMPORT_PLAN_SCHEMA = "spindle.state-import-plan/v1"
GC_PLAN_SCHEMA = "spindle.cache-gc-plan/v1"
GC_EVENT_SCHEMA = "spindle.cache-gc-event/v1"
RECOVERY_PLAN_SCHEMA = "spindle.recovery-plan/v1"
RECOVERY_EVENT_SCHEMA = "spindle.recovery-event/v1"
MIGRATION_PLAN_SCHEMA = "spindle.migration-plan/v1"
MIGRATION_EVENT_SCHEMA = "spindle.migration-event/v1"

_DIGEST_DIR = re.compile(r"^[0-9a-f]{64}$")
_MAX_BUNDLE_BYTES = 512 * 1024 * 1024
_MAX_BUNDLE_FILES = 50_000
_MUTABLE_FILES = frozenset(
    {
        "maintenance.json",
        "quarantine.json",
        "hooks.json",
        "startup-observations.jsonl",
        "events.jsonl",
        "state.json",
        "ledger.jsonl",
    }
)


class CustodyError(ValueError):
    """Raised when a state custody operation cannot be proved safe."""


def export_state(
    output: str | Path,
    *,
    include_cache: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    state = paths.spindle_home().resolve()
    target = Path(output).resolve()
    files = _state_files(state, include_cache=include_cache, exclude=target)
    entries = [
        {
            "path": path.relative_to(state).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": f"sha256:{_sha256_file(path)}",
        }
        for path in files
    ]
    body = {
        "schema": BUNDLE_SCHEMA,
        "include_cache": include_cache,
        "files": entries,
        "schemas": _schema_counts(files),
    }
    manifest = {"bundle_id": content_id(body), **body}
    payload = {
        "action": "would-export" if dry_run else "exported",
        "output": str(target),
        "manifest": manifest,
    }
    if dry_run:
        return payload
    encoded = _bundle_bytes(state, files, manifest)
    if target.exists():
        if target.is_symlink() or not target.is_file() or target.read_bytes() != encoded:
            raise CustodyError(f"bundle output already contains different content: {target}")
        return payload
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_bytes_atomic(target, encoded)
    return payload


def plan_import(bundle: str | Path, *, destination: Path | None = None) -> dict[str, Any]:
    target = (destination or paths.spindle_home()).resolve()
    manifest, payloads = _read_bundle(Path(bundle).resolve())
    actions: list[dict[str, str]] = []
    blockers: list[str] = []
    for entry in manifest["files"]:
        relative = str(entry["path"])
        destination_path = target / relative
        if destination_path.is_symlink():
            state = "conflict"
        elif not destination_path.exists():
            state = "create"
        elif destination_path.is_file() and _sha256_bytes(
            destination_path.read_bytes()
        ) == entry["sha256"].removeprefix("sha256:"):
            state = "identical"
        else:
            state = "conflict"
        actions.append({"path": relative, "action": state})
        if state == "conflict":
            blockers.append(relative)
    body = {
        "schema": IMPORT_PLAN_SCHEMA,
        "bundle_id": manifest["bundle_id"],
        "destination": str(target),
        "actions": actions,
        "blockers": sorted(blockers),
    }
    return {"plan_id": content_id(body), **body, "_payloads": payloads}


def import_state(
    bundle: str | Path,
    *,
    destination: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    plan = plan_import(bundle, destination=destination)
    payloads = plan.pop("_payloads")
    if plan["blockers"]:
        raise CustodyError("state import conflicts: " + ", ".join(plan["blockers"]))
    if dry_run:
        return {"action": "would-import", "plan": plan}
    root = Path(plan["destination"])
    lock_path = root / ".custody.lock"
    with _file_lock(lock_path):
        replay = plan_import(bundle, destination=root)
        replay.pop("_payloads")
        if replay["plan_id"] != plan["plan_id"] or replay["blockers"]:
            raise CustodyError("state import changed after planning; re-plan")
        for action in plan["actions"]:
            if action["action"] != "create":
                continue
            target = root / action["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_bytes_exclusive(target, payloads[action["path"]])
    return {"action": "imported", "plan": plan}


def cache_gc_plan() -> dict[str, Any]:
    referenced = _referenced_package_digests()
    cache = paths.package_cache_dir()
    candidates: list[dict[str, Any]] = []
    blockers: list[str] = []
    if cache.is_dir():
        for digest_dir in sorted(cache.iterdir()):
            if digest_dir.is_symlink() or not digest_dir.is_dir():
                blockers.append(f"unrecognized package cache entry: {digest_dir}")
                continue
            if not _DIGEST_DIR.fullmatch(digest_dir.name):
                blockers.append(f"unrecognized package digest directory: {digest_dir}")
                continue
            digest = f"sha256:{digest_dir.name}"
            valid = True
            packages: list[str] = []
            for package in sorted(digest_dir.iterdir()):
                if package.is_symlink() or not package.is_dir():
                    valid = False
                    break
                packages.append(package.name)
                if digest_path(package) != digest:
                    valid = False
                    break
            if not valid or not packages:
                blockers.append(f"package cache integrity mismatch: {digest_dir}")
                continue
            if digest not in referenced:
                candidates.append(
                    {
                        "package_digest": digest,
                        "path": str(digest_dir.resolve()),
                        "packages": packages,
                        "bytes": _tree_bytes(digest_dir),
                    }
                )
    body = {
        "schema": GC_PLAN_SCHEMA,
        "cache_root": str(cache.resolve()),
        "referenced_package_digests": sorted(referenced),
        "candidates": candidates,
        "blockers": sorted(blockers),
    }
    return {"plan_id": content_id(body), **body}


def apply_cache_gc(plan_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    plan = cache_gc_plan()
    if plan["plan_id"] != plan_id:
        raise CustodyError("cache GC plan changed; re-plan")
    if plan["blockers"]:
        raise CustodyError("cache GC blocked: " + "; ".join(plan["blockers"]))
    if dry_run:
        return {"action": "would-gc", "plan": plan}
    cache = Path(plan["cache_root"])
    removed: list[str] = []
    with _file_lock(paths.spindle_home() / ".cache-gc.lock"):
        replay = cache_gc_plan()
        if replay["plan_id"] != plan_id:
            raise CustodyError("cache GC state changed after planning; re-plan")
        for candidate in plan["candidates"]:
            target = Path(candidate["path"])
            if target.parent != cache.resolve() or not _DIGEST_DIR.fullmatch(target.name):
                raise CustodyError("cache GC target escaped the package cache")
            shutil.rmtree(target)
            removed.append(candidate["package_digest"])
    body = {
        "schema": GC_EVENT_SCHEMA,
        "plan_id": plan_id,
        "removed_package_digests": removed,
        "removed_bytes": sum(item["bytes"] for item in plan["candidates"]),
    }
    event = {"event_id": content_id(body), **body}
    _write_json_immutable(
        paths.hardening_receipts_dir() / f"{event['event_id'][7:]}.json", event
    )
    return {"action": "garbage-collected", "plan": plan, "event": event}


def recovery_plan() -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    proposed: dict[str, Any] = {}
    locks = _load_locks(blockers)
    proposed["ownership_indexes"] = _recover_ownership(locks, blockers)
    proposed["maintenance_index"] = _recover_maintenance(blockers)
    proposed["quarantine_index"] = _recover_quarantine(blockers)
    proposed["hook_index"] = _recover_hooks(blockers, warnings)
    body = {
        "schema": RECOVERY_PLAN_SCHEMA,
        "proposed": proposed,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
    }
    return {"plan_id": content_id(body), **body}


def apply_recovery(plan_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    plan = recovery_plan()
    if plan["plan_id"] != plan_id:
        raise CustodyError("recovery plan changed; re-plan")
    if plan["blockers"]:
        raise CustodyError("recovery blocked: " + "; ".join(plan["blockers"]))
    if dry_run:
        return {"action": "would-recover", "plan": plan}
    with _file_lock(paths.spindle_home() / ".recovery.lock"):
        replay = recovery_plan()
        if replay["plan_id"] != plan_id:
            raise CustodyError("recovery inputs changed after planning; re-plan")
        for surface, payload in plan["proposed"]["ownership_indexes"].items():
            target = paths.ownership_index_dir() / f"{surface.removeprefix('sha256:')}.json"
            _write_json_atomic(target, payload)
        _write_json_atomic(
            paths.maintenance_index_file(), plan["proposed"]["maintenance_index"]
        )
        _write_json_atomic(
            paths.quarantine_index_file(), plan["proposed"]["quarantine_index"]
        )
        _write_json_atomic(paths.hook_index_file(), plan["proposed"]["hook_index"])
    body = {
        "schema": RECOVERY_EVENT_SCHEMA,
        "plan_id": plan_id,
        "recovered_indexes": ["ownership", "maintenance", "quarantine", "hooks"],
    }
    event = {"event_id": content_id(body), **body}
    _write_json_immutable(
        paths.hardening_receipts_dir() / f"{event['event_id'][7:]}.json", event
    )
    return {"action": "recovered", "plan": plan, "event": event}


def migration_plan(repo: str | Path, harness: str) -> dict[str, Any]:
    project = Path(repo).resolve()
    sid = surface_id(project, harness)
    blockers: list[str] = []
    actions: list[dict[str, Any]] = []
    lock = read_surface_lock(sid)
    if lock is not None:
        actions.append(
            {
                "kind": "existing-surface-lock",
                "status": "current",
                "lock_id": lock.lock_id,
                "binding_coordinate": lock.binding_coordinate,
            }
        )
    effective = inventory.scan_effective_inventory(
        project,
        harness,
        surface_name=project.name,
        lock=lock,
    )
    for entry in effective.entries:
        if entry.state in {
            inventory.InventoryState.FOREIGN,
            inventory.InventoryState.OPAQUE,
            inventory.InventoryState.CONFLICTING,
        }:
            actions.append(
                {
                    "kind": "legacy-or-foreign-skill",
                    "status": "preserve",
                    "name": entry.name,
                    "scope": entry.scope,
                    "path": entry.path,
                    "next": "inspect and try before explicit adoption",
                }
            )
    adoption_root = paths.adoption_receipts_dir()
    if adoption_root.is_dir():
        for target in sorted(adoption_root.glob("*.json")):
            try:
                raw = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                blockers.append(f"invalid adoption record {target}: {exc}")
                continue
            if raw.get("schema") == "spindle.adoption-record/v1":
                blockers.append(
                    f"legacy adoption {target} lacks trial/activation provenance; "
                    "re-try exact cached bytes before v2 adoption"
                )
            elif raw.get("schema") != maintenance.ADOPTION_RECORD_SCHEMA:
                blockers.append(f"unknown adoption schema at {target}")
    body = {
        "schema": MIGRATION_PLAN_SCHEMA,
        "repo_path": str(project),
        "harness": harness,
        "surface_id": sid,
        "actions": actions,
        "blockers": sorted(blockers),
        "foreign_policy": "preserve-never-infer-ownership",
    }
    return {"plan_id": content_id(body), **body}


def record_migration(plan_id: str, repo: str | Path, harness: str) -> dict[str, Any]:
    plan = migration_plan(repo, harness)
    if plan["plan_id"] != plan_id:
        raise CustodyError("migration plan changed; re-plan")
    if plan["blockers"]:
        raise CustodyError("migration blocked: " + "; ".join(plan["blockers"]))
    body = {
        "schema": MIGRATION_EVENT_SCHEMA,
        "plan_id": plan_id,
        "surface_id": plan["surface_id"],
        "decision": "audited-current-state-and-preserved-foreign",
    }
    event = {"event_id": content_id(body), **body}
    _write_json_immutable(
        paths.hardening_receipts_dir() / f"{event['event_id'][7:]}.json", event
    )
    return {"action": "migration-audited", "plan": plan, "event": event}


def _state_files(state: Path, *, include_cache: bool, exclude: Path) -> list[Path]:
    if not state.exists():
        return []
    result: list[Path] = []
    for path in sorted(state.rglob("*")):
        if path == exclude or path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(state)
        if path.name.endswith(".lock") or path.name.startswith("."):
            continue
        if relative.parts[:2] == ("cache", "sources"):
            continue
        if relative.parts[:2] == ("cache", "inventory-digests"):
            continue
        if relative.parts[:2] == ("cache", "packages") and not include_cache:
            continue
        result.append(path)
    return result


def _bundle_bytes(state: Path, files: list[Path], manifest: dict[str, Any]) -> bytes:
    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
            _tar_bytes(archive, "manifest.json", manifest_bytes)
            for path in files:
                _tar_bytes(
                    archive,
                    f"state/{path.relative_to(state).as_posix()}",
                    path.read_bytes(),
                    mode=path.stat().st_mode & 0o777,
                )
    return raw.getvalue()


def _tar_bytes(archive: tarfile.TarFile, name: str, payload: bytes, mode: int = 0o600) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mode = mode
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    archive.addfile(info, io.BytesIO(payload))


def _read_bundle(bundle: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    if bundle.is_symlink() or not bundle.is_file():
        raise CustodyError("state bundle must be a regular file")
    payloads: dict[str, bytes] = {}
    total = 0
    try:
        with tarfile.open(bundle, mode="r:gz") as archive:
            members = archive.getmembers()
            if len(members) > _MAX_BUNDLE_FILES:
                raise CustodyError("state bundle contains too many files")
            for member in members:
                pure = PurePosixPath(member.name)
                if (
                    member.name.startswith("/")
                    or ".." in pure.parts
                    or not member.isfile()
                    or member.name in payloads
                ):
                    raise CustodyError(f"unsafe state bundle member: {member.name}")
                total += member.size
                if total > _MAX_BUNDLE_BYTES:
                    raise CustodyError("state bundle exceeds size limit")
                handle = archive.extractfile(member)
                if handle is None:
                    raise CustodyError(f"cannot read bundle member: {member.name}")
                payloads[member.name] = handle.read()
    except (OSError, tarfile.TarError) as exc:
        raise CustodyError(f"invalid state bundle: {exc}") from exc
    try:
        manifest = json.loads(payloads.pop("manifest.json").decode())
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CustodyError(f"state bundle has no valid manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != BUNDLE_SCHEMA:
        raise CustodyError("unsupported state bundle manifest")
    identity = content_id(
        {key: value for key, value in manifest.items() if key != "bundle_id"}
    )
    if manifest.get("bundle_id") != identity:
        raise CustodyError("state bundle identity mismatch")
    expected_paths = {f"state/{entry['path']}" for entry in manifest.get("files", [])}
    if set(payloads) != expected_paths:
        raise CustodyError("state bundle file set differs from its manifest")
    normalized: dict[str, bytes] = {}
    for entry in manifest["files"]:
        relative = str(entry["path"])
        payload = payloads[f"state/{relative}"]
        if len(payload) != entry["bytes"] or f"sha256:{_sha256_bytes(payload)}" != entry["sha256"]:
            raise CustodyError(f"state bundle digest mismatch: {relative}")
        normalized[relative] = payload
    return manifest, normalized


def _schema_counts(files: list[Path]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in files:
        if path.suffix != ".json":
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(raw, dict) and isinstance(raw.get("schema"), str):
            schema = raw["schema"]
            counts[schema] = counts.get(schema, 0) + 1
    return dict(sorted(counts.items()))


def _referenced_package_digests() -> set[str]:
    referenced: set[str] = set()
    lock_root = paths.surface_locks_dir()
    if lock_root.is_dir():
        for target in sorted(lock_root.glob("*.json")):
            raw = json.loads(target.read_text(encoding="utf-8"))
            lock = SurfaceLock.from_dict(raw)
            referenced.update(item.package_digest for item in lock.projections)
    adoption_root = paths.adoption_receipts_dir()
    if adoption_root.is_dir():
        for record in maintenance.AdoptionStore().list():
            referenced.add(record.package_digest)
    return referenced


def _load_locks(blockers: list[str]) -> dict[str, SurfaceLock]:
    result: dict[str, SurfaceLock] = {}
    root = paths.surface_locks_dir()
    if not root.is_dir():
        return result
    for target in sorted(root.glob("*.json")):
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            lock = SurfaceLock.from_dict(raw)
            if target.stem != lock.surface_id.removeprefix("sha256:"):
                raise LifecycleError("surface lock filename mismatch")
            result[lock.surface_id] = lock
        except (OSError, json.JSONDecodeError, LifecycleError) as exc:
            blockers.append(f"invalid surface lock {target}: {exc}")
    return result


def _recover_ownership(
    locks: dict[str, SurfaceLock], blockers: list[str]
) -> dict[str, dict[str, Any]]:
    records: list[OwnershipRecord] = []
    root = paths.ownership_receipts_dir()
    if root.is_dir():
        for target in sorted(root.glob("*.json")):
            try:
                raw = json.loads(target.read_text(encoding="utf-8"))
                record = OwnershipRecord.from_dict(raw)
                if target.stem != record.ownership_id.removeprefix("sha256:"):
                    raise LifecycleError("ownership receipt filename mismatch")
                records.append(record)
            except (OSError, json.JSONDecodeError, LifecycleError) as exc:
                blockers.append(f"invalid ownership receipt {target}: {exc}")
    result: dict[str, dict[str, Any]] = {}
    for sid, lock in locks.items():
        entries: dict[str, str] = {}
        for projection in lock.projections:
            matches = [
                record
                for record in records
                if record.surface_id == sid
                and record.projection_path == projection.projection_path
                and record.source_path == projection.source_path
                and record.source_digest == projection.source_digest
                and record.package_digest == projection.package_digest
            ]
            if len(matches) != 1:
                blockers.append(
                    f"expected projection lacks unique ownership receipt: {projection.projection_path}"
                )
                continue
            entries[projection.projection_path] = matches[0].ownership_id
        result[sid] = {
            "schema": "spindle.ownership-index/v1",
            "surface_id": sid,
            "entries": dict(sorted(entries.items())),
        }
    return result


def _recover_maintenance(blockers: list[str]) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    root = paths.maintenance_events_dir()
    if root.is_dir():
        for target in sorted(root.glob("*.json")):
            try:
                raw = json.loads(target.read_text(encoding="utf-8"))
                identity = content_id(
                    {key: value for key, value in raw.items() if key != "event_id"}
                )
                if raw.get("schema") != maintenance.MAINTENANCE_EVENT_SCHEMA or raw.get("event_id") != identity or target.stem != identity[7:]:
                    raise CustodyError("maintenance event identity mismatch")
                events.append(raw)
            except (OSError, json.JSONDecodeError, CustodyError) as exc:
                blockers.append(f"invalid maintenance event {target}: {exc}")
    surfaces: dict[str, Any] = {}
    status_map = {
        "adopt": "active",
        "update-promote": "active",
        "rollback": "active",
        "disable": "disabled",
        "enable": "active",
        "deprecate": "deprecated",
        "retire": "retired",
    }
    for event in sorted(events, key=lambda item: (str(item["observed_at"]), str(item["event_id"]))):
        skill = surfaces.setdefault(event["surface_id"], {"skills": {}})["skills"]
        skill[event["skill"]] = {
            "status": status_map[event["operation"]],
            "adoption_id": event["adoption_id"],
            "previous_adoption_id": event.get("previous_adoption_id"),
            "event_id": event["event_id"],
            "reason": event["reason"],
        }
    return {"schema": maintenance.MAINTENANCE_INDEX_SCHEMA, "surfaces": surfaces}


def _recover_quarantine(blockers: list[str]) -> dict[str, Any]:
    by_package: dict[str, dict[str, dict[str, Any]]] = {}
    root = paths.quarantine_events_dir()
    if root.is_dir():
        for target in sorted(root.glob("*.json")):
            try:
                raw = json.loads(target.read_text(encoding="utf-8"))
                event = trust.QuarantineEvent(
                    package_digest=str(raw["package_digest"]),
                    action=str(raw["action"]),
                    reason=str(raw["reason"]),
                    actor=str(raw["actor"]),
                    effective_at=str(raw["effective_at"]),
                    previous_event_id=(str(raw["previous_event_id"]) if raw.get("previous_event_id") else None),
                )
                if raw.get("event_id") != event.event_id or target.stem != event.event_id[7:]:
                    raise CustodyError("quarantine event identity mismatch")
                by_package.setdefault(event.package_digest, {})[event.event_id] = raw
            except (KeyError, OSError, json.JSONDecodeError, LifecycleError, CustodyError) as exc:
                blockers.append(f"invalid quarantine event {target}: {exc}")
    packages: dict[str, Any] = {}
    for package, events in by_package.items():
        referenced = {item["previous_event_id"] for item in events.values() if item.get("previous_event_id")}
        if not referenced.issubset(events):
            blockers.append(f"quarantine history for {package} has a missing predecessor")
            continue
        terminal = [item for identity, item in events.items() if identity not in referenced]
        if len(terminal) != 1:
            blockers.append(f"quarantine history for {package} is branched")
            continue
        event = terminal[0]
        packages[package] = {
            "status": "quarantined" if event["action"] == "quarantine" else "available",
            "event_id": event["event_id"],
            "reason": event["reason"],
        }
    return {"schema": trust.QUARANTINE_INDEX_SCHEMA, "packages": packages}


def _recover_hooks(blockers: list[str], warnings: list[str]) -> dict[str, Any]:
    candidates: dict[str, list[hooks.HookInstallReceipt]] = {}
    root = paths.hook_receipts_dir()
    if root.is_dir():
        for target in sorted(root.glob("*.json")):
            try:
                raw = json.loads(target.read_text(encoding="utf-8"))
                receipt = hooks.HookInstallReceipt.from_dict(raw)
                if target.stem != receipt.receipt_id[7:]:
                    raise CustodyError("hook receipt filename mismatch")
                candidates.setdefault(receipt.target_path, []).append(receipt)
            except (OSError, json.JSONDecodeError, LifecycleError, CustodyError) as exc:
                blockers.append(f"invalid hook receipt {target}: {exc}")
    entries: dict[str, str] = {}
    for target_path, receipts in candidates.items():
        target = Path(target_path)
        if target.is_symlink() or not target.is_file():
            warnings.append(f"hook target absent during recovery: {target}")
            continue
        try:
            current = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            blockers.append(f"invalid hook target {target}: {exc}")
            continue
        matches = [receipt for receipt in receipts if _hook_fragments_present(current, receipt)]
        if not matches:
            warnings.append(f"no hook receipt exactly matches current target: {target}")
            continue
        matches.sort(key=lambda item: (len(item.fragments), item.receipt_id))
        entries[target_path] = matches[-1].receipt_id
    return {"schema": hooks.HOOK_INDEX_SCHEMA, "entries": dict(sorted(entries.items()))}


def _hook_fragments_present(current: Any, receipt: hooks.HookInstallReceipt) -> bool:
    if not isinstance(current, dict) or not isinstance(current.get("hooks"), dict):
        return False
    for fragment in receipt.fragments:
        groups = current["hooks"].get(fragment.event)
        if not isinstance(groups, list) or fragment.group not in groups:
            return False
    return True


def _tree_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file() and not item.is_symlink())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_bytes_exclusive(path: Path, payload: bytes) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise CustodyError(f"state import target appeared during apply: {path}") from exc
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    _write_bytes_atomic(path, encoded)


def _write_json_immutable(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    if path.exists():
        if path.is_symlink() or path.read_bytes() != encoded:
            raise CustodyError(f"hardening receipt collision at {path}")
        return
    _write_bytes_exclusive(path, encoded)


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
