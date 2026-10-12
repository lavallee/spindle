"""Non-executing trust preflight and future-lease quarantine controls."""

from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

from . import intent, paths, sources
from .lifecycle import LifecycleError, content_id, digest_path

PREFLIGHT_REPORT_SCHEMA = "spindle.preflight-report/v1"
QUARANTINE_EVENT_SCHEMA = "spindle.quarantine-event/v1"
QUARANTINE_INDEX_SCHEMA = "spindle.quarantine-index/v1"

_NETWORK = re.compile(
    r"\b(?:curl|wget|fetch|requests\.|urllib|httpx|npm\s+install|pip\s+install)\b|https?://",
    re.IGNORECASE,
)
_CREDENTIAL = re.compile(
    r"\b(?:api[_ -]?key|access[_ -]?token|secret|credential|password|\.env)\b",
    re.IGNORECASE,
)
_SHELL = re.compile(
    r"\b(?:subprocess\.|os\.system|child_process|shell=True|eval\s*\(|exec\s*\()",
    re.IGNORECASE,
)
_TEXT_SUFFIXES = frozenset(
    {"", ".md", ".txt", ".toml", ".json", ".yaml", ".yml", ".py", ".sh", ".js", ".ts"}
)
_LICENSE_NAMES = ("LICENSE*", "COPYING*", "NOTICE*")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class NamedAttestation:
    name: str
    artifact_digest: str
    semantics: str = "opaque-third-party-artifact"

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "artifact_digest": self.artifact_digest,
            "semantics": self.semantics,
        }


@dataclass(frozen=True)
class PreflightReport:
    package_digest: str
    skill_digest: str
    intent_card_id: str
    source_receipt_id: str | None
    structure: tuple[dict[str, Any], ...]
    licenses: tuple[dict[str, str], ...]
    risk_findings: tuple[dict[str, str], ...]
    authority_required: tuple[str, ...]
    authority_granted: tuple[str, ...]
    attestations: tuple[NamedAttestation, ...]
    composition: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def report_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "schema": PREFLIGHT_REPORT_SCHEMA,
            "package_digest": self.package_digest,
            "skill_digest": self.skill_digest,
            "intent_card_id": self.intent_card_id,
            "source_receipt_id": self.source_receipt_id,
            "structure": list(self.structure),
            "licenses": list(self.licenses),
            "risk_findings": list(self.risk_findings),
            "authority": {
                "required": list(self.authority_required),
                "granted": list(self.authority_granted),
            },
            "attestations": [item.to_dict() for item in self.attestations],
            "composition": self.composition,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "execution": "none",
        }
        return {"report_id": self.report_id, **payload} if include_id else payload


@dataclass(frozen=True)
class QuarantineEvent:
    package_digest: str
    action: str
    reason: str
    actor: str
    effective_at: str
    previous_event_id: str | None

    def __post_init__(self) -> None:
        if not _DIGEST.fullmatch(self.package_digest):
            raise LifecycleError("quarantine package digest must be a full sha256 digest")
        if self.action not in {"quarantine", "unquarantine"}:
            raise LifecycleError(f"unsupported quarantine action: {self.action!r}")
        if not self.reason.strip() or not self.actor.strip() or not self.effective_at.strip():
            raise LifecycleError("quarantine event reason, actor, and time are required")

    @property
    def event_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "schema": QUARANTINE_EVENT_SCHEMA,
            "package_digest": self.package_digest,
            "action": self.action,
            "reason": self.reason,
            "actor": self.actor,
            "effective_at": self.effective_at,
            "previous_event_id": self.previous_event_id,
        }
        return {"event_id": self.event_id, **payload} if include_id else payload


def load_attestations(values: Iterable[str]) -> tuple[NamedAttestation, ...]:
    records: list[NamedAttestation] = []
    for value in values:
        name, separator, raw_path = value.partition("=")
        if not separator or not name.strip() or not raw_path:
            raise LifecycleError("attestations use NAME=PATH")
        artifact = Path(raw_path).expanduser()
        if not artifact.is_file():
            raise LifecycleError(f"attestation artifact is not a file: {artifact}")
        records.append(NamedAttestation(name.strip(), digest_path(artifact)))
    names = [item.name for item in records]
    if len(names) != len(set(names)):
        raise LifecycleError("attestation names must be unique")
    return tuple(sorted(records, key=lambda item: item.name))


def preflight_candidate(
    candidate: intent.LocalCandidate,
    card: intent.IntentCard,
    *,
    source_receipt: sources.SourceReceipt | None = None,
    allow_executable: bool = False,
    allow_network: bool = False,
    allow_credentials: bool = False,
    allowed_tools: Iterable[str] = (),
    attestations: Iterable[NamedAttestation] = (),
) -> PreflightReport:
    """Inspect static bytes only; no candidate command, import, or hook is run."""

    facts = card.package_facts
    requirements = facts["requirements"]
    authority = facts["authority"]
    blockers: list[str] = []
    warnings: list[str] = []
    structure: list[dict[str, Any]] = []

    skill_md = candidate.skill_path / "SKILL.md"
    skill_ok = skill_md.is_file() and not skill_md.is_symlink()
    structure.append({"check": "skill-manifest", "state": "pass" if skill_ok else "block"})
    if not skill_ok:
        blockers.append("candidate needs one regular SKILL.md")

    missing = tuple(str(item) for item in requirements.get("missing_references", ()))
    outside = tuple(
        str(item["target"])
        for item in requirements.get("references", ())
        if item.get("state") == "outside-package"
    )
    structure.append(
        {
            "check": "references",
            "state": "pass" if not missing and not outside else "block",
            "missing": list(missing),
            "outside_package": list(outside),
        }
    )
    if missing:
        blockers.append("candidate has missing local references: " + ", ".join(missing))
    if outside:
        blockers.append("candidate has references outside its package: " + ", ".join(outside))

    profiles = facts.get("evidence", {}).get("runtime_profiles", [])
    if "invalid-manifest" in profiles:
        blockers.append("candidate realization manifest is invalid")
    structure.append(
        {
            "check": "realization-manifest",
            "state": "block" if "invalid-manifest" in profiles else "pass",
        }
    )

    root = Path(candidate.revision.root)
    licenses = _discover_licenses(root)
    if not licenses:
        warnings.append("no license artifact was discovered")

    risk_findings = _static_risk_findings(candidate.skill_path)
    required: set[str] = set()
    executable = tuple(
        sorted(
            {
                *map(str, authority.get("executable_resources", ())),
                *map(str, authority.get("script_like_resources", ())),
            }
        )
    )
    if executable:
        required.add("executable-resources")
    if any(item["category"] == "network" for item in risk_findings):
        required.add("network")
    if any(item["category"] == "credentials" for item in risk_findings):
        required.add("credentials")
    declared_tools = tuple(sorted(map(str, authority.get("declared_tools", ()))))
    required.update(f"tool:{tool}" for tool in declared_tools)

    granted: set[str] = set()
    if allow_executable:
        granted.add("executable-resources")
    if allow_network:
        granted.add("network")
    if allow_credentials:
        granted.add("credentials")
    granted.update(f"tool:{tool}" for tool in allowed_tools)
    unapproved = sorted(required - granted)
    if unapproved:
        blockers.append("explicit authority approval required: " + ", ".join(unapproved))

    if source_receipt is not None:
        if source_receipt.content_digest != candidate.revision.content_digest:
            blockers.append("source receipt does not match candidate package bytes")
        structure.append(
            {
                "check": "source-provenance",
                "state": "pass"
                if source_receipt.content_digest == candidate.revision.content_digest
                else "block",
                "resolved_commit": source_receipt.resolved_commit,
            }
        )

    return PreflightReport(
        package_digest=candidate.revision.content_digest,
        skill_digest=dict(candidate.revision.skill_digests)[candidate.skill],
        intent_card_id=card.card_id,
        source_receipt_id=source_receipt.receipt_id if source_receipt else None,
        structure=tuple(structure),
        licenses=licenses,
        risk_findings=risk_findings,
        authority_required=tuple(sorted(required)),
        authority_granted=tuple(sorted(granted & required)),
        attestations=tuple(sorted(attestations, key=lambda item: item.name)),
        composition=str(card.fit_analysis.get("composition", "unknown")),
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


def write_preflight_report(
    report: PreflightReport, root: Path | None = None
) -> Path:
    target_root = root or paths.preflight_receipts_dir()
    return _write_immutable(target_root, report.report_id, report.to_dict())


def quarantine_status(
    package_digest: str, index_path: Path | None = None
) -> dict[str, Any] | None:
    index = _read_index(index_path or paths.quarantine_index_file())
    value = index["packages"].get(package_digest)
    return dict(value) if isinstance(value, dict) else None


def assert_not_quarantined(package_digest: str) -> None:
    status = quarantine_status(package_digest)
    if status is not None and status.get("status") == "quarantined":
        raise LifecycleError(
            f"package {package_digest} is quarantined by {status.get('event_id')}: "
            f"{status.get('reason')}"
        )


def set_quarantine(
    package_digest: str,
    *,
    quarantined: bool,
    reason: str,
    actor: str,
    effective_at: str | None = None,
    dry_run: bool = False,
    index_path: Path | None = None,
    events_root: Path | None = None,
) -> QuarantineEvent:
    index_target = index_path or paths.quarantine_index_file()
    event_root = events_root or paths.quarantine_events_dir()
    with _index_lock(index_target):
        index = _read_index(index_target)
        current = index["packages"].get(package_digest)
        event = QuarantineEvent(
            package_digest=package_digest,
            action="quarantine" if quarantined else "unquarantine",
            reason=reason,
            actor=actor,
            effective_at=effective_at or datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            previous_event_id=(
                str(current.get("event_id")) if isinstance(current, dict) else None
            ),
        )
        if dry_run:
            return event
        _write_immutable(event_root, event.event_id, event.to_dict())
        index["packages"][package_digest] = {
            "status": "quarantined" if quarantined else "available",
            "event_id": event.event_id,
            "reason": reason,
        }
        _write_json_atomic(index_target, index)
        return event


def _discover_licenses(root: Path) -> tuple[dict[str, str], ...]:
    found: dict[str, dict[str, str]] = {}
    for pattern in _LICENSE_NAMES:
        for candidate in root.glob(pattern):
            if candidate.is_file() and not candidate.is_symlink():
                relative = candidate.relative_to(root).as_posix()
                found[relative] = {"path": relative, "content_digest": digest_path(candidate)}
    return tuple(found[key] for key in sorted(found))


def _static_risk_findings(root: Path) -> tuple[dict[str, str], ...]:
    findings: set[tuple[str, str, str]] = set()
    for candidate in sorted(root.rglob("*")):
        if (
            not candidate.is_file()
            or candidate.is_symlink()
            or candidate.suffix.lower() not in _TEXT_SUFFIXES
            or candidate.stat().st_size > 1024 * 1024
        ):
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relative = candidate.relative_to(root).as_posix()
        for category, pattern, detail in (
            ("network", _NETWORK, "network-like static indicator"),
            ("credentials", _CREDENTIAL, "credential-like static indicator"),
            ("shell", _SHELL, "process-execution static indicator"),
        ):
            if pattern.search(text):
                findings.add((category, relative, detail))
    return tuple(
        {"category": category, "path": path, "detail": detail}
        for category, path, detail in sorted(findings)
    )


def _read_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": QUARANTINE_INDEX_SCHEMA, "packages": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError(f"invalid quarantine index at {path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema") != QUARANTINE_INDEX_SCHEMA:
        raise LifecycleError(f"unsupported quarantine index at {path}")
    if not isinstance(raw.get("packages"), dict):
        raise LifecycleError(f"quarantine index packages must be an object at {path}")
    return raw


@contextmanager
def _index_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_immutable(root: Path, identity: str, payload: dict[str, Any]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{identity.removeprefix('sha256:')}.json"
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != serialized:
            raise LifecycleError(f"immutable receipt collision at {target}")
        return target
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{target.name}-", dir=root)
    temporary = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.read_text(encoding="utf-8") != serialized:
                raise LifecycleError(f"immutable receipt collision at {target}")
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
