"""Tests for spindle.channels — surface subscription order + provider-driven loading."""

from __future__ import annotations

import spindle.channels as ch
from spindle.composition import ChannelLayer, ComposedSkill


def test_subscribed_channels_order_system_clusters_repo():
    s = ch.Surface(name="barn-owl", harness="claude", autonomy_mode="deterministic",
                   clusters=("lang:python|uses-llms", "network-service"))
    assert ch.subscribed_channels(s) == [
        ("system", "system"),
        ("cluster", "lang:python|uses-llms"),
        ("cluster", "network-service"),
        ("repo", "barn-owl"),
    ]


def test_subscribed_channels_no_clusters():
    s = ch.Surface(name="solo", harness="codex", autonomy_mode="self_evolving")
    assert ch.subscribed_channels(s) == [("system", "system"), ("repo", "solo")]


def test_select_layers_uses_provider_and_passes_harness():
    seen = []

    def provider(scope, name, harness):
        seen.append((scope, name, harness))
        return ChannelLayer(scope=scope, skills=[ComposedSkill(f"{scope}-skill", f"/{scope}", scope)])

    s = ch.Surface(name="r", harness="claude", autonomy_mode="deterministic",
                   clusters=("c1",))
    layers = ch.select_layers(s, provider)
    assert [layer.scope for layer in layers] == ["system", "cluster", "repo"]
    # harness threaded to every provider call
    assert all(h == "claude" for (_, _, h) in seen)


def test_select_layers_skips_missing_channels():
    def provider(scope, name, harness):
        # only system exists for this harness
        return ChannelLayer(scope="system") if scope == "system" else None

    s = ch.Surface(name="r", harness="pi", autonomy_mode="deterministic", clusters=("c1",))
    layers = ch.select_layers(s, provider)
    assert [layer.scope for layer in layers] == ["system"]


# ---- filesystem provider ------------------------------------------------

def _write_manifest(root, scope, name, harness, body):
    p = ch.channel_manifest_path(root, scope, name, harness)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


def test_fs_provider_reads_manifest_and_resolves_skills(tmp_path):
    root = tmp_path / "dist"
    _write_manifest(root, "system", "system", "claude",
                    'version = "1.0"\nabsolutes = ["A1"]\nskills = ["grill", "plan"]\n')
    index = {"grill": tmp_path / "src/grill", "plan": tmp_path / "src/plan"}
    provider = ch.fs_provider(index, source_dir=root)
    layer = provider("system", "system", "claude")
    assert layer is not None
    assert layer.version == "1.0"
    assert layer.absolutes == ["A1"]
    assert sorted(s.name for s in layer.skills) == ["grill", "plan"]
    g = next(s for s in layer.skills if s.name == "grill")
    assert g.command == "/grill"
    assert g.source_dir == str(tmp_path / "src/grill")


def test_fs_provider_skips_skills_absent_from_index(tmp_path):
    root = tmp_path / "dist"
    _write_manifest(root, "system", "system", "claude",
                    'version = "1.0"\nskills = ["known", "missing"]\n')
    provider = ch.fs_provider({"known": tmp_path / "k"}, source_dir=root)
    layer = provider("system", "system", "claude")
    assert [s.name for s in layer.skills] == ["known"]


def test_fs_provider_returns_none_for_missing_channel(tmp_path):
    provider = ch.fs_provider({}, source_dir=tmp_path / "dist")
    assert provider("repo", "nope", "claude") is None


def test_fs_provider_serves_shipped_spindle_sample_system_channel():
    """The repo's spindle-sample system/claude manifest is well-formed and parses."""
    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent
    root = repo / "examples" / "spindle-sample"
    # index every listed skill to a dummy dir so the provider builds the layer
    import tomllib
    manifest = ch.channel_manifest_path(root, "system", "system", "claude")
    names = tomllib.loads(manifest.read_text())["skills"]
    index = {n: repo / "fake" / n for n in names}
    layer = ch.fs_provider(index, source_dir=root)("system", "system", "claude")
    assert layer is not None
    assert layer.scope == "system"
    assert len(layer.skills) == len(names) == 4
    assert all(s.command == f"/{s.name}" for s in layer.skills)
