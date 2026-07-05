"""Per-harness dialect profiles — load + transform registry.

A profile turns the canonical (claude-reference) skill text into a harness's
dialect (eng-review D4). Profiles are data-driven and versioned, loaded from
``<source_dir>/profiles/<harness>/profile.toml`` so the profile *version* feeds
the render cache key (a profile bump re-renders). The actual transform is one of:

  - ``identity`` — verbatim (claude is the reference dialect; the concept's
    "start optimistic, one source" default);
  - ``terse``   — deterministic whitespace collapse (safe: never drops content,
    so guardrails always survive verification);
  - ``llm``     — an LLM rewrites into the harness dialect (real dialect work),
    built only when an ``llm_client`` is supplied.

Every transform's output is still verified by ``render.verify_preserved`` — a
profile that drops a guardrail fails the bind closed, so even an LLM rewrite can't
silently strip a safety clause.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Callable

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from . import active as active_mod
from .render import Profile, Transform, identity_transform

LLMClient = Callable[[str], str]  # prompt -> completion


def terse_transform(text: str) -> str:
    """Collapse runs of blank lines + trim trailing whitespace. Content-preserving
    by construction (it only removes blank lines and trailing spaces), so every
    guardrail clause survives verification."""
    out: list[str] = []
    blank = False
    for raw in text.splitlines():
        ln = raw.rstrip()
        if ln == "":
            if blank:
                continue
            blank = True
        else:
            blank = False
        out.append(ln)
    return "\n".join(out).strip() + "\n"


BUILTIN_TRANSFORMS: dict[str, Transform] = {
    "identity": identity_transform,
    "terse": terse_transform,
}

# A scaffold fence wraps optional teaching material a *weaker* model needs but a
# frontier model reads faster without — worked examples, restated context, redundant
# step spelling. Authors mark it explicitly:
#
#   <!-- scaffold:examples -->
#   ...worked example a smaller model benefits from...
#   <!-- /scaffold -->
#
# A subtractive model profile (`trim`) removes these blocks; the default (no model
# profile, or an `identity` one) keeps them. Guardrails (ALWAYS/NEVER/DO NOT) must
# never live inside a fence — and if one does, ``render.verify_preserved`` catches it
# and fails the bind closed, so the safety floor holds regardless of author error.
_SCAFFOLD_RE = re.compile(
    r"[ \t]*<!--\s*scaffold\b[^>]*-->.*?<!--\s*/scaffold\s*-->[ \t]*\n?",
    re.DOTALL | re.IGNORECASE,
)


def trim_scaffold(text: str) -> str:
    """Subtractive density transform: strip ``<!-- scaffold --> … <!-- /scaffold -->``
    blocks (the optimize-*out* half of model tuning). Deterministic; collapses the
    blank-line runs a removed block can leave behind. Never touches text outside a
    fence, so guardrails outside fences survive by construction."""
    stripped = _SCAFFOLD_RE.sub("", text)
    return terse_transform(stripped)


# Model-density transforms: how *much* scaffolding a target model needs. `identity`
# keeps everything (the spelled-out baseline weaker models want); `trim` is
# subtractive (frontier). `llm` is the evidence-promoted density rewrite.
MODEL_TRANSFORMS: dict[str, Transform] = {
    "identity": identity_transform,
    "trim": trim_scaffold,
}


def llm_transform(client: LLMClient, style: str) -> Transform:
    """A transform that asks an LLM to rewrite into a harness dialect.

    The instruction (stable per profile) goes in the ``system`` prefix so it's
    cached across every skill in a render pass; only the variable skill text is the
    user message. The prompt pins meaning-preservation, but it's *belt and
    suspenders*: ``render.verify_preserved`` independently checks the output, so a
    model that ignores the instruction still fails the bind closed.
    """
    instruction = (
        f"Rewrite the agent-skill instructions the user sends in {style} dialect. "
        "Preserve every line containing ALWAYS, NEVER, or DO NOT verbatim. Keep all "
        "structure, steps, and meaning; change only phrasing and framing for the "
        "target harness. Return only the rewritten markdown."
    )

    def transform(text: str) -> str:
        return client(text, system=instruction)

    return transform


def profiles_dir(source_dir: Path | None = None) -> Path:
    root = Path(source_dir) if source_dir is not None else active_mod.source_dir()
    return root / "profiles"


def load_profiles(source_dir: Path | None = None, *,
                  llm_client: LLMClient | None = None) -> dict[str, Profile]:
    """Load ``<source_dir>/profiles/<harness>/profile.toml`` into harness → Profile.

    A profile.toml has ``version``, ``transform`` (identity|terse|llm), and
    ``style`` (for llm). Harnesses with no profile are simply absent — the render
    layer passes those through verbatim. An ``llm`` profile is skipped when no
    ``llm_client`` is provided (so offline binds don't fail on a missing model).
    """
    d = profiles_dir(source_dir)
    out: dict[str, Profile] = {}
    if not d.exists():
        return out
    for harness_dir in sorted(d.iterdir()):
        manifest = harness_dir / "profile.toml"
        # `models/` holds the model-density axis (load_model_profiles), not a harness.
        if harness_dir.name == "models":
            continue
        if not harness_dir.is_dir() or not manifest.exists():
            continue
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        ttype = str(data.get("transform", "identity"))
        version = str(data.get("version", "0"))
        if ttype == "llm":
            if llm_client is None:
                continue
            transform = llm_transform(llm_client, str(data.get("style", harness_dir.name)))
        else:
            transform = BUILTIN_TRANSFORMS.get(ttype, identity_transform)
        out[harness_dir.name] = Profile(harness=harness_dir.name, version=version,
                                        transform=transform)
    return out


def model_profiles_dir(source_dir: Path | None = None) -> Path:
    return profiles_dir(source_dir) / "models"


def load_model_profiles(source_dir: Path | None = None, *,
                        llm_client: LLMClient | None = None) -> dict[str, Profile]:
    """Load ``<source_dir>/profiles/models/<key>/profile.toml`` into model-key → Profile.

    The model axis tunes *render density* (how much scaffolding the target model
    needs), composed after the harness dialect at bind time. A ``profile.toml`` has
    ``version``, ``transform`` (identity|trim|llm), an optional ``tier``
    (frontier|mid|small — advisory, for the matcher/ledger), and ``style`` (for llm).
    The ``<key>`` is whatever a surface's ``model`` field carries — a specific model
    id or a capability tier. Keys with no profile pass through verbatim (no model
    tuning), so the axis is fully optional and backward-compatible. An ``llm`` profile
    is skipped when no ``llm_client`` is supplied (offline binds don't fail on it).

    The Profile's ``harness`` slot carries the model key — it is a render-axis identity
    used only as a cache-key label (Profile is the shared render-axis shape).
    """
    d = model_profiles_dir(source_dir)
    out: dict[str, Profile] = {}
    if not d.exists():
        return out
    for model_dir in sorted(d.iterdir()):
        manifest = model_dir / "profile.toml"
        if not model_dir.is_dir() or not manifest.exists():
            continue
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        ttype = str(data.get("transform", "identity"))
        version = str(data.get("version", "0"))
        if ttype == "llm":
            if llm_client is None:
                continue
            transform = llm_transform(llm_client, str(data.get("style", model_dir.name)))
        else:
            transform = MODEL_TRANSFORMS.get(ttype, identity_transform)
        out[model_dir.name] = Profile(harness=model_dir.name, version=version,
                                      transform=transform)
    return out
