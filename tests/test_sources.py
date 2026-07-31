from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path

import pytest

from spindle.lifecycle import LifecycleError, digest_path
from spindle.sources import (
    _safe_extract,
    parse_reference,
    resolve_remote_candidate,
)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "origin"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "spindle@example.test")
    _git(repo, "config", "user.name", "Spindle Test")
    skill = repo / "skills" / "remote-demo"
    skill.mkdir(parents=True)
    skill.joinpath("SKILL.md").write_text(
        "---\nname: remote-demo\ndescription: Review a migration.\n---\n\n# Review\n",
        encoding="utf-8",
    )
    repo.joinpath("LICENSE").write_text("MIT fixture\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    return repo, _git(repo, "rev-parse", "HEAD")


def _resolve(reference: str, state: Path, *, offline: bool = False):
    return resolve_remote_candidate(
        reference,
        offline=offline,
        source_cache=state / "cache",
        snapshot_root=state / "snapshots",
        receipt_root=state / "receipts",
    )


def test_mutable_git_reference_is_pinned_and_moves_side_by_side(tmp_path):
    repo, first_commit = _repository(tmp_path)
    state = tmp_path / "state"
    first = _resolve(f"git:{repo}@main#remote-demo", state)

    assert first.reference.pinned is False
    assert first.source_receipt.requested_revision == "main"
    assert first.source_receipt.resolved_commit == first_commit
    assert first.candidate.revision.source.revision == first_commit
    assert first.candidate.revision.editable is False
    assert first.candidate.revision.name == "origin"
    assert first.candidate.revision.version == first_commit[:12]
    assert Path(first.candidate.revision.root).is_relative_to(state / "snapshots")
    first_receipt = first.source_receipt.receipt_id

    repo.joinpath("skills/remote-demo/SKILL.md").write_text(
        "---\nname: remote-demo\ndescription: Review a migration.\n---\n\n# Review v2\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "second")
    second_commit = _git(repo, "rev-parse", "HEAD")
    second = _resolve(f"git:{repo}@main#remote-demo", state)

    assert second.source_receipt.resolved_commit == second_commit
    assert second.candidate.revision.name == first.candidate.revision.name
    assert second.source_receipt.receipt_id != first_receipt
    assert second.candidate.revision.content_digest != first.candidate.revision.content_digest
    assert len(list((state / "receipts").glob("*.json"))) == 2


def test_offline_pinned_reuse_verifies_snapshot_without_origin(tmp_path):
    repo, commit = _repository(tmp_path)
    state = tmp_path / "state"
    online = _resolve(f"git:{repo}@{commit}#remote-demo", state)
    repo.rename(tmp_path / "origin-unavailable")

    offline = _resolve(f"git:{repo}@{commit}#remote-demo", state, offline=True)

    assert offline.fetched is False
    assert offline.source_receipt.receipt_id == online.source_receipt.receipt_id
    assert offline.candidate.revision.content_digest == online.candidate.revision.content_digest


def test_cached_snapshot_poisoning_fails_closed(tmp_path):
    repo, commit = _repository(tmp_path)
    state = tmp_path / "state"
    resolved = _resolve(f"git:{repo}@{commit}#remote-demo", state)
    root = Path(resolved.candidate.revision.root)
    root.joinpath("skills/remote-demo/SKILL.md").write_text("poisoned\n", encoding="utf-8")
    assert digest_path(root) != resolved.source_receipt.content_digest

    with pytest.raises(LifecycleError, match="snapshot digest mismatch"):
        _resolve(f"git:{repo}@{commit}#remote-demo", state, offline=True)


def test_safe_extract_rejects_traversal_and_symlink_parent(tmp_path):
    traversal = tmp_path / "traversal.tar"
    with tarfile.open(traversal, "w") as bundle:
        info = tarfile.TarInfo("../outside")
        info.size = 1
        bundle.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(LifecycleError, match="unsafe path"):
        _safe_extract(traversal, tmp_path / "one")

    symlink_parent = tmp_path / "symlink-parent.tar"
    with tarfile.open(symlink_parent, "w") as bundle:
        link = tarfile.TarInfo("directory")
        link.type = tarfile.SYMTYPE
        link.linkname = "elsewhere"
        bundle.addfile(link)
        child = tarfile.TarInfo("directory/payload")
        child.size = 1
        bundle.addfile(child, io.BytesIO(b"x"))
    with pytest.raises(LifecycleError, match="traverses a symlink"):
        _safe_extract(symlink_parent, tmp_path / "two")


@pytest.mark.parametrize(
    "reference",
    [
        "github:owner/repo@../main#skill",
        "github:owner/repo@main#../skill",
        "git+http://example.test/repo@main#skill",
        "git:relative/path@main#skill",
    ],
)
def test_unsafe_remote_references_are_rejected(reference):
    with pytest.raises(LifecycleError):
        parse_reference(reference)
