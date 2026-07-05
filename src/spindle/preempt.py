"""Preempt mechanism — bias Claude toward spindle skills via CLAUDE.md.

Adds a fenced block to ~/.claude/CLAUDE.md (creating the file if absent)
that tells Claude to default to spindle skills for planning. The block is
delimited so we can remove it cleanly with `spindle unpreempt`.

The block is opt-in. Other planning systems (gstack, Superpowers, etc)
remain installed and reachable by name — they just don't get
auto-activated for generic planning phrasing.
"""

from __future__ import annotations

from pathlib import Path

from . import active
from .distributions import read_distribution_metadata
from .ledger import log_event
from .paths import claude_md_path


_BEGIN = "<!-- spindle:preempt:begin -->"
_END = "<!-- spindle:preempt:end -->"


def _load_snippet() -> str:
    """Load snippet body from the active distribution's preempt file.

    BEGIN/END delimiters are added here; the distribution file contains only
    the body content.
    """
    name = active.active_distribution()
    if name == active.ANONYMOUS:
        raise RuntimeError(
            "cannot load preempt snippet: active distribution is anonymous "
            "(SPINDLE_ACTIVE_DIST_DIR is set but provides no metadata)"
        )

    meta = read_distribution_metadata(name)
    if meta is None:
        raise RuntimeError(
            f"cannot load preempt snippet: distribution {name!r} not found"
        )
    if meta.preempt_snippet is None:
        raise RuntimeError(
            f"cannot load preempt snippet: distribution {name!r} has no "
            "`preempt_snippet` configured in pyproject.toml"
        )

    content = meta.preempt_snippet.read_text(encoding="utf-8")
    return f"{_BEGIN}\n{content.rstrip()}\n{_END}\n"


def is_preempted() -> bool:
    p = claude_md_path()
    if not p.exists():
        return False
    text = p.read_text()
    return _BEGIN in text and _END in text


def preempt() -> str:
    """Add the preempt block. Idempotent. Returns 'added' or 'already-present'."""
    p = claude_md_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    snippet = _load_snippet()
    if not p.exists():
        p.write_text(snippet)
        log_event("preempt", action="add")
        return "added"
    text = p.read_text()
    if _BEGIN in text and _END in text:
        return "already-present"
    if not text.endswith("\n"):
        text += "\n"
    text += "\n" + snippet
    p.write_text(text)
    log_event("preempt", action="add")
    return "added"


def unpreempt() -> str:
    """Remove the preempt block. Returns 'removed' or 'not-present'."""
    p = claude_md_path()
    if not p.exists():
        return "not-present"
    text = p.read_text()
    if _BEGIN not in text or _END not in text:
        return "not-present"
    start = text.index(_BEGIN)
    end = text.index(_END) + len(_END)
    # Eat one trailing newline so we don't leave a blank gap.
    if end < len(text) and text[end] == "\n":
        end += 1
    new = text[:start] + text[end:]
    # Trim trailing blank lines we may have created
    new = new.rstrip() + "\n" if new.strip() else ""
    if new:
        p.write_text(new)
    else:
        p.unlink()
    log_event("preempt", action="remove")
    return "removed"
