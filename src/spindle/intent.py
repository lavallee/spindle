"""Deterministic, read-only intent cards for local skill candidates.

Inspection never imports candidate code, runs bundled commands, populates the
package cache, or changes desired state. Package facts and context-specific fit
derivations are kept in separate sections so a lexical hint cannot masquerade
as maintainer metadata or behavioral evidence.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import packages, skills
from .lifecycle import LifecycleError, PackageRevision, content_id

INTENT_CARD_SCHEMA = "spindle.intent-card/v1"
_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
_WORD = re.compile(r"[a-z0-9][a-z0-9_-]+")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_EXECUTABLE_SUFFIXES = frozenset({".sh", ".bash", ".py", ".js", ".ts", ".rb"})


@dataclass(frozen=True)
class LocalCandidate:
    reference: str
    revision: PackageRevision
    skill: str
    skill_path: Path

    @property
    def relative_skill_path(self) -> Path:
        return self.skill_path.resolve().relative_to(Path(self.revision.root).resolve())

    def cached_skill_path(self, cached_package: Path) -> Path:
        relative = self.relative_skill_path
        return cached_package if relative == Path(".") else cached_package / relative


@dataclass(frozen=True)
class IntentCard:
    package_facts: dict[str, Any]
    fit_analysis: dict[str, Any]

    @property
    def card_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "schema": INTENT_CARD_SCHEMA,
            "package_facts": self.package_facts,
            "fit_analysis": self.fit_analysis,
        }
        return {"card_id": self.card_id, **payload} if include_id else payload


def resolve_local_candidate(reference: str) -> LocalCandidate:
    """Resolve a path, installed skill, or installed package to exact local bytes."""

    raw_ref, requested_skill = _split_reference(reference)
    candidate_path = Path(raw_ref).expanduser()
    if candidate_path.exists():
        return _candidate_from_path(reference, candidate_path, requested_skill)

    installed_skill = skills.read_skill_metadata(raw_ref)
    if installed_skill is not None:
        _frontmatter, spec = installed_skill
        if requested_skill is not None and requested_skill != spec.name:
            raise LifecycleError(
                f"installed skill {raw_ref!r} does not contain {requested_skill!r}"
            )
        revision = packages.resolve_package_revision(spec.package)
        return LocalCandidate(reference, revision, spec.name, spec.skill_dir.resolve())

    try:
        revision = packages.resolve_package_revision(raw_ref)
    except ValueError as exc:
        raise LifecycleError(
            f"no local path, installed skill, or installed package matches {raw_ref!r}"
        ) from exc
    skill_dirs = packages.package_skill_dirs(revision.name)
    skill_path = _select_skill(skill_dirs, requested_skill)
    return LocalCandidate(reference, revision, _skill_name(skill_path), skill_path)


def build_intent_card(
    candidate: LocalCandidate,
    *,
    requested_intent: str | None = None,
    effective_entries: Iterable[dict[str, Any]] = (),
) -> IntentCard:
    """Build a deterministic card without executing or activating the candidate."""

    root = candidate.skill_path
    skill_md = root / "SKILL.md"
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        raise LifecycleError(f"cannot read candidate SKILL.md: {exc}") from exc
    frontmatter, body = _frontmatter(text)
    contents = _contents(root)
    references = _references(root, text)
    executables = tuple(
        item["path"]
        for item in contents
        if item["kind"] == "file" and item["executable"]
    )
    script_like = tuple(
        item["path"]
        for item in contents
        if item["kind"] == "file"
        and Path(item["path"]).suffix.lower() in _EXECUTABLE_SUFFIXES
    )
    declared_tools = tuple(
        sorted(
            item.strip()
            for item in re.split(r"[, ]+", frontmatter.get("allowed-tools", ""))
            if item.strip()
        )
    )
    description = frontmatter.get("description", "").strip()
    behavioral_delta = _behavioral_delta(body)
    facts: dict[str, Any] = {
        "skill": candidate.skill,
        "outcome": description or behavioral_delta,
        "trigger_boundary": description or "not declared",
        "behavioral_delta": behavioral_delta,
        "frontmatter": dict(sorted(frontmatter.items())),
        "contents": list(contents),
        "requirements": {
            "declared_tools": list(declared_tools),
            "references": list(references),
            "missing_references": [
                item["target"] for item in references if item["state"] == "missing"
            ],
        },
        "context_cost": {
            "always_visible_bytes": len(text.encode("utf-8")),
            "estimated_tokens": (len(text) + 3) // 4,
            "package_bytes": sum(int(item.get("bytes", 0)) for item in contents),
        },
        "provenance": {
            "reference": candidate.reference,
            "source": candidate.revision.source.to_dict(),
            "package_name": candidate.revision.name,
            "package_version": candidate.revision.version,
            "package_digest": candidate.revision.content_digest,
            "skill_digest": dict(candidate.revision.skill_digests)[candidate.skill],
            "editable": candidate.revision.editable,
        },
        "evidence": {
            "runtime_profiles": _runtime_profile_ids(root),
            "evaluation_claims": [],
        },
        "freshness": {
            "basis": "immutable-content-identity",
            "revision": candidate.revision.source.revision,
        },
        "authority": {
            "default_trial_posture": "read-only",
            "declared_tools": list(declared_tools),
            "executable_resources": list(executables),
            "script_like_resources": list(script_like),
            "requires_explicit_expansion": bool(
                declared_tools or executables or script_like
            ),
        },
    }
    observed = tuple(effective_entries)
    same_name = tuple(
        sorted(
            (
                {
                    "scope": str(entry.get("scope", "unknown")),
                    "state": str(entry.get("state", "unknown")),
                    "path": entry.get("path"),
                }
                for entry in observed
                if entry.get("name") == candidate.skill
            ),
            key=lambda item: (item["scope"], str(item["path"])),
        )
    )
    intent_terms = set(_WORD.findall((requested_intent or "").lower()))
    package_terms = set(
        _WORD.findall(f"{description} {behavioral_delta} {candidate.skill}".lower())
    )
    shared = tuple(sorted(intent_terms & package_terms))
    fit = {
        "basis": "deterministic-structural-and-lexical/v1",
        "model_assisted": False,
        "requested_intent": requested_intent,
        "shared_terms": list(shared),
        "lexical_coverage": (
            round(len(shared) / len(intent_terms), 4) if intent_terms else None
        ),
        "same_name_entries": list(same_name),
        "composition": "name-conflict" if same_name else "additive",
        "behavioral_fit": "unassessed",
        "note": (
            "Structural fit is factual; behavioral fit requires trial evidence or "
            "an explicitly identified model-assisted analysis."
        ),
    }
    return IntentCard(facts, fit)


def _split_reference(reference: str) -> tuple[str, str | None]:
    if "#" not in reference:
        return reference, None
    base, fragment = reference.rsplit("#", 1)
    if not base or not fragment:
        raise LifecycleError("local reference fragments use <path-or-package>#<skill>")
    return base, fragment


def _candidate_from_path(
    reference: str, path: Path, requested_skill: str | None
) -> LocalCandidate:
    resolved = path.resolve()
    if resolved.is_file():
        if resolved.name != "SKILL.md":
            raise LifecycleError("a local candidate file must be named SKILL.md")
        resolved = resolved.parent
    if (resolved / "SKILL.md").is_file():
        name = _skill_name(resolved)
        if requested_skill is not None and requested_skill != name:
            raise LifecycleError(
                f"candidate skill is {name!r}, not requested {requested_skill!r}"
            )
        revision = PackageRevision.from_path(
            name,
            "local",
            resolved,
            editable=True,
            skills=((name, resolved),),
        )
        return LocalCandidate(reference, revision, name, resolved)

    skill_dirs = _discover_package_skills(resolved)
    skill_path = _select_skill(skill_dirs, requested_skill)
    name, version = _local_package_identity(resolved)
    revision = PackageRevision.from_path(
        name,
        version,
        resolved,
        editable=True,
        skills=tuple((_skill_name(skill), skill) for skill in skill_dirs),
    )
    return LocalCandidate(reference, revision, _skill_name(skill_path), skill_path)


def _discover_package_skills(root: Path) -> list[Path]:
    candidates: set[Path] = set()
    for pattern in ("skills/*/SKILL.md", "src/*/skills/*/SKILL.md", "*/SKILL.md"):
        for skill_md in root.glob(pattern):
            if skill_md.is_file() and not skill_md.is_symlink():
                candidates.add(skill_md.parent.resolve())
    if not candidates:
        raise LifecycleError(f"no local skills found beneath {root}")
    return sorted(candidates, key=lambda item: (_skill_name(item), str(item)))


def _select_skill(skill_dirs: Iterable[Path], requested: str | None) -> Path:
    candidates = tuple(skill_dirs)
    if requested is not None:
        matches = tuple(path for path in candidates if _skill_name(path) == requested)
        if len(matches) != 1:
            raise LifecycleError(
                f"skill {requested!r} was not found exactly once; available: "
                + ", ".join(sorted(_skill_name(path) for path in candidates))
            )
        return matches[0]
    if len(candidates) != 1:
        raise LifecycleError(
            "candidate contains multiple skills; select one with #<skill>: "
            + ", ".join(sorted(_skill_name(path) for path in candidates))
        )
    return candidates[0]


def _skill_name(skill_dir: Path) -> str:
    try:
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    except OSError as exc:
        raise LifecycleError(f"cannot read candidate skill at {skill_dir}: {exc}") from exc
    frontmatter, _body = _frontmatter(text)
    name = frontmatter.get("name", "").strip() or skill_dir.name
    if not _SAFE_NAME.fullmatch(name):
        raise LifecycleError(f"unsafe candidate skill name: {name!r}")
    return name


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    values: dict[str, str] = {}
    for line in text[3:end].splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip().strip('"').strip("'")
    body = text[end + 4 :].lstrip("\n")
    return values, body


def _behavioral_delta(body: str) -> str:
    for line in body.splitlines():
        value = line.strip().lstrip("#").strip()
        if value and not value.startswith("<!--"):
            return value[:240]
    return "not stated"


def _contents(root: Path) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if any(part in {".git", "__pycache__"} for part in path.relative_to(root).parts):
            continue
        if path.is_symlink():
            rows.append(
                {
                    "path": relative,
                    "kind": "symlink",
                    "target": os.readlink(path),
                    "bytes": 0,
                    "executable": False,
                }
            )
        elif path.is_file():
            stat = path.stat()
            rows.append(
                {
                    "path": relative,
                    "kind": "file",
                    "bytes": stat.st_size,
                    "executable": bool(stat.st_mode & 0o111),
                }
            )
    return tuple(rows)


def _references(root: Path, text: str) -> tuple[dict[str, str], ...]:
    rows: list[dict[str, str]] = []
    resolved_root = root.resolve()
    for target in sorted(set(_LINK.findall(text))):
        cleaned = target.split("#", 1)[0].strip()
        if not cleaned or "://" in cleaned or cleaned.startswith("mailto:"):
            continue
        candidate = (root / cleaned).resolve(strict=False)
        if not candidate.is_relative_to(resolved_root):
            state = "outside-package"
        else:
            state = "present" if candidate.exists() else "missing"
        rows.append({"target": target, "state": state})
    return tuple(rows)


def _runtime_profile_ids(root: Path) -> list[str]:
    manifest = root / "spindle-realization.toml"
    if not manifest.is_file() or manifest.is_symlink():
        return []
    try:
        raw = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ["invalid-manifest"]
    profiles = raw.get("profile", [])
    if not isinstance(profiles, list):
        return ["invalid-manifest"]
    return sorted(
        str(profile.get("id"))
        for profile in profiles
        if isinstance(profile, dict) and profile.get("id")
    )


def _local_package_identity(root: Path) -> tuple[str, str]:
    pyproject = root / "pyproject.toml"
    if pyproject.is_file() and not pyproject.is_symlink():
        try:
            raw = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            raw = {}
        project = raw.get("project", {}) if isinstance(raw, dict) else {}
        if isinstance(project, dict):
            name = str(project.get("name") or root.name)
            if not _SAFE_NAME.fullmatch(name):
                raise LifecycleError(f"unsafe local package name: {name!r}")
            return (name, str(project.get("version") or "local"))
    if not _SAFE_NAME.fullmatch(root.name):
        raise LifecycleError(f"unsafe local package name: {root.name!r}")
    return root.name, "local"


def card_json(card: IntentCard) -> str:
    return json.dumps(card.to_dict(), indent=2, sort_keys=True)
