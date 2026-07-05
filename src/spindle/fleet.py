"""Cross-machine ledger sync via git.

Each machine has a stable UUID stored at ``machine_id_file()``. On sync we
snapshot the local ledger (``ledger_path()``) into a shared git working
copy at ``fleet_repo()`` under ``events/<machine-id>.jsonl`` and push.
Materialized fleet state is the union of every machine's events file.

The per-machine filename is what makes append-only safe: two machines
syncing concurrently always touch different paths, so ``git pull --rebase``
never has to merge content — only file additions.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .paths import fleet_repo, ledger_path, machine_id_file


# ---- machine id ---------------------------------------------------------

def machine_id() -> str:
    """Stable UUID v4 for this machine; created on first call."""
    p = machine_id_file()
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    mid = str(uuid.uuid4())
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(mid + "\n", encoding="utf-8")
    return mid


# ---- git wrapper --------------------------------------------------------

class GitError(RuntimeError):
    """A git subprocess returned a non-zero exit code."""


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    # -c flags supply a default identity so commits work in fresh test envs
    # where the user's global git config is unset.
    cmd = [
        "git",
        "-C", str(repo),
        "-c", "user.name=spindle",
        "-c", "user.email=spindle@local",
        "-c", "commit.gpgsign=false",
        *args,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} (rc={proc.returncode}): {proc.stderr.strip()}"
        )
    return proc


def _ensure_repo(repo: Path, remote: str | None) -> None:
    """Init the fleet repo if absent; set/update origin if requested."""
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        _git(repo, "init", "-q")
    if remote:
        existing = _git(repo, "remote", check=False)
        names = existing.stdout.split()
        if "origin" in names:
            _git(repo, "remote", "set-url", "origin", remote)
        else:
            _git(repo, "remote", "add", "origin", remote)


def _current_remote(repo: Path) -> str | None:
    proc = _git(repo, "remote", "get-url", "origin", check=False)
    if proc.returncode != 0:
        return None
    url = proc.stdout.strip()
    return url or None


def _has_staged_changes(repo: Path) -> bool:
    proc = _git(repo, "status", "--porcelain")
    return bool(proc.stdout.strip())


# ---- sync ---------------------------------------------------------------

@dataclass
class SyncResult:
    repo: Path
    machine: str
    committed: bool
    pulled: bool
    pushed: bool
    remote: str | None
    detail: str = ""


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fleet_sync(
    remote: str | None = None,
    *,
    repo: Path | None = None,
    local_events: Path | None = None,
    mid: str | None = None,
    push: bool = True,
) -> SyncResult:
    """Snapshot local events into the fleet repo, commit, pull, push.

    - ``remote``: if given, set as ``origin`` and persist for later runs.
    - ``push``: skip network ops when False (used by tests/dry-run).
    """
    repo = repo or fleet_repo()
    local_events = local_events or ledger_path()
    mid = mid or machine_id()

    _ensure_repo(repo, remote)
    effective_remote = _current_remote(repo)

    events_dir = repo / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    target = events_dir / f"{mid}.jsonl"
    if local_events.exists():
        shutil.copyfile(local_events, target)
    else:
        # nothing to publish yet, but make the file exist so other machines
        # see this machine in `fleet status` once it lands
        target.touch()

    _git(repo, "add", "events")
    committed = False
    if _has_staged_changes(repo):
        _git(repo, "commit", "-m", f"sync {mid} {_now_iso()}")
        committed = True

    pulled = pushed = False
    detail = ""
    if push and effective_remote:
        # Pull first so we don't push over a remote that's ahead.
        pull = _git(repo, "pull", "--rebase", "--autostash", "origin", "HEAD", check=False)
        if pull.returncode == 0:
            pulled = True
        else:
            detail = pull.stderr.strip()
        push_proc = _git(repo, "push", "origin", "HEAD", check=False)
        if push_proc.returncode == 0:
            pushed = True
        else:
            detail = (detail + "\n" + push_proc.stderr.strip()).strip()

    return SyncResult(
        repo=repo,
        machine=mid,
        committed=committed,
        pulled=pulled,
        pushed=pushed,
        remote=effective_remote,
        detail=detail,
    )


# ---- status -------------------------------------------------------------

@dataclass
class MachineState:
    machine: str
    distributions: dict[str, str] = field(default_factory=dict)
    last_event_ts: str | None = None
    event_count: int = 0


def _event_kind(obj: dict) -> str | None:
    return obj.get("kind") or obj.get("event")


def _apply_event(state: MachineState, obj: dict) -> None:
    state.event_count += 1
    ts = obj.get("ts")
    if ts and (state.last_event_ts is None or ts > state.last_event_ts):
        state.last_event_ts = ts
    kind = _event_kind(obj)
    if kind == "dist_install":
        dist = obj.get("distribution")
        if dist:
            state.distributions[dist] = obj.get("version", "?")
    elif kind == "dist_uninstall":
        dist = obj.get("distribution")
        if dist:
            state.distributions.pop(dist, None)


def _read_events(path: Path) -> list[dict]:
    out: list[dict] = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def fleet_status(*, repo: Path | None = None) -> list[MachineState]:
    """Read every events/<machine>.jsonl in the fleet repo, fold per-machine."""
    repo = repo or fleet_repo()
    events_dir = repo / "events"
    if not events_dir.exists():
        return []
    machines: list[MachineState] = []
    for p in sorted(events_dir.glob("*.jsonl")):
        state = MachineState(machine=p.stem)
        for obj in _read_events(p):
            _apply_event(state, obj)
        machines.append(state)
    return machines
