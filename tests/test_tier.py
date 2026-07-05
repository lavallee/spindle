"""Tests for the P10 tier-routing hint (judgment | execution) — read from a
channel's optional `tiers` map, carried on ComposedSkill, preserved through resolve."""

from __future__ import annotations

import spindle.channels as ch
import spindle.composition as composition
from spindle.composition import ChannelLayer, ComposedSkill


def _write_manifest(root, scope, name, harness, body):
    p = ch.channel_manifest_path(root, scope, name, harness)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


def test_fs_provider_reads_tier_map(tmp_path):
    root = tmp_path / "dist"
    _write_manifest(root, "system", "system", "claude",
                    'version = "1"\nskills = ["plan", "exec"]\n'
                    '[tiers]\nplan = "judgment"\nexec = "execution"\n')
    index = {"plan": tmp_path / "p", "exec": tmp_path / "e"}
    layer = ch.fs_provider(index, source_dir=root)("system", "system", "claude")
    tiers = {s.name: s.tier for s in layer.skills}
    assert tiers == {"plan": "judgment", "exec": "execution"}


def test_tier_defaults_empty_when_absent(tmp_path):
    root = tmp_path / "dist"
    _write_manifest(root, "system", "system", "claude",
                    'version = "1"\nskills = ["plan"]\n')  # no [tiers]
    layer = ch.fs_provider({"plan": tmp_path / "p"}, source_dir=root)("system", "system", "claude")
    assert layer.skills[0].tier == ""


def test_resolve_preserves_tier():
    layer = ChannelLayer(
        scope="system", name="sys", version="1",
        skills=[ComposedSkill("plan", "/plan", "system", source_dir="/p", tier="judgment")],
    )
    comp = composition.resolve([layer], surface="r", autonomy_mode="deterministic")
    assert comp.skills[0].tier == "judgment"


def test_shipped_system_channel_tags_judgment(tmp_path):
    # the real spindle-sample system/claude channel tags the planning suite judgment-tier
    from pathlib import Path
    sample = Path(__file__).resolve().parents[1] / "examples" / "spindle-sample"
    import spindle.skills as skills_mod
    index = {s.name: s.skill_dir for s in skills_mod.discover_skills()}
    layer = ch.fs_provider(index, source_dir=sample)("system", "system", "claude")
    tiered = {s.name: s.tier for s in layer.skills if s.tier}
    assert tiered.get("clarify") == "judgment"
    assert tiered.get("review") == "judgment"
    assert all(t == "judgment" for t in tiered.values())
