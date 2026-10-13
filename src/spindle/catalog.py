"""The catalog: pinned sources of skills that are available but not installed.

``<house>/catalog.toml`` lists sources. A Git source is pinned to one commit and
exported through ``spindle.sources`` (no hooks, no execution); a local source is
a directory read in place. ``sync`` walks every source for ``SKILL.md`` files and
writes one searchable index. Nothing in the catalog is visible to a harness
until ``spindle use`` hands a skill to an agent.

Staying current is one command: ``check_updates`` resolves each source's tracked
branch and reports what a newer commit would add, change, or remove;
``apply_update`` moves the pin, which is an ordinary reviewable diff in the house.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from . import paths, sources, trust
from .house import House, HouseError, frontmatter, skill_body
from .lifecycle import LifecycleError, digest_path

CATALOG_INDEX_SCHEMA = "spindle.catalog-index/v1"
EXCERPT_CHARS = 4000
_SKIP_DIRS = frozenset(
    {".git", "node_modules", "__pycache__", ".venv", "dist", "build", "test",
     "tests", "fixtures", "__fixtures__", "evals"}
)
# A skill that hard-codes its own install location cannot be read from a snapshot.
_INSTALL_PATH = re.compile(r"(?:~|\$HOME|\$\{HOME\})/\.(?:claude|agents|codex)/skills/")


@dataclass(frozen=True)
class Source:
    slug: str
    ref: str | None
    path: Path | None
    track: str
    include: tuple[str, ...]
    exclude: tuple[str, ...]
    notes: str
    max_archive_mb: int = 64

    @property
    def pinned_commit(self) -> str | None:
        if self.ref is None:
            return None
        return self.ref.rsplit("@", 1)[1] if "@" in self.ref else None

    def tracking_ref(self) -> str:
        assert self.ref is not None
        return self.ref.rsplit("@", 1)[0] + "@" + self.track


def catalog_file(house: House) -> Path:
    return house.root / "catalog.toml"


def index_file() -> Path:
    return paths.spindle_home() / "catalog" / "index.json"


def load_sources(house: House) -> list[Source]:
    path = catalog_file(house)
    if not path.is_file():
        return []
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise HouseError(f"cannot read {path}: {exc}") from exc
    found: list[Source] = []
    seen: set[str] = set()
    for item in raw.get("source") or ():
        slug = str(item.get("slug") or "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug) or slug in seen:
            raise HouseError(f"catalog source slug is missing or repeated: {slug!r}")
        seen.add(slug)
        ref, local = item.get("ref"), item.get("path")
        if bool(ref) == bool(local):
            raise HouseError(f"catalog source {slug!r} needs exactly one of ref, path")
        found.append(
            Source(
                slug=slug,
                ref=str(ref) if ref else None,
                path=(house.root / str(local)).resolve() if local else None,
                track=str(item.get("track", "main")),
                include=tuple(item.get("include") or ()),
                exclude=tuple(item.get("exclude") or ()),
                notes=str(item.get("notes", "")),
                max_archive_mb=int(item.get("max_archive_mb", 64)),
            )
        )
    return found


def _wanted(source: Source, relative: str) -> bool:
    if source.include and not any(fnmatch.fnmatch(relative, p) for p in source.include):
        return False
    return not any(fnmatch.fnmatch(relative, p) for p in source.exclude)


def scan(source: Source, root: Path, commit: str | None, kernel: frozenset[str]):
    """Index entries for every skill under *root*, first name wins."""
    entries: dict[str, dict[str, Any]] = {}
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
        if "SKILL.md" not in files:
            continue
        skill_dir = Path(current)
        relative = skill_dir.relative_to(root).as_posix()
        if relative != ".":
            dirs[:] = []  # a suite's root skill may sit above its member skills
        if not _wanted(source, relative):
            continue
        try:
            text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        meta = frontmatter(text)
        name = meta.get("name") or (skill_dir.name if relative != "." else source.slug)
        description = meta.get("description", "")
        if not description or name in entries:
            continue
        body = skill_body(text)
        entries[name] = {
            "ref": f"{source.slug}/{name}",
            "source": source.slug,
            "name": name,
            "description": description,
            "path": str(skill_dir),
            "rel": relative,
            "commit": commit,
            "digest": digest_path(skill_dir),
            "words": len(body.split()),
            "requires_install": bool(_INSTALL_PATH.search(body)),
            "risks": sorted(
                {finding["category"] for finding in trust._static_risk_findings(skill_dir)}
            ),
            "kernel": name in kernel,
            "excerpt": body[:EXCERPT_CHARS],
        }
    return [entries[name] for name in sorted(entries)]


def _resolve(source: Source, *, offline: bool, reference: str | None = None):
    """Return ``(root, commit)`` for a source, fetching only when allowed."""
    if source.path is not None:
        if not source.path.is_dir():
            raise HouseError(f"catalog path does not exist: {source.path}")
        return source.path, None
    resolved = sources.resolve_remote_snapshot(
        reference or source.ref or "",
        offline=offline,
        max_archive_bytes=source.max_archive_mb * 1024 * 1024,
    )
    return resolved.snapshot, resolved.source_receipt.resolved_commit


def sync(
    house: House, *, offline: bool = False, only: str | None = None
) -> dict[str, Any]:
    """Rebuild the index (or one source's part of it) from the pinned sources."""
    kernel = frozenset(house.kernel)
    previous = load_index(missing_ok=True)
    kept = {s["slug"]: s for s in previous.get("sources", [])}
    by_source: dict[str, list[dict[str, Any]]] = {}
    for entry in previous.get("skills", []):
        by_source.setdefault(entry["source"], []).append(entry)
    summaries: list[dict[str, Any]] = []
    declared = load_sources(house)
    for source in declared:
        if only and source.slug != only:
            if source.slug in kept:
                summaries.append(kept[source.slug])
            continue
        summary: dict[str, Any] = {"slug": source.slug, "ref": source.ref,
                                   "path": str(source.path) if source.path else None}
        try:
            if source.ref and not sources.parse_reference(source.ref).pinned:
                raise HouseError("ref must pin a full commit; run `spindle catalog "
                                 f"update {source.slug} --apply`")
            root, commit = _resolve(source, offline=offline)
            by_source[source.slug] = scan(source, root, commit, kernel)
            summary.update(commit=commit, skills=len(by_source[source.slug]))
        except (HouseError, LifecycleError, OSError) as exc:
            by_source.pop(source.slug, None)
            summary.update(error=str(exc), skills=0)
        summaries.append(summary)
    live = {source.slug for source in declared}
    index = {
        "schema": CATALOG_INDEX_SCHEMA,
        "house_version": house.version,
        "synced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": summaries,
        "skills": [
            entry
            for slug in sorted(by_source)
            if slug in live
            for entry in by_source[slug]
        ],
    }
    path = index_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(index, indent=1, sort_keys=True) + "\n", "utf-8")
    os.replace(temporary, path)
    return index


def load_index(*, missing_ok: bool = False) -> dict[str, Any]:
    path = index_file()
    if not path.is_file():
        if missing_ok:
            return {"schema": CATALOG_INDEX_SCHEMA, "sources": [], "skills": []}
        raise HouseError("the catalog has not been synced; run `spindle catalog sync`")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HouseError(f"cannot read {path}: {exc}") from exc


def read_roots(index: dict[str, Any]) -> list[str]:
    """The directories that hold every indexed skill, for sandbox allow-lists.

    A runtime whose agent may only read named directories needs these to let
    it open a skill by path, including one it finds for itself mid-task.
    """
    roots: set[str] = set()
    snapshots = str(paths.source_snapshots_dir())
    for entry in index.get("skills", []):
        path = entry["path"]
        if path.startswith(snapshots + os.sep):
            roots.add(snapshots)
        else:
            rel = entry.get("rel") or "."
            root = Path(path)
            for _ in Path(rel).parts if rel != "." else ():
                root = root.parent
            roots.add(str(root))
    return sorted(roots)


def find_entry(index: dict[str, Any], ref: str) -> dict[str, Any]:
    """Look a skill up by ``source/name``, or by bare name when it is unambiguous."""
    matches = [
        entry
        for entry in index.get("skills", [])
        if entry["ref"] == ref or ("/" not in ref and entry["name"] == ref)
    ]
    if not matches:
        raise HouseError(f"no catalog skill named {ref!r}; try `spindle find`")
    if len(matches) > 1:
        options = ", ".join(entry["ref"] for entry in matches)
        raise HouseError(f"{ref!r} is ambiguous; use one of: {options}")
    return matches[0]


def check_updates(house: House, only: str | None = None) -> list[dict[str, Any]]:
    """Compare each Git source's pin with the head of its tracked branch."""
    kernel = frozenset(house.kernel)
    reports: list[dict[str, Any]] = []
    for source in load_sources(house):
        if source.ref is None or (only and source.slug != only):
            continue
        report: dict[str, Any] = {"slug": source.slug, "pinned": source.pinned_commit,
                                  "track": source.track}
        try:
            head_root, head = _resolve(
                source, offline=False, reference=source.tracking_ref()
            )
            report["head"] = head
            if head == source.pinned_commit:
                report["state"] = "current"
            else:
                new = {e["name"]: e for e in scan(source, head_root, head, kernel)}
                old: dict[str, dict[str, Any]] = {}
                if sources.parse_reference(source.ref).pinned:
                    old_root, commit = _resolve(source, offline=False)
                    old = {e["name"]: e for e in scan(source, old_root, commit, kernel)}
                report.update(
                    state="behind",
                    added=sorted(set(new) - set(old)),
                    removed=sorted(set(old) - set(new)),
                    changed=sorted(
                        n for n in set(new) & set(old)
                        if new[n]["digest"] != old[n]["digest"]
                    ),
                    new_risks={
                        name: entry["risks"]
                        for name, entry in sorted(new.items())
                        if entry["risks"]
                        and set(entry["risks"]) - set(old.get(name, {}).get("risks", []))
                    },
                )
        except (HouseError, LifecycleError, OSError) as exc:
            report.update(state="error", error=str(exc))
        reports.append(report)
    return reports


def apply_update(house: House, slug: str, commit: str) -> None:
    """Move one source's pin to *commit* by rewriting its ``ref`` line."""
    source = next((s for s in load_sources(house) if s.slug == slug), None)
    if source is None or source.ref is None:
        raise HouseError(f"no Git catalog source named {slug!r}")
    base = source.ref.rsplit("@", 1)[0]
    path = catalog_file(house)
    text = path.read_text(encoding="utf-8")
    old_line = re.compile(r'^(\s*ref\s*=\s*)"' + re.escape(source.ref) + r'"', re.M)
    updated, count = old_line.subn(rf'\g<1>"{base}@{commit}"', text)
    if count != 1:
        raise HouseError(f"could not find a unique ref line for {slug!r} in {path}")
    path.write_text(updated, encoding="utf-8")
