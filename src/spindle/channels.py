"""Channel selection — which (scope × harness) channels a surface subscribes to.

A *surface* is anything that consumes skills: a repo working under a harness, an
agent with an autonomy mode. It subscribes to a channel at each scope — `system`,
each `cluster` it belongs to, and its own `repo` channel — and every channel is
keyed by harness (a claude surface gets `system/claude`, not `system/codex`).
This is the harness-as-*selection* half of the (scope × harness × autonomy) model
(eng-review D4); harness-as-*rendering* happens later in the render stage.

Selection (the ordered subscription list) is decided and pure; *loading* a channel
into a `ChannelLayer` is delegated to an injectable provider, so storage layout
stays a separate decision (paired with the materialize target path).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from . import active as active_mod
from .composition import ChannelLayer, ComposedSkill

# A provider loads one channel into a layer, or None if the surface's harness has
# no channel at that (scope, name). Signature: (scope, name, harness) -> layer?.
ChannelProvider = Callable[[str, str, str], Optional[ChannelLayer]]


def _frontmatter_chip(src: str | Path) -> str:
    """Read the optional ``chip:`` alias from a skill dir's SKILL.md frontmatter.

    Advisory-only; missing file or key returns "". Kept string-level here so the
    channel layer never imports chip tooling."""
    md = Path(src) / "SKILL.md"
    try:
        text = md.read_text(encoding="utf-8")
    except OSError:
        return ""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    if end < 0:
        return ""
    for line in text[3:end].splitlines():
        if line.startswith("chip:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return ""


@dataclass(frozen=True)
class Surface:
    """A skill consumer. ``clusters`` are app-class keys from spindle.appclass."""

    name: str                       # repo / agent id, e.g. "barn-owl"
    harness: str                    # claude | codex | pi | …
    autonomy_mode: str              # self_evolving | deterministic
    clusters: tuple[str, ...] = ()  # app-class keys this surface belongs to
    model: str | None = None        # model/tier key the skills are tuned to render for
                                    # (frontier | opus-4.8 | …); None = no model tuning.
                                    # Selection is per (scope × harness); model is a
                                    # *rendering* axis (density), applied at the render
                                    # stage like harness dialect — not a channel key.


def subscribed_channels(surface: Surface) -> list[tuple[str, str]]:
    """The ordered (scope, name) channels a surface subscribes to.

    Order is least- to most-specific so it feeds ``resolve()`` directly: system
    first, then each cluster (in declared order), then the repo's own channel.
    Harness is applied by the provider, not encoded here.
    """
    out: list[tuple[str, str]] = [("system", "system")]
    out.extend(("cluster", c) for c in surface.clusters)
    out.append(("repo", surface.name))
    return out


def select_layers(surface: Surface, provider: ChannelProvider) -> list[ChannelLayer]:
    """Resolve a surface's subscriptions into ChannelLayers via ``provider``.

    Channels the provider can't supply for this harness are skipped (a surface
    legitimately may have no repo-scoped channel yet, or no cluster channel for
    its harness). The returned layers are ready to hand to ``composition.resolve``.
    """
    layers: list[ChannelLayer] = []
    for scope, name in subscribed_channels(surface):
        layer = provider(scope, name, surface.harness)
        if layer is not None:
            layers.append(layer)
    return layers


# ---- filesystem provider ------------------------------------------------

def channel_manifest_path(source_dir: Path, scope: str, name: str, harness: str) -> Path:
    """Where a channel's manifest lives:
    ``<source_dir>/channels/<scope>/<name>/<harness>/channel.toml``."""
    return Path(source_dir) / "channels" / scope / name / harness / "channel.toml"


def fs_provider(skill_index: dict[str, str | Path], *,
                source_dir: Path | None = None) -> ChannelProvider:
    """A ChannelProvider backed by on-disk channel manifests.

    A ``channel.toml`` declares ``version``, ``absolutes`` (ids in force at that
    scope), ``skills`` (skill names), an optional ``tiers`` map (skill name → P10
    routing hint, ``judgment`` | ``execution``), and an optional ``chips`` map
    (skill name → chip alias, touchpoint A). ``skill_index`` maps a skill name to
    its canonical source dir (built once from installed skills via
    ``skills.discover_skills``); names absent from the index are skipped. The
    command is conventionally ``/<name>``.

    The chip alias falls back to the skill's own ``chip:`` frontmatter key when
    the manifest does not name one — either source is purely advisory and inert
    without a chip host.

    ``source_dir`` defaults to the active distribution's source dir.
    """
    base = Path(source_dir) if source_dir is not None else None

    def provider(scope: str, name: str, harness: str) -> Optional[ChannelLayer]:
        root = base if base is not None else active_mod.source_dir()
        manifest = channel_manifest_path(root, scope, name, harness)
        if not manifest.exists():
            return None
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        tiers = data.get("tiers", {}) or {}
        chips = data.get("chips", {}) or {}
        skills: list[ComposedSkill] = []
        for sname in data.get("skills", []):
            src = skill_index.get(sname)
            if src is None:
                continue
            chip = str(chips.get(sname, "")) or _frontmatter_chip(src)
            skills.append(ComposedSkill(
                name=sname, command=f"/{sname}", scope=scope, source_dir=str(src),
                tier=str(tiers.get(sname, "")), chip=chip,
            ))
        return ChannelLayer(
            scope=scope,
            name=f"{scope}:{name}",
            version=str(data.get("version", "")),
            skills=skills,
            absolutes=[str(a) for a in data.get("absolutes", [])],
        )

    return provider
