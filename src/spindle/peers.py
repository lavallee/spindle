"""Peer registry — read/write peers.toml.

Lightweight on purpose: one TOML file with a flat list of [[peer]]
entries. Each peer has: slug, name, url, kind, last_seen, our_take,
notes. Hand-editable, version-controlled.
"""

from __future__ import annotations

import sys
from datetime import date

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from . import active as active_mod


def _peers_file():
    return active_mod.source_dir() / "peers" / "peers.toml"


def _read() -> dict:
    p = _peers_file()
    if not p.exists():
        return {"peer": []}
    with open(p, "rb") as fh:
        return tomllib.load(fh)


def _write(data: dict) -> None:
    """Hand-roll TOML writer for the simple shape we use; avoids a
    third-party dep. Each peer is a [[peer]] table with simple fields."""
    p = _peers_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# spindle peer registry — libraries we watch for ideas to borrow")
    lines.append("# edit by hand or via `spindle peers add/remove`")
    lines.append("")
    for peer in data.get("peer", []):
        lines.append("[[peer]]")
        for key in ("slug", "name", "url", "kind", "last_seen", "our_take", "notes"):
            v = peer.get(key)
            if v is None or v == "":
                continue
            lines.append(f'{key} = "{v}"')
        lines.append("")
    p.write_text("\n".join(lines).rstrip() + "\n")


def list_peers() -> list[dict]:
    return list(_read().get("peer", []))


def add(*, slug: str, name: str, url: str, kind: str = "github",
        our_take: str = "", notes: str = "") -> bool:
    data = _read()
    peers = data.get("peer", [])
    if any(p.get("slug") == slug for p in peers):
        return False
    peers.append({
        "slug": slug,
        "name": name,
        "url": url,
        "kind": kind,
        "last_seen": date.today().isoformat(),
        "our_take": our_take,
        "notes": notes,
    })
    data["peer"] = peers
    _write(data)
    return True


def remove(slug: str) -> bool:
    data = _read()
    peers = data.get("peer", [])
    n = len(peers)
    peers = [p for p in peers if p.get("slug") != slug]
    if len(peers) == n:
        return False
    data["peer"] = peers
    _write(data)
    return True


def get(slug: str) -> dict | None:
    for p in list_peers():
        if p.get("slug") == slug:
            return p
    return None


def touch(slug: str, when: str | None = None) -> bool:
    """Advance a peer's ``last_seen`` to *when* (ISO date) or today.

    Called after a scout pass applies so the next pass diffs from the date we
    actually looked, not the stale seed. Returns False if no such peer (so the
    caller can stay quiet for non-peer result files).
    """
    data = _read()
    peers = data.get("peer", [])
    for p in peers:
        if p.get("slug") == slug:
            p["last_seen"] = when or date.today().isoformat()
            data["peer"] = peers
            _write(data)
            return True
    return False
