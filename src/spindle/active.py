"""Resolve which installed distribution is currently "active".

Many spindle commands need a single answer to "where do peers, verdicts, and
scout-pass.md live for this invocation?". That answer comes from the
*active distribution*. This module is the one place that question gets
answered.

Resolution order (highest precedence first):

1. ``SPINDLE_ACTIVE_DIST_DIR`` env var — direct path to a distribution
   source_dir. Bypasses the installed-distributions registry entirely;
   ``active_distribution()`` reports the synthetic name ``"anonymous"``
   and ``source_dir()`` returns the env path verbatim. Mainly used by
   tests and by ad-hoc work against an uninstalled distribution.
2. ``SPINDLE_ACTIVE_DIST_NAME`` env var — distribution name; must be
   installed.
3. ``$SPINDLE_HOME/active`` pointer file (written by ``set_active``).
4. Only-installed fallback — if exactly one distribution is installed,
   use it.
5. Otherwise raise :class:`ActiveDistributionError`.
"""

from __future__ import annotations

import os
from pathlib import Path

from .distributions import list_installed_distributions, read_distribution_metadata
from .paths import spindle_home

ANONYMOUS = "anonymous"


class ActiveDistributionError(RuntimeError):
    """No active distribution could be resolved."""


def _active_pointer_file() -> Path:
    return spindle_home() / "active"


def _active_dist_dir_env() -> str | None:
    return os.environ.get("SPINDLE_ACTIVE_DIST_DIR")


def _active_dist_name_env() -> str | None:
    return os.environ.get("SPINDLE_ACTIVE_DIST_NAME")


def _read_pointer() -> str | None:
    p = _active_pointer_file()
    if not p.exists():
        return None
    name = p.read_text(encoding="utf-8").strip()
    return name or None


def active_distribution() -> str:
    """Return the name of the currently active distribution.

    See module docstring for full resolution order. Raises
    :class:`ActiveDistributionError` if nothing resolves.
    """
    if _active_dist_dir_env():
        return ANONYMOUS

    name = _active_dist_name_env()
    if name:
        if read_distribution_metadata(name) is None:
            raise ActiveDistributionError(
                f"SPINDLE_ACTIVE_DIST_NAME={name!r} is not an installed distribution"
            )
        return name

    pointer = _read_pointer()
    if pointer:
        if read_distribution_metadata(pointer) is None:
            raise ActiveDistributionError(
                f"active pointer at {_active_pointer_file()} names {pointer!r}, "
                "which is not an installed distribution"
            )
        return pointer

    installed = list_installed_distributions()
    if len(installed) == 1:
        return installed[0].name
    if not installed:
        raise ActiveDistributionError(
            "no spindle distributions are installed; install one or set "
            "SPINDLE_ACTIVE_DIST_DIR / SPINDLE_ACTIVE_DIST_NAME"
        )
    names = ", ".join(d.name for d in installed)
    raise ActiveDistributionError(
        f"multiple distributions installed ({names}); pick one with "
        "`spindle dist activate <name>`, SPINDLE_ACTIVE_DIST_NAME, or "
        "SPINDLE_ACTIVE_DIST_DIR"
    )


def source_dir() -> Path:
    """Absolute source_dir of the active distribution.

    If ``SPINDLE_ACTIVE_DIST_DIR`` is set, returns that path verbatim.
    Otherwise resolves the active distribution and returns its source_dir.
    """
    raw = _active_dist_dir_env()
    if raw:
        return Path(raw)

    name = active_distribution()
    meta = read_distribution_metadata(name)
    if meta is None:
        raise ActiveDistributionError(
            f"active distribution {name!r} resolved but its metadata could not be read"
        )
    return meta.source_dir


def set_active(name: str) -> None:
    """Persist *name* as the active distribution in the state pointer."""
    if read_distribution_metadata(name) is None:
        raise ActiveDistributionError(
            f"cannot activate {name!r}: not an installed distribution"
        )
    p = _active_pointer_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(name + "\n", encoding="utf-8")
