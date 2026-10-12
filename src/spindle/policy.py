"""Organization policy seams for sources, authority, hooks, and evidence."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import conformance, hooks, maintenance, paths
from .lifecycle import LifecycleError, content_id, read_surface_lock, surface_id

POLICY_SCHEMA = "spindle.organization-policy/v1"
AUDIT_SCHEMA = "spindle.organization-policy-audit/v1"
_AUTHORITY = {"read-only": 0, "sandboxed": 1, "full": 2}


class PolicyError(ValueError):
    """Raised when an organization policy is invalid or unsatisfied."""


@dataclass(frozen=True)
class OrganizationPolicy:
    path: Path
    allowed_source_providers: tuple[str, ...]
    authority_ceiling: str
    required_hook_scopes: tuple[str, ...]
    required_attestations: tuple[str, ...]
    require_certified_adapter: bool
    allowed_adapter_builds: tuple[tuple[str, tuple[str, ...]], ...]

    @property
    def policy_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        body = {
            "schema": POLICY_SCHEMA,
            "path": str(self.path),
            "allowed_source_providers": list(self.allowed_source_providers),
            "authority_ceiling": self.authority_ceiling,
            "required_hook_scopes": list(self.required_hook_scopes),
            "required_attestations": list(self.required_attestations),
            "require_certified_adapter": self.require_certified_adapter,
            "allowed_adapter_builds": {
                harness: list(builds) for harness, builds in self.allowed_adapter_builds
            },
        }
        return {"policy_id": self.policy_id, **body} if include_id else body


def discover_policy(repo: str | Path) -> Path | None:
    override = os.environ.get("SPINDLE_POLICY")
    if override:
        return Path(override).expanduser().resolve()
    current = Path(repo).resolve()
    for directory in (current, *current.parents):
        candidate = directory / ".spindle" / "policy.toml"
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
        if (directory / ".git").exists():
            break
    return None


def load_policy(repo: str | Path) -> OrganizationPolicy | None:
    target = discover_policy(repo)
    if target is None:
        return None
    try:
        raw = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PolicyError(f"cannot read organization policy: {exc}") from exc
    if raw.get("schema") != POLICY_SCHEMA:
        raise PolicyError(f"policy schema must be {POLICY_SCHEMA}")
    sources = raw.get("sources", {})
    authority = raw.get("authority", {})
    hook_policy = raw.get("hooks", {})
    evidence = raw.get("evidence", {})
    adapter = raw.get("adapters", {})
    if not all(isinstance(value, dict) for value in (sources, authority, hook_policy, evidence, adapter)):
        raise PolicyError("policy sections must be tables")
    providers = _strings(sources.get("allowed_providers", ["local", "git", "github", "skills.sh"]), "sources.allowed_providers")
    ceiling = authority.get("ceiling", "read-only")
    if ceiling not in _AUTHORITY:
        raise PolicyError("authority.ceiling must be read-only, sandboxed, or full")
    scopes = _strings(hook_policy.get("required_scopes", []), "hooks.required_scopes")
    if any(scope not in {"repo", "user"} for scope in scopes):
        raise PolicyError("hook scopes must be repo or user")
    attestations = _strings(evidence.get("required_attestations", []), "evidence.required_attestations")
    require_certified = evidence.get("require_certified_adapter", False)
    if not isinstance(require_certified, bool):
        raise PolicyError("evidence.require_certified_adapter must be boolean")
    builds: list[tuple[str, tuple[str, ...]]] = []
    for harness, values in adapter.items():
        builds.append((str(harness), _strings(values, f"adapters.{harness}")))
    return OrganizationPolicy(
        path=target,
        allowed_source_providers=providers,
        authority_ceiling=str(ceiling),
        required_hook_scopes=scopes,
        required_attestations=attestations,
        require_certified_adapter=require_certified,
        allowed_adapter_builds=tuple(sorted(builds)),
    )


def assert_candidate_allowed(
    policy: OrganizationPolicy | None, *, provider: str, posture: str
) -> None:
    if policy is None:
        return
    if provider not in policy.allowed_source_providers:
        raise LifecycleError(
            f"organization policy {policy.policy_id} disallows source provider {provider!r}"
        )
    if _AUTHORITY[posture] > _AUTHORITY[policy.authority_ceiling]:
        raise LifecycleError(
            f"organization policy {policy.policy_id} authority ceiling is "
            f"{policy.authority_ceiling}"
        )


def assert_adoption_allowed(
    policy: OrganizationPolicy | None,
    record: maintenance.AdoptionRecord,
    *,
    harness_build: str | None,
) -> None:
    if policy is None:
        return
    assert_candidate_allowed(
        policy,
        provider=record.source.provider,
        posture=record.authority_ceiling,
    )
    allowed = dict(policy.allowed_adapter_builds).get(record.harness, ())
    if allowed and harness_build not in allowed:
        raise LifecycleError(
            f"organization policy requires an allowed {record.harness} build: "
            + ", ".join(allowed)
        )
    if policy.required_attestations:
        if record.preflight_report_id is None:
            raise LifecycleError("organization policy requires preflight attestations")
        preflight = _load_preflight(record.preflight_report_id)
        observed = {
            item.get("name")
            for item in preflight.get("attestations", [])
            if isinstance(item, dict)
        }
        missing = sorted(set(policy.required_attestations) - observed)
        if missing:
            raise LifecycleError(
                "organization policy requires attestations: " + ", ".join(missing)
            )
    if policy.require_certified_adapter:
        if harness_build is None or not _has_certification(record.harness, harness_build):
            raise LifecycleError(
                "organization policy requires a certified exact adapter build"
            )


def audit_policy(
    policy: OrganizationPolicy,
    repo: str | Path,
    harness: str,
    *,
    harness_build: str | None = None,
) -> dict[str, Any]:
    project = Path(repo).resolve()
    findings: list[dict[str, str]] = []
    allowed_builds = dict(policy.allowed_adapter_builds).get(harness, ())
    if allowed_builds and harness_build not in allowed_builds:
        findings.append(
            {
                "kind": "adapter-build",
                "status": "block",
                "detail": "current build is absent or not allowed",
            }
        )
    sid = surface_id(project, harness)
    lock = read_surface_lock(sid)
    if lock is not None:
        for record in maintenance.active_adoptions(lock):
            try:
                assert_adoption_allowed(policy, record, harness_build=harness_build)
            except LifecycleError as exc:
                findings.append(
                    {"kind": "adoption", "status": "block", "detail": str(exc)}
                )
    for scope in policy.required_hook_scopes:
        try:
            plan = hooks.plan_hooks(project, harness, scope=scope)
        except LifecycleError as exc:
            findings.append(
                {"kind": "hook", "status": "block", "detail": str(exc)}
            )
            continue
        if plan.blockers or len(plan.owned) != len(hooks.desired_fragments(harness)):
            findings.append(
                {
                    "kind": "hook",
                    "status": "block",
                    "detail": f"required {scope} native hooks are not fully owned",
                }
            )
    body = {
        "schema": AUDIT_SCHEMA,
        "policy_id": policy.policy_id,
        "surface_id": sid,
        "harness": harness,
        "harness_build": harness_build,
        "findings": findings,
        "decision": "pass" if not findings else "block",
    }
    return {"audit_id": content_id(body), **body}


def _load_preflight(report_id: str) -> dict[str, Any]:
    target = paths.preflight_receipts_dir() / f"{report_id.removeprefix('sha256:')}.json"
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError(f"cannot read required preflight report: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("report_id") != report_id:
        raise LifecycleError("required preflight report identity mismatch")
    return raw


def _has_certification(harness: str, build: str) -> bool:
    root = paths.adapter_certifications_dir()
    if not root.is_dir():
        return False
    for target in sorted(root.glob("*.json")):
        try:
            raw = conformance.load_certification(target)
        except conformance.ConformanceError:
            continue
        if (
            raw.get("schema") == "spindle.adapter-certification/v1"
            and raw.get("harness") == harness
            and raw.get("harness_build") == build
            and raw.get("status") == "certified"
        ):
            return True
    return False


def _strings(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise PolicyError(f"{label} must be an array of non-empty strings")
    return tuple(sorted(set(value)))
