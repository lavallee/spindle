"""Touchpoint A: the advisory `chip:` alias on ComposedSkill.

Mirrors test_tier.py — the chip alias is read from a channel's optional `chips`
map (or the skill's `chip:` frontmatter) and travels through resolve → render →
materialize untouched. It is purely advisory; nothing enforces it.
"""

from __future__ import annotations

import spindle.channels as ch
import spindle.composition as composition
import spindle.render as render
import spindle.materialize as materialize
from spindle.channels import Surface
from spindle.composition import ChannelLayer, ComposedSkill, Composition


def _write_manifest(root, scope, name, harness, body):
    p = ch.channel_manifest_path(root, scope, name, harness)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


def _skill_dir(tmp_path, name, frontmatter_chip=None):
    d = tmp_path / name
    d.mkdir()
    fm = f"---\nname: {name}\n"
    if frontmatter_chip is not None:
        fm += f"chip: {frontmatter_chip}\n"
    fm += "---\n"
    (d / "SKILL.md").write_text(fm + f"# {name}\n\nbody\n")
    return d


def test_fs_provider_reads_chips_map(tmp_path):
    root = tmp_path / "dist"
    _write_manifest(root, "system", "system", "claude",
                    'version = "1"\nskills = ["gate", "plan"]\n'
                    '[chips]\ngate = "signoff-chip"\n')
    index = {"gate": tmp_path / "g", "plan": tmp_path / "p"}
    layer = ch.fs_provider(index, source_dir=root)("system", "system", "claude")
    chips = {s.name: s.chip for s in layer.skills}
    assert chips == {"gate": "signoff-chip", "plan": ""}


def test_fs_provider_falls_back_to_frontmatter_chip(tmp_path):
    root = tmp_path / "dist"
    _write_manifest(root, "system", "system", "claude",
                    'version = "1"\nskills = ["gate"]\n')  # no [chips] table
    gate_dir = _skill_dir(tmp_path, "gate", frontmatter_chip="fm-chip")
    layer = ch.fs_provider({"gate": gate_dir}, source_dir=root)("system", "system", "claude")
    assert layer.skills[0].chip == "fm-chip"


def test_manifest_chips_map_wins_over_frontmatter(tmp_path):
    root = tmp_path / "dist"
    _write_manifest(root, "system", "system", "claude",
                    'version = "1"\nskills = ["gate"]\n'
                    '[chips]\ngate = "manifest-chip"\n')
    gate_dir = _skill_dir(tmp_path, "gate", frontmatter_chip="fm-chip")
    layer = ch.fs_provider({"gate": gate_dir}, source_dir=root)("system", "system", "claude")
    assert layer.skills[0].chip == "manifest-chip"


def test_chip_defaults_empty_when_absent(tmp_path):
    root = tmp_path / "dist"
    _write_manifest(root, "system", "system", "claude",
                    'version = "1"\nskills = ["plan"]\n')
    plain = _skill_dir(tmp_path, "plan")  # no chip frontmatter
    layer = ch.fs_provider({"plan": plain}, source_dir=root)("system", "system", "claude")
    assert layer.skills[0].chip == ""


def test_resolve_preserves_chip():
    layer = ChannelLayer(
        scope="system", name="sys", version="1",
        skills=[ComposedSkill("gate", "/gate", "system", source_dir="/g", chip="signoff-chip")],
    )
    comp = composition.resolve([layer], surface="r", autonomy_mode="deterministic")
    assert comp.skills[0].chip == "signoff-chip"


def test_render_preserves_chip(tmp_path):
    d = _skill_dir(tmp_path, "gate")
    comp = Composition(
        surface="r", autonomy_mode="deterministic",
        skills=[ComposedSkill("gate", "/gate", "system", source_dir=str(d), chip="signoff-chip")],
    )
    surface = Surface(name="r", harness="claude", autonomy_mode="deterministic")
    render_fn = render.make_render_fn(
        {"claude": render.Profile("claude", "1", render.identity_transform)},
        "doctrine@1", store_root=tmp_path / "store",
    )
    out = render_fn(comp, surface)
    # source_dir gets rewritten to the rendered store, but chip must survive
    assert out.skills[0].chip == "signoff-chip"


def test_materialize_ignores_but_tolerates_chip(tmp_path):
    d = _skill_dir(tmp_path, "gate")
    comp = Composition(
        surface="r", autonomy_mode="deterministic",
        skills=[ComposedSkill("gate", "/gate", "system", source_dir=str(d), chip="signoff-chip")],
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    actions = materialize.materialize(comp, repo, "claude")
    assert ("gate", "linked") in actions
    assert (repo / ".claude" / "skills" / "gate").is_symlink()
