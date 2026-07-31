"""Harness-native operator skill and compact in-session control contract.

The bundled ``spindle`` skill is intentionally small.  It asks this module for
current lifecycle facts and command templates instead of carrying a second,
quickly stale copy of the CLI manual in model context.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from . import __version__, hooks, inventory, leases, maintenance, materialize, paths
from .composition import ComposedSkill, Composition
from .lifecycle import (
    ExpectedProjection,
    LifecycleError,
    OwnershipStore,
    PackageRevision,
    SurfaceLock,
    cache_package,
    digest_path,
    read_surface_lock,
    surface_id,
    write_surface_lock,
)
from .startup import SurfaceMutex, latest_startup_receipt, plan_startup, run_startup

HARNESS_CONTEXT_SCHEMA = "spindle.harness-context/v1"
OPERATOR_PLAN_SCHEMA = "spindle.operator-plan/v1"
OPERATOR_AUTHORITY_PREFIX = "operator:spindle:"
SUPPORTED_HARNESSES = ("claude", "codex")


@dataclass(frozen=True)
class OperatorPlan:
    repo_path: str
    harness: str
    current_lock_id: str | None
    proposed_lock: SurfaceLock
    projection: ExpectedProjection
    action: str
    blockers: tuple[str, ...]
    hook_plan: hooks.HookPlan

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": OPERATOR_PLAN_SCHEMA,
            "repo_path": self.repo_path,
            "harness": self.harness,
            "current_lock_id": self.current_lock_id,
            "proposed_lock": self.proposed_lock.to_dict(),
            "projection": self.projection.to_dict(),
            "action": self.action,
            "blockers": list(self.blockers),
            "hook_plan": self.hook_plan.to_dict(),
            "workspace": _workspace_guidance(
                self.projection.projection_path,
                self.hook_plan.target_path,
            ),
            "requires_new_session": not self.blockers
            and (
                self.action != "no-change" or bool(self.hook_plan.additions)
            ),
        }


def bundled_skill_path() -> Path:
    target = Path(__file__).parent / "builtin" / "skills" / "spindle"
    if target.is_symlink() or not (target / "SKILL.md").is_file():
        raise LifecycleError("installed Spindle package lacks its operator skill")
    return target


def operator_revision() -> PackageRevision:
    source = bundled_skill_path()
    return PackageRevision.from_path(
        "spindle-operator",
        __version__,
        source,
        editable=False,
        skills=(("spindle", source),),
    )


def detect_harness(
    explicit: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    repo_path: str | Path = ".",
) -> tuple[str, str]:
    if explicit is not None:
        if explicit not in SUPPORTED_HARNESSES:
            raise LifecycleError(f"unsupported harness: {explicit!r}")
        return explicit, "explicit"

    env = environ if environ is not None else os.environ
    detected: list[tuple[str, str]] = []
    if any(env.get(key) for key in ("CODEX_THREAD_ID", "CODEX_CI")):
        detected.append(("codex", "environment"))
    if any(
        env.get(key)
        for key in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_PROJECT_DIR")
    ):
        detected.append(("claude", "environment"))
    names = {name for name, _source in detected}
    if len(names) == 1:
        return detected[0]
    if len(names) > 1:
        process_harness = _detect_process_harness()
        if process_harness in names:
            return process_harness, "process-tree"
        raise LifecycleError(
            "both Codex and Claude Code environment markers are present; pass --harness"
        )

    repo = Path(repo_path).resolve()
    installed = [
        harness
        for harness in SUPPORTED_HARNESSES
        if _operator_projection(read_surface_lock(surface_id(repo, harness))) is not None
    ]
    if len(installed) == 1:
        return installed[0], "surface-lock"
    raise LifecycleError(
        "cannot determine the active harness; pass --harness codex or --harness claude"
    )


def plan_operator(
    repo_path: str | Path,
    harness: str,
    *,
    surface_name: str | None = None,
    home: Path | None = None,
) -> OperatorPlan:
    repo = _repo(repo_path)
    _require_harness(harness)
    revision = operator_revision()
    skill_digest = dict(revision.skill_digests)["spindle"]
    cached_source = (
        paths.package_cache_dir()
        / revision.content_digest.removeprefix("sha256:")
        / revision.name
    )
    target = materialize.target_dir(repo, harness) / "spindle"
    projection = ExpectedProjection(
        skill="spindle",
        projection_path=str(target.absolute()),
        source_path=str(cached_source.absolute()),
        source_digest=skill_digest,
        package_digest=revision.content_digest,
        authority=f"{OPERATOR_AUTHORITY_PREFIX}{__version__}",
    )
    current = read_surface_lock(surface_id(repo, harness))
    base = current or SurfaceLock(
        surface_id=surface_id(repo, harness),
        surface_name=surface_name or repo.name,
        repo_path=str(repo),
        harness=harness,
        binding_coordinate="operator-only/v1",
        projections=(),
    )
    proposed, blockers = _lock_with_operator(base, projection)
    current_operator = _operator_projection(current)
    if blockers:
        action = "blocked"
    elif current_operator is None:
        action = "install"
    elif current_operator == projection:
        action = "no-change"
    else:
        action = "update"

    ownership = OwnershipStore().records(base.surface_id)
    record = ownership.get(projection.projection_path)
    target_path = Path(projection.projection_path)
    if target_path.exists() or target_path.is_symlink():
        if record is None or not record.matches_symlink(target_path):
            blockers.append(
                "operator target is foreign or its ownership proof no longer matches: "
                + projection.projection_path
            )
    hook_plan = hooks.plan_hooks(
        repo,
        harness,
        scope="repo",
        home=home,
    )
    return OperatorPlan(
        repo_path=str(repo),
        harness=harness,
        current_lock_id=current.lock_id if current is not None else None,
        proposed_lock=proposed,
        projection=projection,
        action="blocked" if blockers else action,
        blockers=tuple(sorted(set(blockers))),
        hook_plan=hook_plan,
    )


def setup_operator(
    repo_path: str | Path,
    harness: str,
    *,
    surface_name: str | None = None,
    dry_run: bool = False,
    home: Path | None = None,
) -> dict[str, Any]:
    plan = plan_operator(
        repo_path,
        harness,
        surface_name=surface_name,
        home=home,
    )
    if plan.blockers or dry_run:
        action = (
            "blocked"
            if plan.blockers
            else "no-change"
            if plan.action == "no-change"
            else f"would-{plan.action}"
        )
        return {
            "action": action,
            "plan": plan.to_dict(),
            "startup": None,
            "hooks": None,
            "requires_new_session": not bool(plan.blockers),
        }

    revision = operator_revision()
    cached = cache_package(revision)
    if str(cached.absolute()) != plan.projection.source_path:
        raise LifecycleError("operator cache path differs from its plan")
    if digest_path(cached) != plan.projection.source_digest:
        raise LifecycleError("operator cache digest differs from its plan")

    with SurfaceMutex(plan.proposed_lock.surface_id):
        _assert_current_lock(plan)
        actions = materialize.materialize(
            Composition(
                surface=plan.proposed_lock.surface_name,
                autonomy_mode="deterministic",
                skills=[
                    ComposedSkill(
                        name="spindle",
                        command="$spindle" if harness == "codex" else "/spindle",
                        scope="repo",
                        source="spindle-operator",
                        source_dir=str(cached),
                        package_name=revision.name,
                        package_version=revision.version,
                        package_digest=revision.content_digest,
                    )
                ],
            ),
            plan.repo_path,
            harness,
            previous=set(),
            creation_receipt_id=f"operator:{plan.proposed_lock.lock_id}",
            package_digests={"spindle": revision.content_digest},
        )
        if not actions or actions[0][1].startswith("skipped:"):
            return {
                "action": "blocked",
                "plan": plan.to_dict(),
                "projection_actions": actions,
                "startup": None,
                "hooks": None,
                "requires_new_session": False,
            }
        write_surface_lock(plan.proposed_lock)
    startup = run_startup(
        plan.repo_path,
        harness,
        reconcile_owned=True,
        surface_name=plan.proposed_lock.surface_name,
        event_source="pre-launch",
        home=home,
    )
    hook_result = hooks.install_hooks(
        plan.repo_path,
        harness,
        scope="repo",
        home=home,
    )
    action = plan.action if hook_result.action != "blocked" else "partial"
    return {
        "action": action,
        "plan": plan.to_dict(),
        "projection_actions": actions,
        "startup": _startup_dict(startup),
        "hooks": hook_result.to_dict(),
        "operator_ready": True,
        "surface_ready": startup.receipt.decision in {"ok", "warn"},
        "requires_new_session": plan.action != "no-change"
        or hook_result.action == "installed",
    }


def remove_operator(
    repo_path: str | Path,
    harness: str,
    *,
    dry_run: bool = False,
    home: Path | None = None,
) -> dict[str, Any]:
    repo = _repo(repo_path)
    _require_harness(harness)
    sid = surface_id(repo, harness)
    current = read_surface_lock(sid)
    operator = _operator_projection(current)
    hook_probe = hooks.remove_hooks(
        repo,
        harness,
        scope="repo",
        dry_run=True,
        home=home,
    )
    if hook_probe.action.startswith("blocked"):
        return {
            "action": "blocked",
            "operator": operator.to_dict() if operator else None,
            "startup": None,
            "hooks": hook_probe.to_dict(),
            "requires_new_session": False,
        }
    if current is None or operator is None:
        if dry_run:
            return {
                "action": "would-remove-hooks"
                if hook_probe.action == "would-remove"
                else "not-installed",
                "operator": None,
                "startup": None,
                "hooks": hook_probe.to_dict(),
                "requires_new_session": hook_probe.action == "would-remove",
            }
        hook_result = hooks.remove_hooks(
            repo,
            harness,
            scope="repo",
            home=home,
        )
        return {
            "action": "removed-hooks"
            if hook_result.action == "removed"
            else "not-installed",
            "operator": None,
            "startup": None,
            "hooks": hook_result.to_dict(),
            "requires_new_session": hook_result.action == "removed",
        }

    proposed = _lock_without_operator(current)
    startup_plan = plan_startup(
        repo,
        harness,
        surface_name=current.surface_name,
        event_source="operator-remove-plan",
        lock=proposed,
        home=home,
    )
    if dry_run:
        return {
            "action": "would-remove",
            "operator": operator.to_dict(),
            "projection_actions": materialize.materialize(
                Composition(
                    surface=current.surface_name,
                    autonomy_mode="deterministic",
                ),
                repo,
                harness,
                previous={"spindle"},
                dry_run=True,
            ),
            "startup": {"plan": startup_plan.to_dict()},
            "hooks": hook_probe.to_dict(),
            "requires_new_session": True,
        }

    with SurfaceMutex(sid):
        observed = read_surface_lock(sid)
        if observed is None or observed.lock_id != current.lock_id:
            raise LifecycleError("surface lock changed after operator removal planning")
        actions = materialize.materialize(
            Composition(
                surface=current.surface_name,
                autonomy_mode="deterministic",
            ),
            repo,
            harness,
            previous={"spindle"},
        )
        if not actions or any(action.startswith("skipped:") for _, action in actions):
            return {
                "action": "blocked",
                "operator": operator.to_dict(),
                "projection_actions": actions,
                "startup": {"plan": startup_plan.to_dict()},
                "hooks": hook_probe.to_dict(),
                "requires_new_session": False,
            }
        write_surface_lock(proposed)
    startup = run_startup(
        repo,
        harness,
        reconcile_owned=True,
        surface_name=current.surface_name,
        event_source="pre-launch",
        home=home,
    )
    hook_result = hooks.remove_hooks(
        repo,
        harness,
        scope="repo",
        home=home,
    )
    return {
        "action": "removed"
        if hook_result.action in {"removed", "not-owned"}
        else "partial",
        "operator": operator.to_dict(),
        "projection_actions": actions,
        "startup": _startup_dict(startup),
        "hooks": hook_result.to_dict(),
        "operator_ready": False,
        "surface_ready": startup.receipt.decision in {"ok", "warn"},
        "requires_new_session": True,
    }


def operator_status(
    repo_path: str | Path,
    harness: str,
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    repo = _repo(repo_path)
    _require_harness(harness)
    current = read_surface_lock(surface_id(repo, harness))
    projection = _operator_projection(current)
    desired = plan_operator(repo, harness, home=home)
    if desired.blockers:
        state = "blocked"
    elif projection is None:
        state = "missing"
    elif projection.package_digest != desired.projection.package_digest:
        state = "update-available"
    else:
        target = Path(projection.projection_path)
        record = OwnershipStore().records(current.surface_id).get(
            projection.projection_path
        )
        if record is None or not record.matches_symlink(target):
            state = "ownership-mismatch"
        elif (
            not Path(projection.source_path).is_dir()
            or digest_path(Path(projection.source_path)) != projection.source_digest
        ):
            state = "source-mismatch"
        else:
            state = "current"
    return {
        "state": state,
        "spindle_version": __version__,
        "invocation": "$spindle" if harness == "codex" else "/spindle",
        "projection": projection.to_dict() if projection else None,
        "desired_projection": desired.projection.to_dict(),
        "blockers": list(desired.blockers),
        "hooks": hooks.hook_status(repo, harness, scope="repo", home=home),
        "workspace": _workspace_guidance(
            desired.projection.projection_path,
            desired.hook_plan.target_path,
        ),
    }


def harness_context(
    repo_path: str | Path,
    harness: str | None = None,
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    repo = _repo(repo_path)
    selected, detected_by = detect_harness(
        harness,
        environ=environ,
        repo_path=repo,
    )
    sid = surface_id(repo, selected)
    lock = read_surface_lock(sid)
    effective = lock
    active_leases: tuple[str, ...] = ()
    expired_leases: tuple[str, ...] = ()
    if lock is not None and lock.lease_ids:
        effective, active_leases, expired_leases = leases.effective_lock_at(lock)
    observed = inventory.scan_effective_inventory(
        repo,
        selected,
        surface_name=lock.surface_name if lock else None,
        lock=effective,
        home=home,
    )
    blocking = [
        {
            "skill": entry.name,
            "state": entry.state.value,
            "scope": entry.scope,
            "path": entry.path,
            "reason": entry.reason,
        }
        for entry in observed.blocking_entries()
    ]
    adoptions = maintenance.active_adoptions(lock) if lock is not None else ()
    prelaunch = latest_startup_receipt(repo, selected, prelaunch=True)
    operator = operator_status(repo, selected, home=home)
    return {
        "schema": HARNESS_CONTEXT_SCHEMA,
        "surface": {
            "repo_path": str(repo),
            "surface_id": sid,
            "name": lock.surface_name if lock else repo.name,
            "harness": selected,
            "harness_detected_by": detected_by,
            "lock_id": effective.lock_id if effective else None,
            "inventory_id": observed.inventory_id,
        },
        "operator": operator,
        "runtime": {
            "latest_prelaunch": _receipt_summary(prelaunch),
            "hook_state": operator["hooks"]["state"],
            "inventory_counts": observed.counts(),
            "blocking": blocking,
        },
        "custody": {
            "active_leases": list(active_leases),
            "expired_leases": list(expired_leases),
            "adoptions": [
                {
                    "skill": record.skill,
                    "adoption_id": record.adoption_id,
                    "package_digest": record.package_digest,
                }
                for record in adoptions
            ],
        },
        "authorization": {
            "read_only_without_confirmation": [
                "context",
                "inventory",
                "why",
                "diff",
                "inspect",
                "health",
                "policy show",
            ],
            "mutation_rule": (
                "Run the exact dry-run first. Apply only when the user's request "
                "already authorizes that mutation or the user approves the plan."
            ),
            "default_when_ambiguous": "inspect or temporary try; never adopt",
        },
        "actions": _action_contracts(selected),
        "recommended": _recommendations(operator, blocking, selected),
    }


def _action_contracts(harness: str) -> list[dict[str, Any]]:
    base = f"--harness {harness} --here"
    return [
        {
            "intent": "refresh-context",
            "mutates": False,
            "command": f"spindle harness context {base} --json",
        },
        {
            "intent": "inspect-candidate",
            "mutates": False,
            "command": f"spindle inspect <candidate> --for <intent> {base} --json",
        },
        {
            "intent": "try-once",
            "mutates": "temporary-and-cleaned",
            "dry_run": f"spindle try <candidate> --task-file <file> {base} --dry-run --json",
            "apply": f"spindle try <candidate> --task-file <file> {base} --json",
        },
        {
            "intent": "borrow-temporarily",
            "mutates": "expiring-lease",
            "dry_run": f"spindle borrow <candidate> --until <duration> {base} --dry-run --json",
            "apply": f"spindle borrow <candidate> --until <duration> {base} --json",
        },
        {
            "intent": "adopt-successful-trial",
            "mutates": "durable-custody",
            "dry_run": "spindle adopt <lease-id> --here --dry-run --json",
            "apply": "spindle adopt <lease-id> --here --json",
        },
        {
            "intent": "diagnose-effective-state",
            "mutates": False,
            "command": f"spindle diff {base} --json",
            "drill_down": f"spindle why <skill> {base} --json",
        },
        {
            "intent": "verify-startup",
            "mutates": False,
            "command": f"spindle bootstrap {base} --check --json",
        },
        {
            "intent": "update-adoption",
            "mutates": "temporary-update-trial",
            "dry_run": f"spindle update try <skill> --task-file <file> {base} --dry-run --json",
            "apply": f"spindle update try <skill> --task-file <file> {base} --json",
        },
        {
            "intent": "maintain-adoption",
            "mutates": "durable-custody",
            "command_help": "spindle disable|enable|deprecate|rollback|retire --help",
        },
        {
            "intent": "more",
            "mutates": False,
            "command": "spindle --help",
        },
    ]


def _recommendations(
    operator: dict[str, Any], blocking: list[dict[str, Any]], harness: str
) -> list[str]:
    items: list[str] = []
    if operator["state"] in {"missing", "update-available"}:
        items.append(
            f"spindle harness setup --harness {harness} --here --dry-run --json"
        )
    if operator["hooks"]["state"] not in {"observed", "observed-warn"}:
        items.append(
            f"spindle hooks status --harness {harness} --scope repo --here --effective --json"
        )
    if blocking:
        items.append(f"spindle diff --harness {harness} --here --json")
    return items


def _lock_with_operator(
    current: SurfaceLock, projection: ExpectedProjection
) -> tuple[SurfaceLock, list[str]]:
    blockers: list[str] = []
    retained: list[ExpectedProjection] = []
    for existing in current.projections:
        if existing.authority.startswith(OPERATOR_AUTHORITY_PREFIX):
            continue
        if existing.skill == projection.skill:
            blockers.append(
                f"desired skill {projection.skill!r} is already owned by "
                f"{existing.authority!r}"
            )
        elif existing.projection_path == projection.projection_path:
            blockers.append(
                f"operator target is already desired by {existing.skill!r}"
            )
        retained.append(existing)
    return (
        SurfaceLock(
            surface_id=current.surface_id,
            surface_name=current.surface_name,
            repo_path=current.repo_path,
            harness=current.harness,
            binding_coordinate=current.binding_coordinate,
            projections=tuple([*retained, projection]),
            adoption_ids=current.adoption_ids,
            lease_ids=current.lease_ids,
            conflict_decisions=current.conflict_decisions,
        ),
        blockers,
    )


def _lock_without_operator(current: SurfaceLock) -> SurfaceLock:
    return SurfaceLock(
        surface_id=current.surface_id,
        surface_name=current.surface_name,
        repo_path=current.repo_path,
        harness=current.harness,
        binding_coordinate=current.binding_coordinate,
        projections=tuple(
            item
            for item in current.projections
            if not item.authority.startswith(OPERATOR_AUTHORITY_PREFIX)
        ),
        adoption_ids=current.adoption_ids,
        lease_ids=current.lease_ids,
        conflict_decisions=current.conflict_decisions,
    )


def _operator_projection(lock: SurfaceLock | None) -> ExpectedProjection | None:
    if lock is None:
        return None
    matches = [
        item
        for item in lock.projections
        if item.authority.startswith(OPERATOR_AUTHORITY_PREFIX)
    ]
    if len(matches) > 1:
        raise LifecycleError("surface lock has multiple Spindle operator projections")
    return matches[0] if matches else None


def _assert_current_lock(plan: OperatorPlan) -> None:
    observed = read_surface_lock(plan.proposed_lock.surface_id)
    observed_id = observed.lock_id if observed is not None else None
    if observed_id != plan.current_lock_id:
        raise LifecycleError("surface lock changed after operator planning")


def _startup_dict(result: Any) -> dict[str, Any]:
    return {
        "plan": result.plan.to_dict(),
        "receipt": result.receipt.to_dict(),
        "plan_path": str(result.plan_path),
        "receipt_path": str(result.receipt_path),
    }


def _receipt_summary(receipt: dict[str, Any] | None) -> dict[str, Any] | None:
    if receipt is None:
        return None
    return {
        key: receipt.get(key)
        for key in ("receipt_id", "decision", "adapter_build", "event_source")
    }


def _repo(repo_path: str | Path) -> Path:
    repo = Path(repo_path).resolve()
    if not repo.is_dir():
        raise LifecycleError(f"no such repository directory: {repo}")
    return repo


def _require_harness(harness: str) -> None:
    if harness not in SUPPORTED_HARNESSES:
        raise LifecycleError(f"unsupported harness: {harness!r}")


def _workspace_guidance(projection_path: str, hook_path: str) -> dict[str, Any]:
    return {
        "operator_projection": {
            "path": projection_path,
            "vcs": "machine-local generated symlink; do not commit",
        },
        "hook_configuration": {
            "path": hook_path,
            "vcs": "review; commit as shared project policy or ignore if local-only",
        },
    }


def _detect_process_harness(*, pid: int | None = None) -> str | None:
    """Resolve inherited marker conflicts from the nearest Linux process ancestor.

    A harness launched by another harness inherits the parent's environment. The
    active child remains the nearest named process, so this is stronger evidence
    than the mere presence of both marker sets. Non-Linux and obscured process
    trees simply retain the fail-closed ambiguity.
    """

    current = pid if pid is not None else os.getppid()
    proc = Path("/proc")
    visited: set[int] = set()
    for _depth in range(12):
        if current <= 1 or current in visited:
            break
        visited.add(current)
        process_dir = proc / str(current)
        try:
            comm = (process_dir / "comm").read_text(encoding="utf-8").strip()
            raw_cmdline = (process_dir / "cmdline").read_bytes()
            status = (process_dir / "status").read_text(encoding="utf-8")
        except OSError:
            return None
        argv = [item for item in raw_cmdline.split(b"\0") if item]
        names = {Path(comm).name.lower()}
        if argv:
            names.add(Path(os.fsdecode(argv[0])).name.lower())
        for harness in SUPPORTED_HARNESSES:
            if harness in names or any(
                name.startswith(f"{harness}-") for name in names
            ):
                return harness
        parent_line = next(
            (line for line in status.splitlines() if line.startswith("PPid:")),
            None,
        )
        if parent_line is None:
            return None
        try:
            current = int(parent_line.split(":", 1)[1].strip())
        except ValueError:
            return None
    return None
