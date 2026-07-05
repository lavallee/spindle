"""LLM client for live dialect rendering (and any future LLM-backed transform).

Kept optional and lazy: spindle is zero-dep by default, so the ``anthropic`` SDK is
imported only when an LLM transform is actually used, and ``from_env`` returns
``None`` (rather than raising) when no API key or SDK is present — so an offline
``spindle bind`` simply skips ``llm`` profiles instead of failing.

The dialect prompt has a stable instruction prefix; we mark it with
``cache_control`` so repeated renders hit the prompt cache (cheap, high-volume).
"""

from __future__ import annotations

import os
from typing import Callable, Optional

# A client takes the variable user text and an optional *stable* system prefix.
# Splitting them lets us cache the system prefix (the dialect instruction is the
# same across every skill in a render pass), per claude-api prompt-caching guidance.
LLMClient = Callable[..., str]  # call(user_text, *, system=None) -> completion text

DEFAULT_MODEL = "claude-sonnet-4-6"  # dialect rendering is cheap/high-volume → Sonnet


def from_env(*, model: str = DEFAULT_MODEL) -> Optional[LLMClient]:
    """An Anthropic-backed client from ANTHROPIC_API_KEY, or None if unavailable.

    None (not an exception) when the key or the SDK is missing, so callers degrade
    to identity/skip rather than break. A ``system`` prefix is sent as a cached
    block (``cache_control: ephemeral``) so repeated renders in a pass reuse it.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
    except ImportError:  # pragma: no cover - optional dep
        return None

    client = anthropic.Anthropic(api_key=key)

    def call(user_text: str, *, system: str | None = None) -> str:
        kwargs: dict = {
            "model": model,
            "max_tokens": 8192,
            "messages": [{"role": "user", "content": user_text}],
        }
        if system:
            kwargs["system"] = [{
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }]
        resp = client.messages.create(**kwargs)
        return "".join(
            getattr(block, "text", "") for block in resp.content
            if getattr(block, "type", None) == "text"
        )

    return call
