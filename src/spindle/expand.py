"""Optional query expansion for skill search.

A commission says what to deliver; a skill's description says what kind of work
it is for. The two often share no words, so text search over the commission
alone misses skills that plainly fit. An *expander* closes that gap: a command
the house names (``[sourcing] expand = "bin/..."`` in ``house.toml``) that reads
the task on stdin and prints a few short search phrases, one per line, naming
the kinds of skill that would help. It is usually a small model call.

Spindle does not care how the command works and never fails because of it: a
missing command, a non-zero exit, a timeout, or empty output all mean "no
expansion".
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable

TIMEOUT_S = 12
MAX_PHRASES = 6
MAX_TASK_CHARS = 6000
_LEAD = re.compile(r"^\s*(?:[-*\u2022]+|\d+[.)])\s*")
Runner = Callable[..., subprocess.CompletedProcess]


def parse(output: str) -> list[str]:
    phrases: list[str] = []
    for raw in output.splitlines():
        line = _LEAD.sub("", raw).strip().strip("\"'`").strip()
        if 2 < len(line) <= 80 and line.lower() not in {p.lower() for p in phrases}:
            phrases.append(line)
    return phrases[:MAX_PHRASES]


def expand(
    task: str, command: Path | None, *, run: Runner = subprocess.run
) -> tuple[list[str], str]:
    """Return ``(phrases, note)``; ``note`` says why there are none."""
    if command is None:
        return [], ""
    try:
        done = run(
            [str(command)], input=task[:MAX_TASK_CHARS], capture_output=True,
            text=True, timeout=TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"expander unavailable: {type(exc).__name__}"
    if done.returncode != 0:
        return [], f"expander exited {done.returncode}"
    phrases = parse(done.stdout)
    return phrases, "" if phrases else "expander returned nothing usable"
