"""Scout utilities — extract candidate verdicts from a scout-pass report.

``spindle scout --write-candidates`` emits runner commands whose notify callback
can call ``spindle scout --apply-results <file>``. That callback parses the
runner report and writes candidate verdict blocks into the local candidates queue
for human review.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from spindle import paths as _paths


_VERDICT_BLOCK_RE = re.compile(
    r"```markdown\s*\n(---\s*\nslug:.*?```)",
    re.DOTALL,
)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _slug_from_frontmatter(block: str) -> str | None:
    m = _FRONTMATTER_RE.match(block)
    if not m:
        return None
    for line in m.group(1).splitlines():
        if line.strip().startswith("slug:"):
            return line.partition(":")[2].strip().strip("\"'")
    return None


def extract_verdicts(report: str) -> list[tuple[str, str]]:
    """Parse candidate verdict blocks from a scout-pass LLM report.

    Accepts blocks fenced as ```markdown ... ``` whose first content line
    starts with ``---`` frontmatter containing a ``slug:`` field.

    Returns a list of (slug, markdown_content) pairs.
    """
    results: list[tuple[str, str]] = []
    # Match ```markdown\n---\nslug: ... ``` blocks
    for m in re.finditer(
        r"```markdown\s*\n(---\s*\n.*?)```",
        report,
        re.DOTALL,
    ):
        block = m.group(1).rstrip()
        slug = _slug_from_frontmatter(block)
        if slug:
            results.append((slug, block))
    return results


def write_candidate(
    slug: str,
    content: str,
    dest_dir: Path | None = None,
) -> Path:
    """Write a candidate verdict markdown file; return the path written."""
    d = dest_dir if dest_dir is not None else _paths.candidates_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{slug}.md"
    p.write_text(content.rstrip() + "\n", encoding="utf-8")
    return p


def apply_results(result_file: Path, dest_dir: Path | None = None) -> list[Path]:
    """Read a runner result JSON (or plain markdown) and write candidate verdicts.

    A notify callback can write a JSON file with shape::

        {"output": "<LLM report text>", ...}

    If the file is plain markdown (no top-level JSON object) we treat the
    whole content as the report.
    """
    raw = result_file.read_text(encoding="utf-8")
    try:
        obj = json.loads(raw)
        report = obj.get("output") or obj.get("result") or raw
    except (json.JSONDecodeError, TypeError):
        report = raw

    written: list[Path] = []
    for slug, content in extract_verdicts(report):
        p = write_candidate(slug, content, dest_dir=dest_dir)
        written.append(p)
    return written
