"""Pinned Git source providers and safe, non-executing source snapshots."""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterator
from urllib.parse import urlparse

from . import intent, paths
from .lifecycle import (
    LifecycleError,
    PackageRevision,
    SkillRef,
    content_id,
    digest_path,
)

SOURCE_RECEIPT_SCHEMA = "spindle.source-receipt/v1"
_GITHUB_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_COMMIT = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_FILES = 10_000


@dataclass(frozen=True)
class RemoteReference:
    provider: str
    locator: str
    requested_revision: str
    skill_selector: str | None
    original: str

    @property
    def pinned(self) -> bool:
        return bool(_COMMIT.fullmatch(self.requested_revision))


@dataclass(frozen=True)
class SourceReceipt:
    provider: str
    locator: str
    requested_revision: str
    resolved_commit: str
    tree_id: str
    snapshot_key: str
    content_digest: str

    @property
    def receipt_id(self) -> str:
        return content_id(self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "schema": SOURCE_RECEIPT_SCHEMA,
            "provider": self.provider,
            "locator": self.locator,
            "requested_revision": self.requested_revision,
            "resolved_commit": self.resolved_commit,
            "tree_id": self.tree_id,
            "snapshot_key": self.snapshot_key,
            "content_digest": self.content_digest,
        }
        return {"receipt_id": self.receipt_id, **payload} if include_id else payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SourceReceipt:
        if raw.get("schema") != SOURCE_RECEIPT_SCHEMA:
            raise LifecycleError("unsupported source receipt schema")
        receipt = cls(
            provider=str(raw["provider"]),
            locator=str(raw["locator"]),
            requested_revision=str(raw["requested_revision"]),
            resolved_commit=str(raw["resolved_commit"]),
            tree_id=str(raw["tree_id"]),
            snapshot_key=str(raw["snapshot_key"]),
            content_digest=str(raw["content_digest"]),
        )
        if raw.get("receipt_id") not in {None, receipt.receipt_id}:
            raise LifecycleError("source receipt content does not match receipt_id")
        if not _COMMIT.fullmatch(receipt.resolved_commit) or not _COMMIT.fullmatch(
            receipt.tree_id
        ):
            raise LifecycleError("source receipt has an invalid Git object identity")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", receipt.content_digest):
            raise LifecycleError("source receipt has an invalid content digest")
        expected_key = (
            content_id({"locator": receipt.locator}).removeprefix("sha256:")
            + "/"
            + receipt.resolved_commit
        )
        if receipt.snapshot_key != expected_key:
            raise LifecycleError("source receipt snapshot key is not canonical")
        return receipt


@dataclass(frozen=True)
class ResolvedCandidate:
    reference: RemoteReference
    source_receipt: SourceReceipt
    candidate: intent.LocalCandidate
    fetched: bool


def is_remote_reference(value: str) -> bool:
    return value.startswith(("github:", "skills.sh:", "git+", "git:"))


def parse_reference(value: str) -> RemoteReference:
    selector: str | None = None
    body = value
    if "#" in body:
        body, selector = body.rsplit("#", 1)
        if not selector or "/" in selector or selector in {".", ".."}:
            raise LifecycleError("remote skill selector must be one simple skill name")

    if body.startswith(("github:", "skills.sh:")):
        provider, source = body.split(":", 1)
        repository, revision = _split_revision(source)
        if not _GITHUB_REPO.fullmatch(repository):
            raise LifecycleError(
                f"{provider} references use {provider}:owner/repo@revision#skill"
            )
        locator = f"https://github.com/{repository}.git"
    elif body.startswith("git+"):
        provider = "git"
        locator, revision = _split_revision(body.removeprefix("git+"))
        _validate_locator(locator)
    elif body.startswith("git:"):
        provider = "git"
        locator, revision = _split_revision(body.removeprefix("git:"))
        path = Path(locator).expanduser()
        if not path.is_absolute():
            raise LifecycleError("git: local repository locators must be absolute")
        locator = str(path.resolve())
    else:
        raise LifecycleError(f"unsupported remote source reference: {value!r}")

    _validate_revision(revision)
    return RemoteReference(provider, locator, revision, selector, value)


def resolve_remote_candidate(
    reference: str,
    *,
    offline: bool = False,
    source_cache: Path | None = None,
    snapshot_root: Path | None = None,
    receipt_root: Path | None = None,
) -> ResolvedCandidate:
    requested = parse_reference(reference)
    cache = source_cache or paths.source_cache_dir()
    repository_key = content_id({"locator": requested.locator}).removeprefix("sha256:")
    with _source_mutex(cache / "locks" / f"{repository_key}.lock"):
        return _resolve_remote_candidate_unlocked(
            reference,
            offline=offline,
            source_cache=cache,
            snapshot_root=snapshot_root,
            receipt_root=receipt_root,
        )


def _resolve_remote_candidate_unlocked(
    reference: str,
    *,
    offline: bool,
    source_cache: Path,
    snapshot_root: Path | None,
    receipt_root: Path | None,
) -> ResolvedCandidate:
    requested = parse_reference(reference)
    cache = source_cache
    snapshots = snapshot_root or paths.source_snapshots_dir()
    receipts = receipt_root or paths.source_receipts_dir()
    repository_key = content_id({"locator": requested.locator}).removeprefix("sha256:")
    bare = cache / "git" / f"{repository_key}.git"
    fetched = False

    known = (
        _find_source_receipt(
            receipts,
            provider=requested.provider,
            locator=requested.locator,
            commit=requested.requested_revision.lower(),
        )
        if requested.pinned
        else None
    )
    if known is not None and offline:
        snapshot = snapshots / known.snapshot_key
        _verify_snapshot(snapshot, known.content_digest)
        receipt = SourceReceipt(
            provider=requested.provider,
            locator=requested.locator,
            requested_revision=requested.requested_revision,
            resolved_commit=known.resolved_commit,
            tree_id=known.tree_id,
            snapshot_key=known.snapshot_key,
            content_digest=known.content_digest,
        )
        _write_receipt(receipts, receipt)
        return _resolved_candidate(requested, receipt, snapshot, fetched=False)

    if bare.exists() and (bare.is_symlink() or not bare.is_dir()):
        raise LifecycleError("Git source cache path is not a regular directory")
    if not bare.is_dir():
        if offline:
            raise LifecycleError("remote source is not available in the offline cache")
        bare.parent.mkdir(parents=True, exist_ok=True)
        _run_git(
            "clone",
            "--mirror",
            "--no-local",
            "--",
            requested.locator,
            str(bare),
        )
        fetched = True
    else:
        observed_locator = _git_output(
            "--git-dir", str(bare), "config", "--get", "remote.origin.url"
        )
        if observed_locator != requested.locator:
            raise LifecycleError("Git source cache remote locator mismatch")
        if not offline:
            _run_git("--git-dir", str(bare), "remote", "update", "--prune")
            fetched = True

    commit = _git_output(
        "--git-dir",
        str(bare),
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{requested.requested_revision}^{{commit}}",
    ).lower()
    if not _COMMIT.fullmatch(commit):
        raise LifecycleError(f"Git resolved an invalid commit identity: {commit!r}")
    tree_id = _git_output(
        "--git-dir", str(bare), "rev-parse", f"{commit}^{{tree}}"
    ).lower()
    snapshot = snapshots / repository_key / commit
    if snapshot.exists():
        existing = _find_source_receipt(
            receipts,
            provider=requested.provider,
            locator=requested.locator,
            commit=commit,
        )
        if existing is None:
            raise LifecycleError(
                "source snapshot exists without an immutable provenance receipt"
            )
        _verify_snapshot(snapshot, existing.content_digest)
        receipt = SourceReceipt(
            provider=requested.provider,
            locator=requested.locator,
            requested_revision=requested.requested_revision,
            resolved_commit=commit,
            tree_id=tree_id,
            snapshot_key=f"{repository_key}/{commit}",
            content_digest=existing.content_digest,
        )
    else:
        _export_snapshot(bare, commit, snapshot)
        receipt = SourceReceipt(
            provider=requested.provider,
            locator=requested.locator,
            requested_revision=requested.requested_revision,
            resolved_commit=commit,
            tree_id=tree_id,
            snapshot_key=f"{repository_key}/{commit}",
            content_digest=digest_path(snapshot),
        )
    _write_receipt(receipts, receipt)
    return _resolved_candidate(requested, receipt, snapshot, fetched=fetched)


def _resolved_candidate(
    requested: RemoteReference,
    receipt: SourceReceipt,
    snapshot: Path,
    *,
    fetched: bool,
) -> ResolvedCandidate:
    local_ref = str(snapshot)
    if requested.skill_selector:
        local_ref += f"#{requested.skill_selector}"
    local = intent.resolve_local_candidate(local_ref)
    if local.revision.content_digest != receipt.content_digest:
        raise LifecycleError("resolved package bytes differ from the source receipt")
    source = SkillRef(
        provider=requested.provider,
        locator=requested.locator,
        revision=receipt.resolved_commit,
        content_digest=receipt.content_digest,
        subpath=local.relative_skill_path.as_posix(),
    )
    package_name = local.revision.name
    if package_name == snapshot.name:
        raw_name = Path(urlparse(requested.locator).path).name.removesuffix(".git")
        package_name = re.sub(r"[^A-Za-z0-9._-]+", "-", raw_name).strip("-.")
        if not package_name:
            package_name = "source-" + receipt.snapshot_key.split("/", 1)[0][:12]
    package_version = local.revision.version
    if package_version == "local":
        package_version = receipt.resolved_commit[:12]
    revision = PackageRevision(
        name=package_name,
        version=package_version,
        content_digest=local.revision.content_digest,
        source=source,
        root=local.revision.root,
        editable=False,
        skill_digests=local.revision.skill_digests,
    )
    candidate = intent.LocalCandidate(
        reference=requested.original,
        revision=revision,
        skill=local.skill,
        skill_path=local.skill_path,
    )
    return ResolvedCandidate(requested, receipt, candidate, fetched)


def _split_revision(value: str) -> tuple[str, str]:
    if "@" not in value:
        return value, "HEAD"
    locator, revision = value.rsplit("@", 1)
    if not locator or not revision:
        raise LifecycleError("remote references need non-empty locator and revision")
    return locator, revision


def _validate_locator(locator: str) -> None:
    parsed = urlparse(locator)
    if parsed.scheme not in {"https", "ssh", "file"}:
        raise LifecycleError("git+ locators support only https, ssh, and file URLs")
    if parsed.password:
        raise LifecycleError("embedded Git credentials are not allowed in source locators")
    if parsed.scheme in {"https", "ssh"} and not parsed.hostname:
        raise LifecycleError("remote Git URL is missing a host")


def _validate_revision(revision: str) -> None:
    if (
        not _REVISION.fullmatch(revision)
        or revision.startswith("-")
        or ".." in revision
        or "@{" in revision
    ):
        raise LifecycleError(f"unsafe Git revision: {revision!r}")


def _git_environment() -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _run_git(*arguments: str, capture: bool = True) -> subprocess.CompletedProcess:
    try:
        completed = subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", *arguments],
            check=False,
            capture_output=capture,
            text=capture,
            env=_git_environment(),
        )
    except OSError as exc:
        raise LifecycleError(f"could not execute Git: {exc}") from exc
    if completed.returncode != 0:
        stderr = completed.stderr.strip() if isinstance(completed.stderr, str) else ""
        raise LifecycleError(f"Git source resolution failed: {stderr or arguments[0]}")
    return completed


def _git_output(*arguments: str) -> str:
    output = _run_git(*arguments).stdout.strip()
    if not output:
        raise LifecycleError("Git source resolution returned no identity")
    return output


def _export_snapshot(bare: Path, commit: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix=".source-", dir=destination.parent))
    archive = temp_root / "source.tar"
    payload = temp_root / "payload"
    payload.mkdir()
    try:
        completed = _run_git(
            "--git-dir",
            str(bare),
            "archive",
            "--format=tar",
            "-o",
            str(archive),
            commit,
        )
        del completed
        if archive.stat().st_size > MAX_ARCHIVE_BYTES:
            raise LifecycleError("Git source archive exceeds the configured size limit")
        _safe_extract(archive, payload)
        try:
            payload.rename(destination)
        except FileExistsError:
            pass
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
    if not destination.is_dir():
        raise LifecycleError("Git source snapshot export was incomplete")


def _safe_extract(archive: Path, destination: Path) -> None:
    total = 0
    with tarfile.open(archive, mode="r:") as bundle:
        members = bundle.getmembers()
        if len(members) > MAX_ARCHIVE_FILES:
            raise LifecycleError("Git source archive exceeds extraction limits")
        names: set[PurePosixPath] = set()
        symlinks: set[PurePosixPath] = set()
        for member in members:
            total += max(member.size, 0)
            if total > MAX_ARCHIVE_BYTES:
                raise LifecycleError("Git source archive exceeds extraction limits")
            relative = PurePosixPath(member.name)
            if (
                relative.is_absolute()
                or not relative.parts
                or any(part in {"", ".", ".."} for part in relative.parts)
            ):
                raise LifecycleError(f"unsafe path in Git source archive: {member.name!r}")
            if relative in names:
                raise LifecycleError(
                    f"duplicate path in Git source archive: {member.name!r}"
                )
            names.add(relative)
            if any(parent in symlinks for parent in relative.parents):
                raise LifecycleError(
                    f"archive entry traverses a symlink: {member.name!r}"
                )
            if member.issym():
                link = PurePosixPath(member.linkname)
                if (
                    link.is_absolute()
                    or not link.parts
                    or any(part in {"", ".", ".."} for part in link.parts)
                ):
                    raise LifecycleError(
                        f"escaping symlink in Git source archive: {member.name!r}"
                    )
                symlinks.add(relative)
            elif not member.isdir() and not member.isfile():
                raise LifecycleError(
                    f"unsupported special file in Git source archive: {member.name!r}"
                )

        for relative in names:
            if any(parent in symlinks for parent in relative.parents):
                raise LifecycleError(
                    f"archive entry traverses a symlink: {relative.as_posix()!r}"
                )

        for member in members:
            relative = PurePosixPath(member.name)
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if member.issym():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(member.linkname)
                continue
            source = bundle.extractfile(member)
            if source is None:
                raise LifecycleError(f"missing file payload in archive: {member.name!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as handle:
                shutil.copyfileobj(source, handle)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)


def _find_source_receipt(
    root: Path,
    *,
    provider: str,
    locator: str,
    commit: str,
) -> SourceReceipt | None:
    if not root.is_dir():
        return None
    matches: list[SourceReceipt] = []
    for path in root.glob("*.json"):
        if path.is_symlink() or not path.is_file():
            raise LifecycleError(f"source receipt path is not a regular file: {path}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LifecycleError(f"invalid source receipt at {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise LifecycleError(f"source receipt at {path} must be an object")
        receipt = SourceReceipt.from_dict(raw)
        if path.stem != receipt.receipt_id.removeprefix("sha256:"):
            raise LifecycleError(f"source receipt filename mismatch at {path}")
        if (
            receipt.provider == provider
            and receipt.locator == locator
            and receipt.resolved_commit == commit
        ):
            matches.append(receipt)
    if not matches:
        return None
    # Requested mutable refs may yield multiple receipts for the same commit;
    # their snapshot identity must still agree.
    identities = {(item.snapshot_key, item.content_digest, item.tree_id) for item in matches}
    if len(identities) != 1:
        raise LifecycleError("source receipts disagree about one resolved commit")
    return sorted(matches, key=lambda item: item.receipt_id)[0]


def _verify_snapshot(snapshot: Path, expected_digest: str) -> None:
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise LifecycleError("cached source snapshot is missing")
    if digest_path(snapshot) != expected_digest:
        raise LifecycleError("cached source snapshot digest mismatch")


def _write_receipt(root: Path, receipt: SourceReceipt) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{receipt.receipt_id.removeprefix('sha256:')}.json"
    serialized = json.dumps(receipt.to_dict(), indent=2, sort_keys=True) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != serialized:
            raise LifecycleError(f"source receipt collision at {target}")
        return target
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{target.name}-", dir=root)
    temp = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
        try:
            os.link(temp, target)
        except FileExistsError:
            if target.read_text(encoding="utf-8") != serialized:
                raise LifecycleError(f"source receipt collision at {target}")
    finally:
        temp.unlink(missing_ok=True)
    return target


@contextmanager
def _source_mutex(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise LifecycleError(f"source lock path is a symlink: {path}")
    with path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
