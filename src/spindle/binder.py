"""The binder — one surface, end to end: select → resolve → render → lint →
materialize → record.

This is the orchestrator that ties the channel/composition/materialize/binding
pieces into a single per-surface bind. It deliberately does NOT touch ``active``
or ``distributions`` (eng-review D6: those are orthogonal — the global
one-active-distribution flow stays untouched). The render step is an injectable
hook defaulting to identity; the real per-harness dialect renderer (with
meaning-preservation verification, eng-review D7) plugs in here later.

A bind fails closed: if ``lint`` finds problems, nothing is materialized unless
``force`` is set, so an incoherent blend never reaches a surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import binding as binding_mod
from . import channels as channels_mod
from . import composition as composition_mod
from . import materialize as materialize_mod
from . import render as render_mod
from .channels import ChannelProvider, Surface
from .composition import Composition
from .doctrine import Doctrine

# A render step maps a resolved composition to a (possibly rewritten) one for the
# surface's harness. Identity by default; the real renderer rewrites skill content
# per harness profile and points source_dir at the rendered output.
RenderFn = Callable[[Composition, Surface], Composition]


def identity_render(comp: Composition, surface: Surface) -> Composition:
    """No-op render: skills are materialized verbatim from their canonical dirs."""
    return comp


@dataclass
class BindResult:
    surface: str
    ok: bool
    problems: list[str] = field(default_factory=list)
    actions: list[tuple[str, str]] = field(default_factory=list)
    coordinate: str | None = None
    composition: Composition | None = None


def bind(
    surface: Surface,
    repo_path: str | Path,
    provider: ChannelProvider,
    doctrine: Doctrine,
    *,
    render: RenderFn = identity_render,
    force: bool = False,
    dry_run: bool = False,
) -> BindResult:
    """Compose and materialize a surface's skills. See module docstring for flow."""
    layers = channels_mod.select_layers(surface, provider)
    comp = composition_mod.resolve(
        layers, surface=surface.name, autonomy_mode=surface.autonomy_mode
    )
    try:
        comp = render(comp, surface)
    except render_mod.RenderError as e:
        # A render that dropped a guardrail clause fails closed — never materialize
        # silently-corrupted skills (eng-review D7/#5).
        return BindResult(surface=surface.name, ok=False,
                          problems=[f"render: {p}" for p in e.problems], composition=comp)

    problems = composition_mod.lint(comp, doctrine)
    if problems and not force:
        # Fail closed: incoherent blend never reaches the surface.
        return BindResult(surface=surface.name, ok=False, problems=problems,
                          composition=comp)

    prev = binding_mod.current_binding(surface.name)
    previous_names = set(prev.skills) if prev else set()
    actions = materialize_mod.materialize(
        comp, repo_path, surface.harness, previous=previous_names, dry_run=dry_run
    )

    coordinate = None
    if not dry_run:
        channel_versions = {
            layer.name or layer.scope: layer.version
            for layer in layers if layer.version
        }
        rec = binding_mod.record_binding(
            comp,
            doctrine_coordinate=doctrine.coordinate(),
            channel_versions=channel_versions,
        )
        coordinate = rec.coordinate

    return BindResult(surface=surface.name, ok=True, problems=problems,
                      actions=actions, coordinate=coordinate, composition=comp)


def unbind(surface_name: str, repo_path: str | Path, harness: str,
           *, dry_run: bool = False) -> list[tuple[str, str]]:
    """Remove a surface's materialized skills (the current binding's owned set).

    Materializes an empty composition with ``previous`` = the current binding's
    skill names, so only spindle-owned symlinks are removed — hand-added skills are
    safe (same guarantee as ``materialize``). Returns the removal actions.
    """
    prev = binding_mod.current_binding(surface_name)
    previous_names = set(prev.skills) if prev else set()
    empty = Composition(surface=surface_name, autonomy_mode="deterministic")
    return materialize_mod.materialize(
        empty, repo_path, harness, previous=previous_names, dry_run=dry_run
    )
