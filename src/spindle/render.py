"""Per-harness dialect rendering + meaning-preservation verification.

A skill is authored once (canonical) and *rendered* into a harness's dialect
before it reaches that surface (eng-review D4/D7). Rendering produces NEW text, so
unlike selection it cannot be a symlink — rendered output is written to a
cache-keyed store and the composition's ``source_dir`` is pointed at it.

The load-bearing safety piece (eng-review #5/D7): the coherence linter inspects
Composition *metadata*, not rendered prose, so it cannot catch a render that
silently drops a guardrail clause (the A1–A4-strip risk by paraphrase). So every
render is **verified** here — guardrail clauses present in the source must survive
in the rendered output, or the bind fails closed via ``RenderError``.

The transform is injectable: identity for claude today, an LLM/rule transform per
harness later. The verification + store + cache key are the durable scaffolding
that makes turning on a real transform safe.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from . import paths
from .channels import Surface
from .composition import Composition

# A guardrail clause is a line asserting a hard rule. We key on the doctrine's own
# absolute markers (ALWAYS/NEVER) plus emphatic safety markers; these are the lines
# a dialect rewrite must never drop.
_GUARDRAIL_RE = re.compile(r"\b(ALWAYS|NEVER|MUST NOT|DO NOT)\b")

Transform = Callable[[str], str]


@dataclass(frozen=True)
class Profile:
    harness: str
    version: str
    transform: Transform


def identity_transform(text: str) -> str:
    return text


class RenderError(Exception):
    """Raised when a render drops a guardrail clause; carries the problem list."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def extract_guardrails(text: str) -> list[str]:
    """The guardrail clauses (ALWAYS/NEVER/DO NOT lines) a render must preserve."""
    return [ln.strip() for ln in text.splitlines() if _GUARDRAIL_RE.search(ln)]


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def verify_preserved(source: str, rendered: str) -> list[str]:
    """Guardrail clauses in *source* that are missing from *rendered* (normalized).

    Empty list means every guardrail survived. This is the meaning-preservation
    floor; an LLM-judge semantic check can layer on top, but clause-presence is the
    deterministic, testable guarantee.
    """
    rnorm = _normalize(rendered)
    return [g for g in extract_guardrails(source) if _normalize(g) not in rnorm]


def cache_key(doctrine_coordinate: str, profile: Profile, content: str,
              model_profile: Profile | None = None) -> str:
    """Stable key over (doctrine × harness-profile × model-profile × skill content) —
    the rendered-content store address. Any change to doctrine, either profile's
    version, the model axis, or the source skill invalidates the cache by producing a
    new key. ``model_profile`` is optional and absent from the key when None, so a
    surface with no model tuning keys identically to before the axis existed."""
    h = hashlib.sha256()
    parts = [doctrine_coordinate, f"{profile.harness}:{profile.version}"]
    if model_profile is not None:
        parts.append(f"model:{model_profile.harness}:{model_profile.version}")
    parts.append(content)
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:16]


def render_store_root() -> Path:
    return paths.spindle_home() / "rendered"


def render_skill(skill_dir: str | Path, profile: Profile, doctrine_coordinate: str,
                 *, model_profile: Profile | None = None,
                 store_root: Path | None = None) -> Path:
    """Render one skill's SKILL.md, verify guardrails, write to the cache-keyed store,
    and return the rendered skill dir.

    Two render axes compose here: the ``profile`` (harness *dialect* — phrasing) runs
    first, then the optional ``model_profile`` (model *density* — how much scaffolding
    the target model needs; subtractive for frontier, additive for weaker). The order
    is dialect-then-density: phrase for the harness, then tune the amount for the
    model. Verification runs over the *final* text against the original source, so a
    guardrail dropped by either axis fails the bind closed — including a subtractive
    model transform that strips a fence containing an ALWAYS/NEVER line.

    Raises RenderError if a guardrail clause didn't survive. Other files in the skill
    dir are copied verbatim. Cached renders are reused (idempotent).
    """
    store_root = store_root or render_store_root()
    skill_dir = Path(skill_dir)
    source = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    rendered = profile.transform(source)
    if model_profile is not None:
        rendered = model_profile.transform(rendered)

    missing = verify_preserved(source, rendered)
    if missing:
        raise RenderError(
            [f"{skill_dir.name}: render dropped guardrail clause {m!r}" for m in missing]
        )

    out = (store_root
           / cache_key(doctrine_coordinate, profile, source, model_profile)
           / skill_dir.name)
    if not (out / "SKILL.md").exists():
        out.mkdir(parents=True, exist_ok=True)
        for f in skill_dir.iterdir():
            if f.is_file() and f.name != "SKILL.md":
                shutil.copy2(f, out / f.name)
        (out / "SKILL.md").write_text(rendered, encoding="utf-8")
    return out


_IDENTITY_PROFILE = Profile(harness="identity", version="0", transform=identity_transform)


def make_render_fn(profiles: dict[str, Profile], doctrine_coordinate: str,
                   *, model_profiles: dict[str, Profile] | None = None,
                   store_root: Path | None = None):
    """Build a binder RenderFn from harness ``profiles`` and optional ``model_profiles``.

    A surface picks its harness profile by ``surface.harness`` and its model profile
    by ``surface.model`` (the rendering-density axis). A skill is rendered when
    *either* axis applies; when neither does it passes through verbatim
    (selection-only). When only the model axis applies, the harness step is identity,
    so model tuning works on any harness. Any guardrail-drop across the composition
    raises RenderError, so the binder fails closed.
    """
    model_profiles = model_profiles or {}

    def render(comp: Composition, surface: Surface) -> Composition:
        hprofile = profiles.get(surface.harness)
        mprofile = model_profiles.get(surface.model) if surface.model else None
        if hprofile is None and mprofile is None:
            return comp
        hprofile = hprofile or _IDENTITY_PROFILE
        new_skills = []
        problems: list[str] = []
        for s in comp.skills:
            if not s.source_dir:
                new_skills.append(s)
                continue
            try:
                out = render_skill(s.source_dir, hprofile, doctrine_coordinate,
                                   model_profile=mprofile, store_root=store_root)
                new_skills.append(replace(s, source_dir=str(out)))
            except RenderError as e:
                problems.extend(e.problems)
                new_skills.append(s)
        if problems:
            raise RenderError(problems)
        comp.skills = new_skills
        return comp

    return render
