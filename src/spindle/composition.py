"""Compose-time coherence linter — the anti-pidgin guard.

A composition is the resolved set of skills a surface gets (the future channel
binding produces these). Blending sources risks a combination no single upstream
ever vetted — two skills claiming the same command, or a self-evolving agent that
has composed away its own guardrails. This linter is where coherence is enforced
(see ``plans/spindle-evolution/concept.md`` §5 / FC-4: coherence lives at the
composition layer, not by enlarging skills), and where FC-3's rule bites:
**a composition may not strip its foundation guardrails** (the system-scope
absolutes), self-evolving agents included.

Pure logic over a ``Composition`` value — it does not bind, fetch, or rewire the
distribution. ``lint`` returns a list of problems; empty means coherent. A
composition that doesn't pass should never reach a surface.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .doctrine import Doctrine

SELF_EVOLVING = "self_evolving"
DETERMINISTIC = "deterministic"
AUTONOMY_MODES = (SELF_EVOLVING, DETERMINISTIC)


@dataclass(frozen=True)
class ComposedSkill:
    name: str
    command: str          # slash command, e.g. "/clarify"
    scope: str            # system | cluster | repo
    source: str = ""      # channel / package it came from
    irreversible: bool = False  # deploy/delete/spend/external-comms → must be A4-gated
    source_dir: str = ""  # canonical on-disk skill dir; what materialize symlinks (or, post-render, the rendered dir)
    tier: str = ""        # P10 routing hint: judgment | execution | "" (unset). Advisory —
                          # spindle annotates which model tier a skill wants; the harness routes.
    chip: str = ""        # optional chip alias (touchpoint A). Advisory routing hint, mirroring
                          # `tier`: names a chip a chip-host *could* wire this skill to. Inert
                          # without a chip host — spindle never imports chip tooling; it only
                          # carries the string through resolve/render/materialize untouched.


@dataclass(frozen=True)
class Shadow:
    """A record that one skill overrode another for the same command slot.

    Cross-scope shadows are intended overrides (a repo's /review beating the
    system's) — informational. Same-scope shadows are accidental collisions (a
    repo in two clusters both claiming /review) — surfaced as lint problems.
    """

    command: str
    winner: str        # skill name that took the slot
    loser: str         # skill name that was shadowed
    winner_scope: str
    loser_scope: str
    same_scope: bool


@dataclass
class Composition:
    surface: str                                  # consuming repo / agent id
    autonomy_mode: str                            # self_evolving | deterministic
    skills: list[ComposedSkill] = field(default_factory=list)
    absolutes_in_force: list[str] = field(default_factory=list)  # doctrine absolute ids enforced
    shadows: list[Shadow] = field(default_factory=list)  # every override recorded (D3)


@dataclass(frozen=True)
class ChannelLayer:
    """One subscribed channel's contribution to a surface's composition."""

    scope: str                                    # system | cluster | repo
    skills: list[ComposedSkill] = field(default_factory=list)
    absolutes: list[str] = field(default_factory=list)  # absolute ids in force at this scope
    name: str = ""                                # channel name (for version tracking)
    version: str = ""                             # channel version (feeds the binding coordinate)


# Precedence is a POLICY, not baked in: the order from least- to most-specific.
# Default = more-specific-scope-wins for skill *slots*; absolutes always accumulate
# (they are non-overridable — enforced by lint). This default is flagged in the
# concept as an open question — pass `precedence=` to override.
DEFAULT_PRECEDENCE = ("system", "cluster", "repo")


def resolve(
    layers: list[ChannelLayer],
    *,
    surface: str,
    autonomy_mode: str,
    precedence: tuple[str, ...] = DEFAULT_PRECEDENCE,
) -> Composition:
    """Merge subscribed channel layers into one Composition.

    Skill *slots* are keyed by command (falling back to name): a more-specific
    layer's skill overrides a less-specific one claiming the same slot. Absolutes
    are unioned across all layers — they accumulate and are never dropped by
    precedence (FC-3: guardrails are non-negotiable; lint enforces it). The result
    still must pass ``lint`` before it reaches a surface.
    """
    rank = {scope: i for i, scope in enumerate(precedence)}
    # Least-specific first so most-specific writes last and wins the slot.
    ordered = sorted(layers, key=lambda layer: rank.get(layer.scope, -1))

    by_slot: dict[str, ComposedSkill] = {}
    shadows: list[Shadow] = []
    absolutes: set[str] = set()
    for layer in ordered:
        for s in layer.skills:
            slot = s.command or f"name:{s.name}"
            prior = by_slot.get(slot)
            if prior is not None and prior.name != s.name:
                # The later writer (more- or equal-specific) wins the slot; record
                # the override so nothing is silently swallowed (D3). same_scope
                # means an accidental collision (e.g. two clusters), not an override.
                shadows.append(Shadow(
                    command=s.command,
                    winner=s.name,
                    loser=prior.name,
                    winner_scope=s.scope,
                    loser_scope=prior.scope,
                    same_scope=(s.scope == prior.scope),
                ))
            by_slot[slot] = s
        absolutes.update(layer.absolutes)

    skills = sorted(by_slot.values(), key=lambda s: s.name)
    return Composition(
        surface=surface,
        autonomy_mode=autonomy_mode,
        skills=skills,
        absolutes_in_force=sorted(absolutes),
        shadows=sorted(shadows, key=lambda sh: (sh.command, sh.winner)),
    )


def resolve_and_lint(
    layers: list[ChannelLayer],
    doc: Doctrine,
    *,
    surface: str,
    autonomy_mode: str,
    precedence: tuple[str, ...] = DEFAULT_PRECEDENCE,
) -> tuple[Composition, list[str]]:
    """Resolve then lint — the compose-time gate in one call."""
    comp = resolve(layers, surface=surface, autonomy_mode=autonomy_mode, precedence=precedence)
    return comp, lint(comp, doc)


def lint(comp: Composition, doc: Doctrine) -> list[str]:
    """Return coherence problems; empty means the blend is coherent.

    Checks:
      1. autonomy_mode is from the controlled vocabulary;
      2. no two skills claim the same command (the clearest pidgin symptom);
      3. same-scope shadows — two equally-specific channels claimed one slot, an
         accidental collision (cross-scope shadows are intended overrides → info,
         carried on ``comp.shadows`` for display, not flagged here) (D3);
      4. no duplicate skill names;
      5. any irreversible-blast-radius skill is A4-gated (FC-2/FC-3).

    There is deliberately NO blanket "all system absolutes must be in force" check
    (dropped per eng-review D2): no current absolute is a genuine *composition*
    guardrail, so mandating them only over-constrains. Re-add a targeted check
    (with an ``applies_to`` axis on absolutes) when a real composition guardrail
    exists. The conditional irreversible→A4 check below is the one guardrail that
    earns its place: it fires only for genuinely dangerous skills.
    """
    problems: list[str] = []

    if comp.autonomy_mode not in AUTONOMY_MODES:
        problems.append(
            f"bad autonomy_mode {comp.autonomy_mode!r} (want one of {AUTONOMY_MODES})"
        )

    # 2. command collisions among the resolved skills (catches hand-built
    #    compositions; resolved ones are deduped, so same-slot clashes show up as
    #    same-scope shadows in check 3).
    by_command: dict[str, list[str]] = defaultdict(list)
    for s in comp.skills:
        if s.command:
            by_command[s.command].append(s.name)
    for command, owners in sorted(by_command.items()):
        if len(owners) > 1:
            problems.append(f"command {command!r} claimed by multiple skills: {', '.join(sorted(owners))}")

    # 3. same-scope shadows — accidental collisions resolve() had to break arbitrarily
    for sh in comp.shadows:
        if sh.same_scope:
            problems.append(
                f"command {sh.command!r} claimed by two {sh.winner_scope}-scope channels "
                f"({sh.winner} shadowed {sh.loser}) — same-scope collision, pick one"
            )

    # 4. duplicate names
    seen: set[str] = set()
    for s in comp.skills:
        if s.name in seen:
            problems.append(f"duplicate skill name {s.name!r}")
        seen.add(s.name)

    # 5. irreversible skills must be A4-gated (the one conditional guardrail)
    in_force = set(comp.absolutes_in_force)
    has_irreversible = any(s.irreversible for s in comp.skills)
    if has_irreversible and "A4" not in in_force:
        names = sorted(s.name for s in comp.skills if s.irreversible)
        problems.append(
            f"irreversible-blast-radius skill(s) {', '.join(names)} present but A4 "
            f"(guardrail veto) not in force — gate them (FC-2/FC-3)"
        )

    return problems
