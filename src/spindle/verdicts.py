"""Verdict store — one markdown file per pattern/skill/idea we've evaluated.

Each verdict has YAML frontmatter and a free-form body. Frontmatter
fields:
  slug:           kebab-case, used as filename
  source:         peer slug this came from (gstack, superpowers, …)
  url:            link to the source artifact
  first_seen:     ISO date
  verdict:        tracking | borrow | graft | ignore | try
  status:         candidate | in-use | rejected | superseded
  last_reviewed:  ISO date

Read/write/list — that's the whole API.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import spindle.active as active_mod
import spindle.paths as _paths


_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _verdicts_dir() -> Path:
    return active_mod.source_dir() / "verdicts"


def _path_for(slug: str) -> Path:
    return _verdicts_dir() / f"{slug}.md"


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    fm_text = m.group(1)
    body = text[m.end():]
    fm: dict = {}
    for line in fm_text.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, body


def list_verdicts() -> list[dict]:
    d = _verdicts_dir()
    if not d.exists():
        return []
    out: list[dict] = []
    for p in sorted(d.glob("*.md")):
        if p.name.startswith("_"):
            continue
        fm, _ = _parse_frontmatter(p.read_text())
        fm.setdefault("slug", p.stem)
        out.append(fm)
    return out


def list_candidates() -> list[dict]:
    """Draft verdicts a scout pass wrote into _candidates/, awaiting review.

    These are the unreviewed end of the scout loop: ``spindle scout --apply-results``
    drops candidate blocks here. Each dict carries the frontmatter plus a
    ``_path`` so the caller can show or promote it.
    """
    d = _paths.candidates_dir()
    if not d.exists():
        return []
    out: list[dict] = []
    for p in sorted(d.glob("*.md")):
        fm, _ = _parse_frontmatter(p.read_text())
        fm.setdefault("slug", p.stem)
        fm["_path"] = str(p)
        out.append(fm)
    return out


def get(slug: str) -> tuple[dict, str] | None:
    p = _path_for(slug)
    if not p.exists():
        return None
    return _parse_frontmatter(p.read_text())


def write(slug: str, *, source: str, url: str = "", verdict: str = "tracking",
          status: str = "candidate", body: str = "") -> Path:
    today = date.today().isoformat()
    fm = {
        "slug": slug,
        "source": source,
        "url": url,
        "first_seen": today,
        "verdict": verdict,
        "status": status,
        "last_reviewed": today,
    }
    lines = ["---"]
    for k, v in fm.items():
        if v == "":
            continue
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    lines.append(body.strip() or f"# {slug}\n\n_(verdict body — fill in)_")
    p = _path_for(slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n")
    return p
