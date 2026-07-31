"""Ownership-safe native startup hook kits for Claude Code and Codex."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import tomllib
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths
from .lifecycle import LifecycleError, content_id
from .startup import SurfaceMutex, latest_startup_receipt

HOOK_INSTALL_RECEIPT_SCHEMA = "spindle.hook-install-receipt/v1"
HOOK_INDEX_SCHEMA = "spindle.hook-index/v1"
HOOK_PLAN_SCHEMA = "spindle.hook-plan/v1"


@dataclass(frozen=True)
class HookFragment:
    event: str
    group: dict[str, Any]

    @property
    def fragment_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {"event": self.event, "group": self.group}
        return {"fragment_id": self.fragment_id, **payload} if include_id else payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> HookFragment:
        group = raw.get("group")
        if not isinstance(group, dict):
            raise LifecycleError("hook fragment group must be an object")
        fragment = cls(event=str(raw["event"]), group=group)
        if raw.get("fragment_id") not in {None, fragment.fragment_id}:
            raise LifecycleError("hook fragment content does not match fragment_id")
        return fragment


@dataclass(frozen=True)
class HookInstallReceipt:
    repo_path: str
    harness: str
    scope: str
    target_path: str
    created_file: bool
    fragments: tuple[HookFragment, ...]
    creation_plan_id: str
    owner: str = "spindle"

    @property
    def receipt_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": HOOK_INSTALL_RECEIPT_SCHEMA,
            "repo_path": self.repo_path,
            "harness": self.harness,
            "scope": self.scope,
            "target_path": self.target_path,
            "created_file": self.created_file,
            "fragments": [fragment.to_dict() for fragment in self.fragments],
            "creation_plan_id": self.creation_plan_id,
            "owner": self.owner,
        }
        return {"receipt_id": self.receipt_id, **payload} if include_id else payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> HookInstallReceipt:
        if raw.get("schema") != HOOK_INSTALL_RECEIPT_SCHEMA:
            raise LifecycleError("unsupported hook install receipt schema")
        fragments = raw.get("fragments")
        if not isinstance(fragments, list):
            raise LifecycleError("hook install receipt fragments must be a list")
        receipt = cls(
            repo_path=str(raw["repo_path"]),
            harness=str(raw["harness"]),
            scope=str(raw["scope"]),
            target_path=str(raw["target_path"]),
            created_file=bool(raw["created_file"]),
            fragments=tuple(HookFragment.from_dict(item) for item in fragments),
            creation_plan_id=str(raw["creation_plan_id"]),
            owner=str(raw["owner"]),
        )
        if receipt.owner != "spindle":
            raise LifecycleError("hook install receipt owner must be spindle")
        if raw.get("receipt_id") not in {None, receipt.receipt_id}:
            raise LifecycleError("hook receipt content does not match receipt_id")
        return receipt


@dataclass(frozen=True)
class HookPlan:
    repo_path: str
    harness: str
    scope: str
    target_path: str
    current_digest: str
    proposed_digest: str
    proposed: dict[str, Any]
    additions: tuple[HookFragment, ...]
    owned: tuple[HookFragment, ...]
    foreign_present: tuple[HookFragment, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    target_existed: bool

    @property
    def plan_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": HOOK_PLAN_SCHEMA,
            "repo_path": self.repo_path,
            "harness": self.harness,
            "scope": self.scope,
            "target_path": self.target_path,
            "current_digest": self.current_digest,
            "proposed_digest": self.proposed_digest,
            "proposed": self.proposed,
            "additions": [fragment.to_dict() for fragment in self.additions],
            "owned": [fragment.to_dict() for fragment in self.owned],
            "foreign_present": [
                fragment.to_dict() for fragment in self.foreign_present
            ],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "target_existed": self.target_existed,
        }
        return {"plan_id": self.plan_id, **payload} if include_id else payload


@dataclass(frozen=True)
class HookApplyResult:
    plan: HookPlan
    action: str
    receipt: HookInstallReceipt | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "action": self.action,
            "ownership": self.receipt.to_dict() if self.receipt is not None else None,
        }


class HookOwnershipStore:
    def __init__(
        self, *, receipt_root: Path | None = None, index_file: Path | None = None
    ) -> None:
        self.receipt_root = receipt_root or paths.hook_receipts_dir()
        self.index_file = index_file or paths.hook_index_file()

    def get(self, target: str | Path) -> HookInstallReceipt | None:
        key = str(Path(target).absolute())
        index = self._read_index()
        receipt_id = index.get(key)
        if receipt_id is None:
            return None
        receipt_path = self.receipt_root / f"{_digest_hex(receipt_id)}.json"
        try:
            raw = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LifecycleError(f"invalid hook ownership receipt: {exc}") from exc
        receipt = HookInstallReceipt.from_dict(raw)
        if receipt.receipt_id != receipt_id or receipt.target_path != key:
            raise LifecycleError("hook ownership index does not match its receipt")
        return receipt

    def record(self, receipt: HookInstallReceipt) -> Path:
        self.receipt_root.mkdir(parents=True, exist_ok=True)
        target = self.receipt_root / f"{_digest_hex(receipt.receipt_id)}.json"
        _write_immutable(target, receipt.to_dict())
        index = self._read_index()
        index[receipt.target_path] = receipt.receipt_id
        self._write_index(index)
        return target

    def forget(self, target: str | Path, receipt_id: str) -> bool:
        key = str(Path(target).absolute())
        index = self._read_index()
        if index.get(key) != receipt_id:
            return False
        del index[key]
        self._write_index(index)
        return True

    def _read_index(self) -> dict[str, str]:
        if not self.index_file.exists():
            return {}
        try:
            raw = json.loads(self.index_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LifecycleError(f"invalid hook ownership index: {exc}") from exc
        if raw.get("schema") != HOOK_INDEX_SCHEMA or not isinstance(
            raw.get("entries"), dict
        ):
            raise LifecycleError("invalid hook ownership index schema")
        return {str(key): str(value) for key, value in raw["entries"].items()}

    def _write_index(self, entries: dict[str, str]) -> None:
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(
            self.index_file,
            {"schema": HOOK_INDEX_SCHEMA, "entries": dict(sorted(entries.items()))},
        )


def desired_fragments(harness: str) -> tuple[HookFragment, ...]:
    if harness == "claude":
        return tuple(
            HookFragment(
                event=event,
                group={
                    "hooks": [
                        {
                            "type": "command",
                            "command": "spindle",
                            "args": [
                                "bootstrap",
                                "--hook",
                                "claude",
                                "--event",
                                event,
                            ],
                            "timeout": 10,
                        }
                    ]
                },
            )
            for event in ("SessionStart", "Setup", "SubagentStart")
        )
    if harness == "codex":
        return tuple(
            HookFragment(
                event=event,
                group={
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"spindle bootstrap --hook codex --event {event}",
                            "timeout": 10,
                            "additionalContextLimit": 5000,
                        }
                    ]
                },
            )
            for event in ("SessionStart", "SubagentStart")
        )
    raise LifecycleError(f"native hook adapter is unavailable for {harness!r}")


def plan_hooks(
    repo_path: str | Path,
    harness: str,
    *,
    scope: str = "repo",
    home: Path | None = None,
    ownership_store: HookOwnershipStore | None = None,
) -> HookPlan:
    repo = Path(repo_path).resolve()
    target = _hook_target(repo, harness, scope, home=home)
    target_existed = target.exists()
    current = _read_json_object(target)
    proposed = json.loads(json.dumps(current))
    if harness == "codex" and not proposed:
        proposed["description"] = "Spindle session-local skill bootstrap."
    hooks = proposed.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise LifecycleError(f"hooks at {target} must be an object")
    store = ownership_store or HookOwnershipStore()
    receipt = store.get(target)
    owned_receipt_fragments = receipt.fragments if receipt is not None else ()
    additions: list[HookFragment] = []
    owned: list[HookFragment] = []
    foreign: list[HookFragment] = []
    blockers: list[str] = []
    warnings = _hook_control_warnings(repo, harness, scope, home=home)

    for prior in owned_receipt_fragments:
        if not _group_present(current, prior):
            blockers.append(
                f"owned {prior.event} hook fragment changed or disappeared; preserve and repair custody explicitly"
            )

    for fragment in desired_fragments(harness):
        if fragment in owned_receipt_fragments and _group_present(current, fragment):
            owned.append(fragment)
            continue
        handler = fragment.group["hooks"][0]
        if _handler_present(current, fragment.event, handler):
            foreign.append(fragment)
            continue
        event_groups = hooks.setdefault(fragment.event, [])
        if not isinstance(event_groups, list):
            raise LifecycleError(
                f"hook event {fragment.event} at {target} must be a list"
            )
        event_groups.append(fragment.group)
        additions.append(fragment)

    if harness == "codex" and scope == "repo" and _codex_has_inline_hooks(repo):
        blockers.append(
            "repo .codex/config.toml already defines inline hooks; adding hooks.json at the same layer would produce a harness warning"
        )
    current_digest = content_id(current)
    return HookPlan(
        repo_path=str(repo),
        harness=harness,
        scope=scope,
        target_path=str(target.absolute()),
        current_digest=current_digest,
        proposed_digest=content_id(proposed),
        proposed=proposed,
        additions=tuple(additions),
        owned=tuple(owned),
        foreign_present=tuple(foreign),
        blockers=tuple(sorted(set(blockers))),
        warnings=tuple(sorted(set(warnings))),
        target_existed=target_existed,
    )


def install_hooks(
    repo_path: str | Path,
    harness: str,
    *,
    scope: str = "repo",
    dry_run: bool = False,
    home: Path | None = None,
    ownership_store: HookOwnershipStore | None = None,
) -> HookApplyResult:
    store = ownership_store or HookOwnershipStore()
    guard = (
        nullcontext()
        if dry_run
        else SurfaceMutex(
            content_id("spindle-hook-ownership-index"),
            root=paths.startup_locks_dir() / "hook-management",
        )
    )
    with guard:
        plan = plan_hooks(
            repo_path,
            harness,
            scope=scope,
            home=home,
            ownership_store=store,
        )
        if plan.blockers:
            return HookApplyResult(plan, "blocked", store.get(plan.target_path))
        if dry_run:
            return HookApplyResult(
                plan,
                "would-install" if plan.additions else "no-change",
                store.get(plan.target_path),
            )
        if not plan.additions:
            return HookApplyResult(plan, "no-change", store.get(plan.target_path))
        target = Path(plan.target_path)
        if content_id(_read_json_object(target)) != plan.current_digest:
            raise LifecycleError("hook configuration changed after planning")
        _atomic_json(target, plan.proposed)
        prior = store.get(target)
        prior_fragments = prior.fragments if prior is not None else ()
        fragments = tuple(
            sorted(
                {
                    fragment.fragment_id: fragment
                    for fragment in prior_fragments + plan.additions
                }.values(),
                key=lambda fragment: (fragment.event, fragment.fragment_id),
            )
        )
        receipt = HookInstallReceipt(
            repo_path=plan.repo_path,
            harness=harness,
            scope=scope,
            target_path=plan.target_path,
            created_file=(
                prior.created_file if prior is not None else not plan.target_existed
            ),
            fragments=fragments,
            creation_plan_id=plan.plan_id,
        )
        store.record(receipt)
        return HookApplyResult(plan, "installed", receipt)


def remove_hooks(
    repo_path: str | Path,
    harness: str,
    *,
    scope: str = "repo",
    dry_run: bool = False,
    home: Path | None = None,
    ownership_store: HookOwnershipStore | None = None,
) -> HookApplyResult:
    store = ownership_store or HookOwnershipStore()
    guard = (
        nullcontext()
        if dry_run
        else SurfaceMutex(
            content_id("spindle-hook-ownership-index"),
            root=paths.startup_locks_dir() / "hook-management",
        )
    )
    with guard:
        target = _hook_target(Path(repo_path).resolve(), harness, scope, home=home)
        receipt = store.get(target)
        plan = plan_hooks(
            repo_path,
            harness,
            scope=scope,
            home=home,
            ownership_store=store,
        )
        if receipt is None:
            return HookApplyResult(plan, "not-owned", None)
        current = _read_json_object(target)
        missing = [
            fragment
            for fragment in receipt.fragments
            if not _group_present(current, fragment)
        ]
        if missing:
            return HookApplyResult(plan, "blocked:ownership-mismatch", receipt)
        if dry_run:
            return HookApplyResult(plan, "would-remove", receipt)

        proposed = json.loads(json.dumps(current))
        hooks = proposed.get("hooks")
        assert isinstance(hooks, dict)
        for fragment in receipt.fragments:
            groups = hooks[fragment.event]
            groups.remove(fragment.group)
            if not groups:
                del hooks[fragment.event]
        if not hooks:
            del proposed["hooks"]
        if receipt.created_file and _only_spindle_scaffold(proposed, harness):
            target.unlink()
        else:
            _atomic_json(target, proposed)
        if not store.forget(target, receipt.receipt_id):
            raise LifecycleError("hook ownership index changed during removal")
        return HookApplyResult(plan, "removed", receipt)


def hook_status(
    repo_path: str | Path,
    harness: str,
    *,
    scope: str = "repo",
    home: Path | None = None,
    ownership_store: HookOwnershipStore | None = None,
) -> dict[str, Any]:
    plan = plan_hooks(
        repo_path,
        harness,
        scope=scope,
        home=home,
        ownership_store=ownership_store,
    )
    heartbeat = _latest_heartbeat(Path(repo_path).resolve(), harness)
    control_blockers = tuple(
        warning for warning in plan.warnings if _is_hook_control_blocker(warning)
    )
    heartbeat_decision = heartbeat.get("decision") if heartbeat is not None else None
    heartbeat_blockers: tuple[str, ...] = ()
    if heartbeat_decision in {"blocked", "restart-required"}:
        heartbeat_blockers = (
            f"latest native hook heartbeat decision is {heartbeat_decision}",
        )
    if plan.blockers or control_blockers or heartbeat_decision == "blocked":
        state = "blocked"
    elif heartbeat_decision == "restart-required":
        state = "restart-required"
    elif plan.additions and plan.foreign_present:
        state = "partial-foreign"
    elif plan.additions:
        state = "missing"
    elif plan.foreign_present and not plan.owned:
        state = "foreign-present"
    elif heartbeat_decision == "warn":
        state = "observed-warn"
    elif heartbeat is not None:
        state = "observed"
    else:
        state = "configured-unverified"
    return {
        "harness": harness,
        "scope": scope,
        "target_path": plan.target_path,
        "state": state,
        "owned_events": [fragment.event for fragment in plan.owned],
        "missing_events": [fragment.event for fragment in plan.additions],
        "foreign_present_events": [fragment.event for fragment in plan.foreign_present],
        "blockers": [*plan.blockers, *control_blockers, *heartbeat_blockers],
        "warnings": list(plan.warnings),
        "heartbeat": heartbeat,
        "plan_id": plan.plan_id,
    }


def _hook_target(repo: Path, harness: str, scope: str, *, home: Path | None) -> Path:
    if scope not in {"repo", "user"}:
        raise LifecycleError(f"unsupported hook scope: {scope}")
    base = repo if scope == "repo" else (home or Path.home()).resolve()
    if harness == "claude":
        return base / ".claude" / "settings.json"
    if harness == "codex":
        return base / ".codex" / "hooks.json"
    raise LifecycleError(f"native hook adapter is unavailable for {harness!r}")


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError(
            f"invalid JSON hook configuration at {path}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise LifecycleError(f"hook configuration at {path} must be an object")
    return raw


def _event_groups(payload: dict[str, Any], event: str) -> list[Any]:
    hooks = payload.get("hooks")
    if not isinstance(hooks, dict):
        return []
    groups = hooks.get(event)
    return groups if isinstance(groups, list) else []


def _group_present(payload: dict[str, Any], fragment: HookFragment) -> bool:
    return fragment.group in _event_groups(payload, fragment.event)


def _handler_present(payload: dict[str, Any], event: str, desired: dict) -> bool:
    for group in _event_groups(payload, event):
        if not isinstance(group, dict):
            continue
        handlers = group.get("hooks")
        if isinstance(handlers, list) and desired in handlers:
            return True
    return False


def _codex_has_inline_hooks(repo: Path) -> bool:
    config = repo / ".codex" / "config.toml"
    if not config.is_file():
        return False
    try:
        raw = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    return isinstance(raw.get("hooks"), dict)


def _hook_control_warnings(
    repo: Path, harness: str, scope: str, *, home: Path | None
) -> list[str]:
    user_home = (home or Path.home()).resolve()
    warnings: list[str] = []
    if harness == "claude":
        for config in (
            user_home / ".claude" / "settings.json",
            repo / ".claude" / "settings.json",
            repo / ".claude" / "settings.local.json",
            Path("/etc/claude-code/managed-settings.json"),
        ):
            if not config.is_file():
                continue
            try:
                raw = json.loads(config.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                warnings.append(f"cannot verify invalid Claude settings at {config}")
                continue
            if isinstance(raw, dict) and raw.get("disableAllHooks") is True:
                warnings.append(f"Claude hooks are disabled by {config}")
            if (
                scope != "managed"
                and isinstance(raw, dict)
                and raw.get("allowManagedHooksOnly") is True
            ):
                warnings.append(f"Claude permits only managed hooks via {config}")
    elif harness == "codex":
        for config in (
            user_home / ".codex" / "config.toml",
            repo / ".codex" / "config.toml",
        ):
            if not config.is_file():
                continue
            try:
                raw = tomllib.loads(config.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                warnings.append(f"cannot verify invalid Codex config at {config}")
                continue
            features = raw.get("features")
            if isinstance(features, dict) and features.get("hooks") is False:
                warnings.append(f"Codex hooks are disabled by {config}")
            if raw.get("allow_managed_hooks_only") is True:
                warnings.append(f"Codex permits only managed hooks via {config}")
    warnings.append(
        "definition presence does not prove harness trust; verify with the harness hook inspector or a startup heartbeat"
    )
    if shutil.which("spindle") is None:
        warnings.append("stable hook command 'spindle' is not available on PATH")
    return warnings


def _is_hook_control_blocker(warning: str) -> bool:
    return any(
        marker in warning
        for marker in (
            "hooks are disabled by",
            "permits only managed hooks via",
            "not available on PATH",
        )
    )


def _latest_heartbeat(repo: Path, harness: str) -> dict[str, Any] | None:
    raw = latest_startup_receipt(repo, harness, prelaunch=False)
    if raw is None:
        return None
    return {
        "receipt_id": raw.get("receipt_id"),
        "event_source": raw.get("event_source"),
        "decision": raw.get("decision"),
    }


def _only_spindle_scaffold(payload: dict[str, Any], harness: str) -> bool:
    if harness == "claude":
        return payload == {}
    return payload in ({}, {"description": "Spindle session-local skill bootstrap."})


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        Path(temporary).unlink(missing_ok=True)
        raise


def _write_immutable(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != serialized:
            raise LifecycleError(f"content-addressed hook receipt collision at {path}")
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(serialized)
        handle.flush()
        os.fsync(handle.fileno())


def _digest_hex(identity: str) -> str:
    prefix, separator, value = identity.partition(":")
    if separator != ":" or prefix != "sha256" or len(value) != 64:
        raise LifecycleError(f"invalid content identity: {identity}")
    return value
