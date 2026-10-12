"""Session-local realization of one installed skill package.

Binding installs a stable package.  Realization combines that package's invariant
``SKILL.md`` with at most one package-local overlay selected from an explicit
runtime coordinate.  Outputs are immutable and content-addressed, so concurrent
parent and child agents never mutate a shared ``SKILL.md``.

Runtime-aware skills declare ``spindle-realization.toml`` beside ``SKILL.md``::

    schema_version = 1

    [[profile]]
    id = "codex-review"
    overlay = "overlays/codex-review.md"  # optional: an evaluated empty delta

    [profile.match]
    harness = "codex"
    model = "gpt-example"
    effort = "high"
    role = "reviewer"

Match values may also be arrays.  Omitted axes are explicit portability claims,
not inferred model capabilities.  The most specific matching profile wins, then
``priority``; an unresolved tie falls back to the invariant core.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import tomllib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import paths

MANIFEST_NAME = "spindle-realization.toml"
SCHEMA_VERSION = 1
_PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MATCH_FIELDS = (
    "harness",
    "model",
    "effort",
    "role",
    "harness_build",
    "toolset_digest",
    "policy_digest",
    "memory_policy",
)


class RealizationError(ValueError):
    """The installed package cannot be realized safely."""


@dataclass(frozen=True)
class SessionProfile:
    """Facts supplied by a harness or agent definition for one agent session."""

    session_id: str
    harness: str
    requested_model: str | None = None
    served_model: str | None = None
    effort: str | None = None
    role: str | None = None
    harness_build: str | None = None
    toolset_digest: str | None = None
    policy_digest: str | None = None
    memory_policy: str | None = None

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise RealizationError("session_id must not be empty")
        if not self.harness.strip():
            raise RealizationError("harness must not be empty")

    @property
    def model_mismatch(self) -> bool:
        return bool(
            self.requested_model
            and self.served_model
            and self.requested_model != self.served_model
        )

    def match_coordinate(self) -> dict[str, str | None]:
        """The coordinate profile matchers consume.

        Model matching uses only the actually served model.  A requested model is
        audit evidence, not proof of what executed.
        """

        return {
            "harness": self.harness,
            "model": self.served_model,
            "effort": self.effort,
            "role": self.role,
            "harness_build": self.harness_build,
            "toolset_digest": self.toolset_digest,
            "policy_digest": self.policy_digest,
            "memory_policy": self.memory_policy,
        }

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


@dataclass(frozen=True)
class RuntimeProfile:
    """One evaluated mapping from runtime facts to an optional steering delta."""

    id: str
    match: dict[str, tuple[str, ...]]
    overlay: Path | None = None
    priority: int = 0

    @property
    def specificity(self) -> int:
        return len(self.match)

    def matches(self, session: SessionProfile) -> bool:
        coordinate = session.match_coordinate()
        return all(coordinate.get(key) in values for key, values in self.match.items())


@dataclass(frozen=True)
class Resolution:
    """Pure selection result; no files have been written yet."""

    status: str  # matched | core | unresolved
    reason: str
    profile: RuntimeProfile | None = None

    @property
    def tuned(self) -> bool:
        return self.status == "matched"


@dataclass(frozen=True)
class RealizationResult:
    skill: str
    path: Path
    status: str
    reason: str
    tuned: bool
    profile_id: str | None
    overlay: str | None
    overlay_digest: str | None
    package_digest: str
    realization_digest: str
    receipt_id: str
    receipt_path: Path

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        data["receipt_path"] = str(self.receipt_path)
        return data


def manifest_path(skill_dir: str | Path) -> Path:
    return Path(skill_dir) / MANIFEST_NAME


def has_runtime_profiles(skill_dir: str | Path) -> bool:
    return manifest_path(skill_dir).is_file()


def _values(value: object, *, profile_id: str, field: str) -> tuple[str, ...]:
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        values = tuple(value)
    else:
        raise RealizationError(
            f"profile {profile_id!r} match.{field} must be a string or list of strings"
        )
    if not values or any(not item.strip() for item in values):
        raise RealizationError(
            f"profile {profile_id!r} match.{field} must not be empty"
        )
    return values


def _contained_file(skill_dir: Path, raw_path: str, *, profile_id: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise RealizationError(
            f"profile {profile_id!r} overlay must be package-relative"
        )
    root = skill_dir.resolve()
    resolved = (skill_dir / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise RealizationError(
            f"profile {profile_id!r} overlay escapes the skill package"
        )
    if resolved.relative_to(root).parts[0] != "overlays":
        raise RealizationError(
            f"profile {profile_id!r} overlay must live under the reserved overlays/ directory"
        )
    if not resolved.is_file():
        raise RealizationError(
            f"profile {profile_id!r} overlay does not exist: {raw_path}"
        )
    return resolved


def load_profiles(skill_dir: str | Path) -> list[RuntimeProfile]:
    """Load and validate every package-local runtime profile."""

    root = Path(skill_dir)
    manifest = manifest_path(root)
    if not manifest.exists():
        return []
    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RealizationError(f"invalid {MANIFEST_NAME}: {exc}") from exc
    if data.get("schema_version") != SCHEMA_VERSION:
        raise RealizationError(
            f"{MANIFEST_NAME} schema_version must be {SCHEMA_VERSION}"
        )
    unknown_manifest = sorted(set(data) - {"schema_version", "profile"})
    if unknown_manifest:
        raise RealizationError(
            f"{MANIFEST_NAME} has unknown fields: {', '.join(unknown_manifest)}"
        )
    raw_profiles = data.get("profile", [])
    if not isinstance(raw_profiles, list):
        raise RealizationError(f"{MANIFEST_NAME} profile must be an array of tables")

    profiles: list[RuntimeProfile] = []
    seen: set[str] = set()
    for raw in raw_profiles:
        if not isinstance(raw, dict):
            raise RealizationError(f"{MANIFEST_NAME} contains a non-table profile")
        profile_id = raw.get("id")
        if not isinstance(profile_id, str) or not _PROFILE_ID_RE.fullmatch(profile_id):
            raise RealizationError("each profile needs a simple non-empty id")
        if profile_id in seen:
            raise RealizationError(f"duplicate profile id: {profile_id}")
        seen.add(profile_id)
        unknown_profile = sorted(set(raw) - {"id", "overlay", "priority", "match"})
        if unknown_profile:
            raise RealizationError(
                f"profile {profile_id!r} has unknown fields: {', '.join(unknown_profile)}"
            )

        raw_match = raw.get("match")
        if not isinstance(raw_match, dict):
            raise RealizationError(
                f"profile {profile_id!r} needs a [profile.match] table"
            )
        unknown = sorted(set(raw_match) - set(_MATCH_FIELDS))
        if unknown:
            raise RealizationError(
                f"profile {profile_id!r} has unknown match fields: {', '.join(unknown)}"
            )
        if "harness" not in raw_match:
            raise RealizationError(
                f"profile {profile_id!r} must constrain match.harness"
            )
        match = {
            field: _values(value, profile_id=profile_id, field=field)
            for field, value in raw_match.items()
        }

        overlay = raw.get("overlay")
        overlay_path = None
        if overlay is not None:
            if not isinstance(overlay, str) or not overlay.strip():
                raise RealizationError(f"profile {profile_id!r} overlay must be a path")
            overlay_path = _contained_file(root, overlay, profile_id=profile_id)
        priority = raw.get("priority", 0)
        if not isinstance(priority, int):
            raise RealizationError(
                f"profile {profile_id!r} priority must be an integer"
            )
        profiles.append(
            RuntimeProfile(
                id=profile_id,
                match=match,
                overlay=overlay_path,
                priority=priority,
            )
        )
    return profiles


def resolve_profile(skill_dir: str | Path, session: SessionProfile) -> Resolution:
    """Select one profile or return an explicit conservative-core decision."""

    if not manifest_path(skill_dir).exists():
        return Resolution(status="core", reason="no-runtime-manifest")
    profiles = load_profiles(skill_dir)
    if session.model_mismatch:
        return Resolution(status="unresolved", reason="requested-served-model-mismatch")

    matches = [profile for profile in profiles if profile.matches(session)]
    if not matches:
        return Resolution(status="unresolved", reason="no-matching-profile")
    best_specificity = max(profile.specificity for profile in matches)
    matches = [p for p in matches if p.specificity == best_specificity]
    best_priority = max(profile.priority for profile in matches)
    matches = [p for p in matches if p.priority == best_priority]
    if len(matches) != 1:
        ids = ",".join(sorted(profile.id for profile in matches))
        return Resolution(status="unresolved", reason=f"ambiguous-profiles:{ids}")
    return Resolution(status="matched", reason="matched", profile=matches[0])


def package_digest(skill_dir: str | Path) -> str:
    """Digest the complete installed skill package, including runtime overlays."""

    root = Path(skill_dir)
    h = hashlib.sha256()
    for file_path in sorted(path for path in root.rglob("*") if path.is_file()):
        h.update(file_path.relative_to(root).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(file_path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _skill_name(skill_dir: Path, core: str) -> str:
    name = skill_dir.name
    if core.startswith("---"):
        end = core.find("\n---", 3)
        if end >= 0:
            for line in core[3:end].splitlines():
                if line.startswith("name:"):
                    value = line.split(":", 1)[1].strip().strip('"').strip("'")
                    if value:
                        name = value
                        break
    if not _SKILL_NAME_RE.fullmatch(name):
        raise RealizationError(f"unsafe skill name for realization path: {name!r}")
    return name


def _realized_text(core: str, resolution: Resolution) -> str:
    profile = resolution.profile
    if profile is None or profile.overlay is None:
        return core
    overlay = profile.overlay.read_text(encoding="utf-8").strip()
    if not overlay:
        return core
    marker = f"<!-- spindle-realization:{profile.id} -->"
    return core.rstrip() + f"\n\n{marker}\n\n" + overlay + "\n"


def _copy_realized_package(skill_dir: Path, destination: Path, text: str) -> None:
    """Copy ordinary resources while withholding routing internals and all overlays."""

    destination.mkdir(parents=True)
    for source in sorted(path for path in skill_dir.rglob("*") if path.is_file()):
        relative = source.relative_to(skill_dir)
        if relative.as_posix() in {"SKILL.md", MANIFEST_NAME}:
            continue
        if relative.parts[0] in {"overlays", "profiles"}:
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (destination / "SKILL.md").write_text(text, encoding="utf-8")


def _store_realization(
    skill_dir: Path,
    skill_name: str,
    text: str,
    digest: str,
    *,
    store_root: Path,
) -> Path:
    final_parent = store_root / digest[:20]
    final_skill = final_parent / skill_name
    expected = final_skill / "SKILL.md"
    if expected.is_file():
        if expected.read_text(encoding="utf-8") != text:
            raise RealizationError(f"realization store collision at {final_skill}")
        return final_skill

    store_root.mkdir(parents=True, exist_ok=True)
    temp_parent = Path(tempfile.mkdtemp(prefix=f".{digest[:12]}-", dir=store_root))
    try:
        _copy_realized_package(skill_dir, temp_parent / skill_name, text)
        try:
            temp_parent.rename(final_parent)
        except OSError:
            if not expected.is_file():
                raise
    finally:
        if temp_parent.exists():
            shutil.rmtree(temp_parent)
    if expected.read_text(encoding="utf-8") != text:
        raise RealizationError(f"incomplete realization at {final_skill}")
    return final_skill


def _now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_receipt(payload: dict[str, Any], *, receipt_root: Path) -> tuple[str, Path]:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    receipt_id = hashlib.sha256(canonical).hexdigest()[:20]
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "receipt_id": receipt_id,
        "created_at": _now_iso(),
        **payload,
    }
    receipt_root.mkdir(parents=True, exist_ok=True)
    destination = receipt_root / f"{receipt_id}.json"
    if destination.exists():
        return receipt_id, destination
    fd, raw_temp = tempfile.mkstemp(prefix=f".{receipt_id}-", dir=receipt_root)
    temp_path = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(receipt, handle, indent=2, sort_keys=True)
            handle.write("\n")
        try:
            os.link(temp_path, destination)
        except FileExistsError:
            pass
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return receipt_id, destination


def realize_skill(
    skill_dir: str | Path,
    session: SessionProfile,
    *,
    store_root: Path | None = None,
    receipt_root: Path | None = None,
) -> RealizationResult:
    """Realize one skill for one explicit agent session and persist its receipt."""

    root = Path(skill_dir).resolve()
    core_path = root / "SKILL.md"
    if not core_path.is_file():
        raise RealizationError(f"skill directory has no SKILL.md: {root}")
    core = core_path.read_text(encoding="utf-8")
    resolution = resolve_profile(root, session)
    text = _realized_text(core, resolution)
    pkg_digest = package_digest(root)
    profile_id = resolution.profile.id if resolution.profile else None
    overlay = (
        resolution.profile.overlay.relative_to(root).as_posix()
        if resolution.profile and resolution.profile.overlay
        else None
    )
    overlay_digest = (
        hashlib.sha256(resolution.profile.overlay.read_bytes()).hexdigest()
        if resolution.profile and resolution.profile.overlay
        else None
    )
    digest_payload = {
        "package_digest": pkg_digest,
        "profile_id": profile_id,
        "skill_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    realization_digest = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    skill_name = _skill_name(root, core)
    realized_path = _store_realization(
        root,
        skill_name,
        text,
        realization_digest,
        store_root=store_root or paths.realizations_dir(),
    )

    receipt_payload = {
        "session": session.to_dict(),
        "skill": {
            "name": skill_name,
            "source": str(root),
            "package_digest": pkg_digest,
        },
        "resolution": {
            "status": resolution.status,
            "reason": resolution.reason,
            "tuned": resolution.tuned,
            "profile_id": profile_id,
            "overlay": overlay,
            "overlay_digest": overlay_digest,
            "specificity": resolution.profile.specificity if resolution.profile else 0,
            "priority": resolution.profile.priority if resolution.profile else None,
        },
        "realization": {
            "digest": realization_digest,
            "path": str(realized_path),
        },
    }
    receipt_id, receipt_path = _write_receipt(
        receipt_payload,
        receipt_root=receipt_root or paths.realization_receipts_dir(),
    )
    return RealizationResult(
        skill=skill_name,
        path=realized_path,
        status=resolution.status,
        reason=resolution.reason,
        tuned=resolution.tuned,
        profile_id=profile_id,
        overlay=overlay,
        overlay_digest=overlay_digest,
        package_digest=pkg_digest,
        realization_digest=realization_digest,
        receipt_id=receipt_id,
        receipt_path=receipt_path,
    )
