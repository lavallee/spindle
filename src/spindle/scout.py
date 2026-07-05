"""Materialize scout prompts and emit runner commands."""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path

from . import active as active_mod
from . import peers as peers_mod

DEFAULT_COMMAND_TEMPLATE = (
    "spindle-runner --prompt-file {prompt_file} --cwd {cwd} "
    "--result-file {result_file} --notify {notify} "
    "--tag scout=spindle --tag peer={peer} --tag url={url} --tag last_seen={last_seen}"
)


def _quote_map(**values: str) -> dict[str, str]:
    return {k: shlex.quote(str(v)) for k, v in values.items()}


def emit_scout_jobs(
    slug: str | None = None,
    write_candidates: bool = False,
    *,
    command_template: str | None = None,
) -> list[str]:
    """Return runner command strings for each peer (or a filtered subset).

    Reads peers via ``peers.list_peers`` and locates ``scout/scout-pass.md`` under
    the active distribution source. ``command_template`` defaults to
    ``SPINDLE_SCOUT_COMMAND`` or an illustrative ``spindle-runner`` command.

    Template fields are shell-quoted: ``prompt_file``, ``cwd``, ``result_file``,
    ``notify``, ``peer``, ``url``, and ``last_seen``.
    """
    scout_d = active_mod.source_dir() / "scout"
    pass_prompt = scout_d / "scout-pass.md"
    if not pass_prompt.exists():
        raise FileNotFoundError(f"missing {pass_prompt}")

    targets = peers_mod.list_peers()
    if slug is not None:
        targets = [p for p in targets if p.get("slug") == slug]
        if not targets:
            raise ValueError(f"no peer {slug!r}")

    spindle_exe = shutil.which("spindle") or str(Path(sys.argv[0]).resolve())
    template = command_template or os.environ.get("SPINDLE_SCOUT_COMMAND") or DEFAULT_COMMAND_TEMPLATE

    commands: list[str] = []
    for peer in targets:
        peer_slug = peer.get("slug", "?")
        url = peer.get("url", "?")
        last = peer.get("last_seen", "?")
        results_file = scout_d / "results" / f"{peer_slug}.json"

        # scout-pass.md is a template. Materialize a per-peer prompt so a generic
        # runner does not need to understand Spindle's peer registry.
        materialized_d = scout_d / "prompts"
        materialized_d.mkdir(exist_ok=True)
        materialized = materialized_d / f"{peer_slug}.md"
        header = (
            "Pass parameters (materialized by `spindle scout` at emit time — "
            "scout ONLY this peer):\n\n"
            f"- peer: {peer_slug}\n"
            f"- url: {url}\n"
            f"- last_seen: {last}\n\n---\n\n"
        )
        materialized.write_text(
            header + pass_prompt.read_text().replace("$PEER_NAME", peer_slug)
        )

        if write_candidates:
            notify = f"exec:{spindle_exe} scout --apply-results"
        else:
            notify = f"file:{results_file}"
        commands.append(template.format(**_quote_map(
            prompt_file=str(materialized),
            cwd=str(scout_d),
            result_file=str(results_file),
            notify=notify,
            peer=peer_slug,
            url=url,
            last_seen=last,
        )))
    return commands
