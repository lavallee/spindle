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
from .lifecycle import (
    ExpectedProjection,
    SurfaceLock,
    content_id,
    digest_path,
    read_surface_lock,
    surface_id,
    write_surface_lock,
)

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
        return BindResult(
            surface=surface.name,
            ok=False,
            problems=[f"render: {p}" for p in e.problems],
            composition=comp,
        )

    problems = composition_mod.lint(comp, doctrine)
    if problems and not force:
        # Fail closed: incoherent blend never reaches the surface.
        return BindResult(
            surface=surface.name, ok=False, problems=problems, composition=comp
        )

    prev = binding_mod.current_binding(surface.name)
    previous_names = set(prev.skills) if prev else set()
    channel_versions = {
        layer.name or layer.scope: layer.version for layer in layers if layer.version
    }
    planned_coordinate = binding_mod.compute_coordinate(
        comp,
        doctrine_coordinate=doctrine.coordinate(),
        channel_versions=channel_versions,
    )
    sid = surface_id(repo_path, surface.harness)
    current_lock = read_surface_lock(sid)
    leased = tuple(
        projection
        for projection in (current_lock.projections if current_lock else ())
        if projection.authority.startswith("lease:")
    )
    leased_names = {projection.skill for projection in leased}
    colliding_leases = sorted(
        skill.name for skill in comp.skills if skill.name in leased_names
    )
    if colliding_leases:
        return BindResult(
            surface=surface.name,
            ok=False,
            problems=[
                "active lease owns desired skill name: " + ", ".join(colliding_leases)
            ],
            composition=comp,
        )
    actions = materialize_mod.materialize(
        comp,
        repo_path,
        surface.harness,
        previous=previous_names,
        dry_run=dry_run,
        creation_receipt_id=f"binding:{planned_coordinate}",
        package_digests={
            skill.name: skill.package_digest or digest_path(skill.source_dir)
            for skill in comp.skills
            if skill.source_dir
        },
    )

    materialization_problems = [
        f"materialize: {name} {action}"
        for name, action in actions
        if action.startswith("skipped:")
    ]
    if materialization_problems:
        return BindResult(
            surface=surface.name,
            ok=False,
            problems=materialization_problems,
            actions=actions,
            composition=comp,
        )

    coordinate: str | None = None
    if not dry_run:
        target = materialize_mod.target_dir(repo_path, surface.harness)
        lock = SurfaceLock(
            surface_id=sid,
            surface_name=surface.name,
            repo_path=str(Path(repo_path).resolve()),
            harness=surface.harness,
            binding_coordinate=planned_coordinate,
            projections=(
                *tuple(
                    ExpectedProjection(
                        skill=skill.name,
                        projection_path=str((target / skill.name).absolute()),
                        source_path=str(Path(skill.source_dir).resolve()),
                        source_digest=digest_path(skill.source_dir),
                        package_digest=skill.package_digest
                        or digest_path(skill.source_dir),
                    )
                    for skill in comp.skills
                    if skill.source_dir
                ),
                *leased,
            ),
            adoption_ids=current_lock.adoption_ids if current_lock else (),
            lease_ids=current_lock.lease_ids if current_lock else (),
            conflict_decisions=(
                current_lock.conflict_decisions if current_lock else ()
            ),
        )
        write_surface_lock(lock)
        rec = binding_mod.record_binding(
            comp,
            doctrine_coordinate=doctrine.coordinate(),
            channel_versions=channel_versions,
            repo_path=str(Path(repo_path).resolve()),
            harness=surface.harness,
            surface_id=sid,
            surface_lock_id=lock.lock_id,
        )
        coordinate = rec.coordinate

    return BindResult(
        surface=surface.name,
        ok=True,
        problems=problems,
        actions=actions,
        coordinate=coordinate,
        composition=comp,
    )


def unbind(
    surface_name: str, repo_path: str | Path, harness: str, *, dry_run: bool = False
) -> list[tuple[str, str]]:
    """Remove a surface's materialized skills (the current binding's owned set).

    Materializes an empty composition with ``previous`` = the current binding's
    skill names, so only spindle-owned symlinks are removed — hand-added skills are
    safe (same guarantee as ``materialize``). Returns the removal actions.
    """
    prev = binding_mod.current_binding(surface_name)
    previous_names = set(prev.skills) if prev else set()
    empty = Composition(surface=surface_name, autonomy_mode="deterministic")
    actions = materialize_mod.materialize(
        empty, repo_path, harness, previous=previous_names, dry_run=dry_run
    )
    if not dry_run and not any(action.startswith("skipped:") for _, action in actions):
        sid = surface_id(repo_path, harness)
        current_lock = read_surface_lock(sid)
        retained = tuple(
            projection
            for projection in (current_lock.projections if current_lock else ())
            if projection.authority.startswith("lease:")
        )
        write_surface_lock(
            SurfaceLock(
                surface_id=sid,
                surface_name=surface_name,
                repo_path=str(Path(repo_path).resolve()),
                harness=harness,
                binding_coordinate=f"unbind:{content_id({'surface_id': sid, 'skills': []})}",
                projections=retained,
                adoption_ids=current_lock.adoption_ids if current_lock else (),
                lease_ids=current_lock.lease_ids if current_lock else (),
                conflict_decisions=(
                    current_lock.conflict_decisions if current_lock else ()
                ),
            )
        )
    return actions
