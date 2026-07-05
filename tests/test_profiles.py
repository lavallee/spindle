"""Tests for spindle.profiles — transforms + data-driven profile loading."""

from __future__ import annotations

import spindle.profiles as profiles
import spindle.render as render

GUARDED = "# skill\n\n\n\nALWAYS check.\n   \nNEVER skip.\n\n\nprose.\n"


def test_terse_transform_collapses_blanks_preserves_guardrails():
    out = profiles.terse_transform(GUARDED)
    assert "\n\n\n" not in out                       # no triple blanks
    # guardrails survive → verification passes
    assert render.verify_preserved(GUARDED, out) == []
    assert "ALWAYS check." in out
    assert "NEVER skip." in out


def test_identity_in_registry():
    assert profiles.BUILTIN_TRANSFORMS["identity"]("x") == "x"


def test_llm_transform_splits_system_and_user():
    seen = {}

    def fake_client(user_text, *, system=None):
        seen["user"] = user_text
        seen["system"] = system
        return "rewritten: " + user_text

    t = profiles.llm_transform(fake_client, "terse imperative")
    out = t("ALWAYS x.\n")
    # stable instruction → system (cacheable); variable skill text → user
    assert "terse imperative" in seen["system"]
    assert "ALWAYS, NEVER, or DO NOT" in seen["system"]  # guardrail-preservation pinned
    assert seen["user"] == "ALWAYS x.\n"
    assert out.startswith("rewritten:")


def _write_profile(root, harness, body):
    d = root / "profiles" / harness
    d.mkdir(parents=True)
    (d / "profile.toml").write_text(body)


def test_load_profiles_builtin(tmp_path):
    _write_profile(tmp_path, "claude", 'version = "1"\ntransform = "identity"\n')
    _write_profile(tmp_path, "codex", 'version = "2"\ntransform = "terse"\n')
    profs = profiles.load_profiles(source_dir=tmp_path)
    assert set(profs) == {"claude", "codex"}
    assert profs["claude"].version == "1"
    assert profs["codex"].transform("a\n\n\n\nb\n").count("\n\n") <= 1


def test_load_profiles_llm_skipped_without_client(tmp_path):
    _write_profile(tmp_path, "pi", 'version = "1"\ntransform = "llm"\nstyle = "concise"\n')
    # no client → llm profile skipped (offline bind doesn't fail)
    assert profiles.load_profiles(source_dir=tmp_path) == {}
    # with a client → built
    profs = profiles.load_profiles(source_dir=tmp_path, llm_client=lambda p: "x")
    assert "pi" in profs


def test_load_profiles_empty_when_no_dir(tmp_path):
    assert profiles.load_profiles(source_dir=tmp_path) == {}


def test_shipped_profiles_load():
    from pathlib import Path
    sample = Path(__file__).resolve().parent.parent / "examples" / "spindle-sample"
    profs = profiles.load_profiles(source_dir=sample)
    assert profs["claude"].transform("x") == "x"        # identity reference
    assert "codex" in profs                              # terse
