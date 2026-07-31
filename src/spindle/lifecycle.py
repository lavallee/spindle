"""Versioned lifecycle records, content identity, and ownership custody.

This module owns deterministic facts.  It does not discover harness state or
launch an agent.  In particular, an ownership index is authority to mutate only
when its immutable receipt still matches the exact symlink on disk.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from . import paths

SKILL_REF_SCHEMA = "spindle.skill-ref/v1"
PACKAGE_REVISION_SCHEMA = "spindle.package-revision/v1"
ADOPTION_RECORD_SCHEMA = "spindle.adoption-record/v1"
LEASE_SCHEMA = "spindle.lease/v1"
SURFACE_LOCK_SCHEMA = "spindle.surface-lock/v1"
OWNERSHIP_RECEIPT_SCHEMA = "spindle.ownership-receipt/v1"
OWNERSHIP_INDEX_SCHEMA = "spindle.ownership-index/v1"
CONFLICT_DECISION_SCHEMA = "spindle.conflict-decision/v1"

_IGNORED_CONTENT_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
    }
)


class LifecycleError(ValueError):
    """A lifecycle record or content-addressed store is inconsistent."""


def _require_text(label: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleError(f"{label} must not be empty")


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LifecycleError(f"record contains non-JSON data: {exc}") from exc


def content_id(value: Any) -> str:
    """Return a full SHA-256 identity with an explicit algorithm prefix."""
    return f"sha256:{hashlib.sha256(_canonical_json(value)).hexdigest()}"


def _validate_digest(label: str, value: str) -> None:
    _require_text(label, value)
    prefix, separator, raw = value.partition(":")
    if separator != ":" or prefix != "sha256" or len(raw) != 64:
        raise LifecycleError(f"{label} must be a full sha256 digest")
    try:
        int(raw, 16)
    except ValueError as exc:
        raise LifecycleError(f"{label} must be a full sha256 digest") from exc


def _parse_iso(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LifecycleError(f"invalid UTC timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise LifecycleError(f"timestamp must include a timezone: {value!r}")
    return parsed.astimezone(UTC)


def _included(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return not any(part in _IGNORED_CONTENT_NAMES for part in relative.parts)


def digest_path(path: str | Path) -> str:
    """Hash a file, directory tree, or symlink without timestamps.

    Directory identity includes relative paths, entry kinds, executable bits,
    file bytes, and raw symlink targets.  Common VCS and interpreter caches are
    excluded so build residue does not change package identity.
    """

    root = Path(path)
    if not root.exists() and not root.is_symlink():
        raise LifecycleError(f"cannot digest missing path: {root}")
    digest = hashlib.sha256()

    def add_entry(item: Path, relative: str) -> None:
        encoded = relative.encode("utf-8")
        if item.is_symlink():
            target = os.readlink(item).encode("utf-8")
            digest.update(b"link\0" + encoded + b"\0" + target + b"\0")
            return
        if item.is_dir():
            digest.update(b"dir\0" + encoded + b"\0")
            return
        if item.is_file():
            executable = b"1" if item.stat().st_mode & 0o111 else b"0"
            digest.update(b"file\0" + encoded + b"\0" + executable + b"\0")
            with item.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
            return
        digest.update(b"other\0" + encoded + b"\0")

    if root.is_symlink() or root.is_file():
        add_entry(root, root.name)
    else:
        add_entry(root, ".")
        for item in sorted(
            root.rglob("*"), key=lambda value: value.relative_to(root).as_posix()
        ):
            if _included(item, root):
                add_entry(item, item.relative_to(root).as_posix())
    return f"sha256:{digest.hexdigest()}"


@dataclass(frozen=True)
class SkillRef:
    provider: str
    locator: str
    revision: str
    content_digest: str
    subpath: str = "."

    def __post_init__(self) -> None:
        for label, value in (
            ("provider", self.provider),
            ("locator", self.locator),
            ("revision", self.revision),
            ("subpath", self.subpath),
        ):
            _require_text(label, value)
        _validate_digest("content_digest", self.content_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SKILL_REF_SCHEMA,
            "provider": self.provider,
            "locator": self.locator,
            "revision": self.revision,
            "subpath": self.subpath,
            "content_digest": self.content_digest,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SkillRef:
        _expect_schema(raw, SKILL_REF_SCHEMA)
        return cls(
            provider=str(raw["provider"]),
            locator=str(raw["locator"]),
            revision=str(raw["revision"]),
            subpath=str(raw.get("subpath", ".")),
            content_digest=str(raw["content_digest"]),
        )


@dataclass(frozen=True)
class PackageRevision:
    name: str
    version: str
    content_digest: str
    source: SkillRef
    root: str
    editable: bool
    skill_digests: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _require_text("package name", self.name)
        _require_text("package version", self.version)
        _require_text("package root", self.root)
        _validate_digest("package content_digest", self.content_digest)
        names: set[str] = set()
        for name, digest in self.skill_digests:
            _require_text("skill name", name)
            _validate_digest("skill digest", digest)
            if name in names:
                raise LifecycleError(f"duplicate package skill: {name}")
            names.add(name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PACKAGE_REVISION_SCHEMA,
            "name": self.name,
            "version": self.version,
            "content_digest": self.content_digest,
            "source": self.source.to_dict(),
            "root": self.root,
            "editable": self.editable,
            "skills": [
                {"name": name, "content_digest": digest}
                for name, digest in self.skill_digests
            ],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PackageRevision:
        _expect_schema(raw, PACKAGE_REVISION_SCHEMA)
        source = raw.get("source")
        skills = raw.get("skills", [])
        if not isinstance(source, dict):
            raise LifecycleError("package revision source must be an object")
        if not isinstance(skills, list):
            raise LifecycleError("package revision skills must be a list")
        if not all(isinstance(item, dict) for item in skills):
            raise LifecycleError("package revision skill entries must be objects")
        return cls(
            name=str(raw["name"]),
            version=str(raw["version"]),
            content_digest=str(raw["content_digest"]),
            source=SkillRef.from_dict(source),
            root=str(raw["root"]),
            editable=bool(raw["editable"]),
            skill_digests=tuple(
                (str(item["name"]), str(item["content_digest"])) for item in skills
            ),
        )

    @classmethod
    def from_path(
        cls,
        name: str,
        version: str,
        root: str | Path,
        *,
        provider: str = "local",
        revision: str | None = None,
        editable: bool = False,
        skills: Iterable[tuple[str, str | Path]] = (),
    ) -> PackageRevision:
        resolved = Path(root).resolve()
        digest = digest_path(resolved)
        source = SkillRef(
            provider=provider,
            locator=str(resolved),
            revision=revision or digest,
            content_digest=digest,
        )
        skill_digests = tuple(
            sorted(
                (skill_name, digest_path(skill_path))
                for skill_name, skill_path in skills
            )
        )
        return cls(
            name=name,
            version=version,
            content_digest=digest,
            source=source,
            root=str(resolved),
            editable=editable,
            skill_digests=skill_digests,
        )


@dataclass(frozen=True)
class AdoptionRecord:
    adoption_id: str
    skill: str
    package_digest: str
    surface_id: str
    scope: str
    owner: str
    adopted_at: str
    update_policy: str
    authority_ceiling: str

    def __post_init__(self) -> None:
        for label, value in (
            ("adoption_id", self.adoption_id),
            ("skill", self.skill),
            ("surface_id", self.surface_id),
            ("scope", self.scope),
            ("owner", self.owner),
            ("adopted_at", self.adopted_at),
            ("update_policy", self.update_policy),
            ("authority_ceiling", self.authority_ceiling),
        ):
            _require_text(label, value)
        _validate_digest("package_digest", self.package_digest)

    def to_dict(self) -> dict[str, Any]:
        return {"schema": ADOPTION_RECORD_SCHEMA, **self.__dict__}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AdoptionRecord:
        _expect_schema(raw, ADOPTION_RECORD_SCHEMA)
        return cls(
            **{
                key: str(raw[key])
                for key in (
                    "adoption_id",
                    "skill",
                    "package_digest",
                    "surface_id",
                    "scope",
                    "owner",
                    "adopted_at",
                    "update_policy",
                    "authority_ceiling",
                )
            }
        )


@dataclass(frozen=True)
class Lease:
    skill: str
    package_digest: str
    skill_digest: str
    source: SkillRef
    source_path: str
    surface_id: str
    harness: str
    kind: str
    scope: str
    starts_at: str
    expires_at: str
    posture: str
    agents: tuple[str, ...] = ("*",)
    renewal_policy: str = "manual"
    cleanup_policy: str = "remove-owned-projection"
    task_digest: str | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("skill", self.skill),
            ("source_path", self.source_path),
            ("surface_id", self.surface_id),
            ("harness", self.harness),
            ("kind", self.kind),
            ("scope", self.scope),
            ("starts_at", self.starts_at),
            ("expires_at", self.expires_at),
            ("posture", self.posture),
            ("renewal_policy", self.renewal_policy),
            ("cleanup_policy", self.cleanup_policy),
        ):
            _require_text(label, value)
        _validate_digest("package_digest", self.package_digest)
        _validate_digest("skill_digest", self.skill_digest)
        _validate_digest("surface_id", self.surface_id)
        if self.task_digest is not None:
            _validate_digest("task_digest", self.task_digest)
        if not Path(self.source_path).is_absolute():
            raise LifecycleError("lease source_path must be absolute")
        if self.kind not in {"session", "borrow", "update"}:
            raise LifecycleError(f"unsupported lease kind: {self.kind}")
        if self.scope not in {"session", "repo"}:
            raise LifecycleError(f"unsupported lease scope: {self.scope}")
        if self.posture not in {"read-only", "sandboxed", "full"}:
            raise LifecycleError(f"unsupported lease posture: {self.posture}")
        if not self.agents or any(not agent.strip() for agent in self.agents):
            raise LifecycleError("lease agents must contain non-empty identities")
        if self.renewal_policy not in {"manual", "none"}:
            raise LifecycleError(
                f"unsupported lease renewal policy: {self.renewal_policy}"
            )
        if self.cleanup_policy != "remove-owned-projection":
            raise LifecycleError(
                f"unsupported lease cleanup policy: {self.cleanup_policy}"
            )
        if _parse_iso(self.expires_at) <= _parse_iso(self.starts_at):
            raise LifecycleError("lease expiry must be later than its start")

    @property
    def lease_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def active_at(self, moment: datetime) -> bool:
        when = moment.astimezone(UTC)
        return _parse_iso(self.starts_at) <= when < _parse_iso(self.expires_at)

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": LEASE_SCHEMA,
            "skill": self.skill,
            "package_digest": self.package_digest,
            "skill_digest": self.skill_digest,
            "source": self.source.to_dict(),
            "source_path": self.source_path,
            "surface_id": self.surface_id,
            "harness": self.harness,
            "kind": self.kind,
            "scope": self.scope,
            "starts_at": self.starts_at,
            "expires_at": self.expires_at,
            "posture": self.posture,
            "agents": list(self.agents),
            "renewal_policy": self.renewal_policy,
            "cleanup_policy": self.cleanup_policy,
            "task_digest": self.task_digest,
        }
        return {"lease_id": self.lease_id, **payload} if include_id else payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Lease:
        _expect_schema(raw, LEASE_SCHEMA)
        agents = raw.get("agents", [])
        source = raw.get("source")
        if not isinstance(agents, list):
            raise LifecycleError("lease agents must be a list")
        if not isinstance(source, dict):
            raise LifecycleError("lease source must be an object")
        lease = cls(
            skill=str(raw["skill"]),
            package_digest=str(raw["package_digest"]),
            skill_digest=str(raw["skill_digest"]),
            source=SkillRef.from_dict(source),
            source_path=str(raw["source_path"]),
            surface_id=str(raw["surface_id"]),
            harness=str(raw["harness"]),
            kind=str(raw["kind"]),
            scope=str(raw["scope"]),
            starts_at=str(raw["starts_at"]),
            expires_at=str(raw["expires_at"]),
            posture=str(raw["posture"]),
            agents=tuple(str(agent) for agent in agents),
            renewal_policy=str(raw.get("renewal_policy", "manual")),
            cleanup_policy=str(
                raw.get("cleanup_policy", "remove-owned-projection")
            ),
            task_digest=(
                str(raw["task_digest"])
                if raw.get("task_digest") is not None
                else None
            ),
        )
        if raw.get("lease_id") not in {None, lease.lease_id}:
            raise LifecycleError("lease content does not match lease_id")
        return lease


@dataclass(frozen=True)
class ExpectedProjection:
    skill: str
    projection_path: str
    source_path: str
    source_digest: str
    package_digest: str
    authority: str = "binding"

    def __post_init__(self) -> None:
        for label, value in (
            ("skill", self.skill),
            ("projection_path", self.projection_path),
            ("source_path", self.source_path),
            ("authority", self.authority),
        ):
            _require_text(label, value)
        _validate_digest("source_digest", self.source_digest)
        _validate_digest("package_digest", self.package_digest)

    def to_dict(self) -> dict[str, str]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ExpectedProjection:
        return cls(**{key: str(value) for key, value in raw.items()})


@dataclass(frozen=True)
class SurfaceLock:
    surface_id: str
    surface_name: str
    repo_path: str
    harness: str
    binding_coordinate: str
    projections: tuple[ExpectedProjection, ...]
    adoption_ids: tuple[str, ...] = ()
    lease_ids: tuple[str, ...] = ()
    conflict_decisions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for label, value in (
            ("surface_id", self.surface_id),
            ("surface_name", self.surface_name),
            ("repo_path", self.repo_path),
            ("harness", self.harness),
            ("binding_coordinate", self.binding_coordinate),
        ):
            _require_text(label, value)
        paths_seen: set[str] = set()
        for projection in self.projections:
            if projection.projection_path in paths_seen:
                raise LifecycleError(
                    f"duplicate expected projection: {projection.projection_path}"
                )
            paths_seen.add(projection.projection_path)
        for decision_id in self.conflict_decisions:
            _validate_digest("conflict decision id", decision_id)

    @property
    def lock_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": SURFACE_LOCK_SCHEMA,
            "surface_id": self.surface_id,
            "surface_name": self.surface_name,
            "repo_path": self.repo_path,
            "harness": self.harness,
            "binding_coordinate": self.binding_coordinate,
            "projections": [
                projection.to_dict()
                for projection in sorted(
                    self.projections, key=lambda item: item.projection_path
                )
            ],
            "adoption_ids": sorted(self.adoption_ids),
            "lease_ids": sorted(self.lease_ids),
            "conflict_decisions": sorted(self.conflict_decisions),
        }
        if include_id:
            payload = {"lock_id": self.lock_id, **payload}
        return payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SurfaceLock:
        _expect_schema(raw, SURFACE_LOCK_SCHEMA)
        projections = raw.get("projections")
        if not isinstance(projections, list):
            raise LifecycleError("surface lock projections must be a list")
        lock = cls(
            surface_id=str(raw["surface_id"]),
            surface_name=str(raw["surface_name"]),
            repo_path=str(raw["repo_path"]),
            harness=str(raw["harness"]),
            binding_coordinate=str(raw["binding_coordinate"]),
            projections=tuple(
                ExpectedProjection.from_dict(item) for item in projections
            ),
            adoption_ids=tuple(str(item) for item in raw.get("adoption_ids", [])),
            lease_ids=tuple(str(item) for item in raw.get("lease_ids", [])),
            conflict_decisions=tuple(
                str(item) for item in raw.get("conflict_decisions", [])
            ),
        )
        stored_id = raw.get("lock_id")
        if stored_id is not None and stored_id != lock.lock_id:
            raise LifecycleError("surface lock content does not match lock_id")
        return lock


@dataclass(frozen=True)
class ConflictDecision:
    surface_id: str
    harness: str
    skill: str
    observed_path: str
    observed_digest: str
    disposition: str
    reason: str

    def __post_init__(self) -> None:
        for label, value in (
            ("surface_id", self.surface_id),
            ("harness", self.harness),
            ("skill", self.skill),
            ("observed_path", self.observed_path),
            ("disposition", self.disposition),
            ("reason", self.reason),
        ):
            _require_text(label, value)
        _validate_digest("surface_id", self.surface_id)
        _validate_digest("observed_digest", self.observed_digest)
        if self.disposition not in {"allow"}:
            raise LifecycleError(
                f"unsupported foreign conflict disposition: {self.disposition}"
            )
        if not Path(self.observed_path).is_absolute():
            raise LifecycleError("conflict decision observed_path must be absolute")

    @property
    def decision_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "schema": CONFLICT_DECISION_SCHEMA,
            "surface_id": self.surface_id,
            "harness": self.harness,
            "skill": self.skill,
            "observed_path": self.observed_path,
            "observed_digest": self.observed_digest,
            "disposition": self.disposition,
            "reason": self.reason,
        }
        return {"decision_id": self.decision_id, **payload} if include_id else payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ConflictDecision:
        _expect_schema(raw, CONFLICT_DECISION_SCHEMA)
        decision = cls(
            surface_id=str(raw["surface_id"]),
            harness=str(raw["harness"]),
            skill=str(raw["skill"]),
            observed_path=str(raw["observed_path"]),
            observed_digest=str(raw["observed_digest"]),
            disposition=str(raw["disposition"]),
            reason=str(raw["reason"]),
        )
        if raw.get("decision_id") not in {None, decision.decision_id}:
            raise LifecycleError("conflict decision content does not match decision_id")
        return decision

    def matches(
        self,
        *,
        surface: str,
        harness: str,
        skill: str,
        observed_path: str,
        observed_digest: str | None,
    ) -> bool:
        return (
            self.surface_id == surface
            and self.harness == harness
            and self.skill == skill
            and self.observed_path == observed_path
            and self.observed_digest == observed_digest
            and self.disposition == "allow"
        )


class ConflictDecisionStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or paths.conflict_receipts_dir()

    def get(self, decision_id: str) -> ConflictDecision:
        target = self.root / f"{_digest_hex(decision_id)}.json"
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LifecycleError(
                f"invalid or missing conflict decision {decision_id}: {exc}"
            ) from exc
        decision = ConflictDecision.from_dict(raw)
        if decision.decision_id != decision_id:
            raise LifecycleError("conflict decision store identity mismatch")
        return decision

    def record(self, decision: ConflictDecision) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{_digest_hex(decision.decision_id)}.json"
        if target.exists():
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise LifecycleError(
                    f"invalid conflict decision at {target}: {exc}"
                ) from exc
            if existing != decision.to_dict():
                raise LifecycleError(f"conflict decision collision at {target}")
        else:
            _atomic_json(target, decision.to_dict(), replace=False)
        return target


@dataclass(frozen=True)
class OwnershipRecord:
    surface_id: str
    surface_name: str
    harness: str
    skill: str
    projection_path: str
    source_path: str
    source_digest: str
    package_digest: str
    creation_receipt_id: str
    owner: str = "spindle"

    def __post_init__(self) -> None:
        for label, value in (
            ("surface_id", self.surface_id),
            ("surface_name", self.surface_name),
            ("harness", self.harness),
            ("skill", self.skill),
            ("projection_path", self.projection_path),
            ("source_path", self.source_path),
            ("creation_receipt_id", self.creation_receipt_id),
            ("owner", self.owner),
        ):
            _require_text(label, value)
        _validate_digest("source_digest", self.source_digest)
        _validate_digest("package_digest", self.package_digest)
        if self.owner != "spindle":
            raise LifecycleError("ownership record owner must be spindle")

    @property
    def ownership_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": OWNERSHIP_RECEIPT_SCHEMA,
            **self.__dict__,
        }
        if include_id:
            payload = {"ownership_id": self.ownership_id, **payload}
        return payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> OwnershipRecord:
        _expect_schema(raw, OWNERSHIP_RECEIPT_SCHEMA)
        fields = {
            key: str(raw[key])
            for key in (
                "surface_id",
                "surface_name",
                "harness",
                "skill",
                "projection_path",
                "source_path",
                "source_digest",
                "package_digest",
                "creation_receipt_id",
                "owner",
            )
        }
        record = cls(**fields)
        stored_id = raw.get("ownership_id")
        if stored_id is not None and stored_id != record.ownership_id:
            raise LifecycleError(
                "ownership receipt content does not match ownership_id"
            )
        return record

    def matches_symlink(self, projection: str | Path) -> bool:
        path = Path(projection)
        if str(path.absolute()) != str(Path(self.projection_path).absolute()):
            return False
        if not path.is_symlink():
            return False
        try:
            observed = (path.parent / os.readlink(path)).resolve(strict=False)
        except OSError:
            return False
        return observed == Path(self.source_path).resolve(strict=False)


def surface_id(repo_path: str | Path, harness: str) -> str:
    return content_id({"repo_path": str(Path(repo_path).resolve()), "harness": harness})


def write_surface_lock(lock: SurfaceLock, *, root: Path | None = None) -> Path:
    target_root = root or paths.surface_locks_dir()
    target_root.mkdir(parents=True, exist_ok=True)
    target = target_root / f"{_digest_hex(lock.surface_id)}.json"
    _atomic_json(target, lock.to_dict())
    return target


def read_surface_lock(surface: str, *, root: Path | None = None) -> SurfaceLock | None:
    target = (root or paths.surface_locks_dir()) / f"{_digest_hex(surface)}.json"
    if not target.exists():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError(f"invalid surface lock at {target}: {exc}") from exc
    if not isinstance(raw, dict):
        raise LifecycleError(f"surface lock at {target} must be an object")
    return SurfaceLock.from_dict(raw)


class OwnershipStore:
    """Immutable ownership receipts plus a mutable current-path index."""

    def __init__(
        self,
        *,
        receipt_root: Path | None = None,
        index_root: Path | None = None,
    ) -> None:
        self.receipt_root = receipt_root or paths.ownership_receipts_dir()
        self.index_root = index_root or paths.ownership_index_dir()

    def records(self, surface: str) -> dict[str, OwnershipRecord]:
        index = self._read_index(surface)
        records: dict[str, OwnershipRecord] = {}
        for projection_path, ownership_id in index.items():
            receipt = self.receipt_root / f"{_digest_hex(ownership_id)}.json"
            try:
                raw = json.loads(receipt.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise LifecycleError(
                    f"invalid ownership receipt at {receipt}: {exc}"
                ) from exc
            if not isinstance(raw, dict):
                raise LifecycleError(
                    f"ownership receipt at {receipt} must be an object"
                )
            record = OwnershipRecord.from_dict(raw)
            if record.ownership_id != ownership_id:
                raise LifecycleError(f"ownership index mismatch for {projection_path}")
            if (
                record.surface_id != surface
                or record.projection_path != projection_path
            ):
                raise LifecycleError(
                    f"ownership index scope mismatch for {projection_path}"
                )
            records[projection_path] = record
        return records

    def record(self, record: OwnershipRecord) -> Path:
        self.receipt_root.mkdir(parents=True, exist_ok=True)
        receipt = self.receipt_root / f"{_digest_hex(record.ownership_id)}.json"
        if receipt.exists():
            existing = json.loads(receipt.read_text(encoding="utf-8"))
            if existing != record.to_dict():
                raise LifecycleError(f"ownership receipt collision at {receipt}")
        else:
            _atomic_json(receipt, record.to_dict(), replace=False)
        index = self._read_index(record.surface_id)
        index[record.projection_path] = record.ownership_id
        self._write_index(record.surface_id, index)
        return receipt

    def forget(
        self, surface: str, projection_path: str | Path, ownership_id: str
    ) -> bool:
        key = str(Path(projection_path).absolute())
        index = self._read_index(surface)
        if index.get(key) != ownership_id:
            return False
        del index[key]
        self._write_index(surface, index)
        return True

    def _index_path(self, surface: str) -> Path:
        return self.index_root / f"{_digest_hex(surface)}.json"

    def _read_index(self, surface: str) -> dict[str, str]:
        path = self._index_path(surface)
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LifecycleError(f"invalid ownership index at {path}: {exc}") from exc
        _expect_schema(raw, OWNERSHIP_INDEX_SCHEMA)
        if raw.get("surface_id") != surface or not isinstance(raw.get("entries"), dict):
            raise LifecycleError(f"invalid ownership index scope at {path}")
        return {str(key): str(value) for key, value in raw["entries"].items()}

    def _write_index(self, surface: str, entries: dict[str, str]) -> None:
        path = self._index_path(surface)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(
            path,
            {
                "schema": OWNERSHIP_INDEX_SCHEMA,
                "surface_id": surface,
                "entries": dict(sorted(entries.items())),
            },
        )


def cache_package(revision: PackageRevision, *, cache_root: Path | None = None) -> Path:
    """Copy one exact package revision into the immutable cache without running it."""

    source = Path(revision.root)
    if digest_path(source) != revision.content_digest:
        raise LifecycleError("package source changed after revision was resolved")
    root = cache_root or paths.package_cache_dir()
    destination = root / _digest_hex(revision.content_digest) / revision.name
    if destination.exists():
        if digest_path(destination) != revision.content_digest:
            raise LifecycleError(f"package cache collision at {destination}")
        return destination

    root.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix=".package-", dir=root))
    payload = temp_root / revision.name
    try:
        shutil.copytree(
            source,
            payload,
            symlinks=True,
            ignore=shutil.ignore_patterns(*sorted(_IGNORED_CONTENT_NAMES)),
        )
        if digest_path(payload) != revision.content_digest:
            raise LifecycleError("cached package digest differs from resolved revision")
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(payload, destination)
        except FileExistsError:
            if digest_path(destination) != revision.content_digest:
                raise LifecycleError(f"package cache collision at {destination}")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
    return destination


def _expect_schema(raw: Any, expected: str) -> None:
    if not isinstance(raw, dict) or raw.get("schema") != expected:
        found = raw.get("schema") if isinstance(raw, dict) else None
        raise LifecycleError(f"unsupported schema {found!r}; expected {expected!r}")


def _digest_hex(value: str) -> str:
    _validate_digest("content identity", value)
    return value.split(":", 1)[1]


def _atomic_json(path: Path, payload: dict[str, Any], *, replace: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        if replace:
            os.replace(temp, path)
        else:
            try:
                os.link(temp, path)
            except FileExistsError:
                pass
    finally:
        temp.unlink(missing_ok=True)


def now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
