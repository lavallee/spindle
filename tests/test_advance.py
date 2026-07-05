"""Tests for spindle.advance — precompute across surfaces + target loading."""

from __future__ import annotations

import spindle.advance as advance
import spindle.binding as binding_mod
from spindle.composition import ChannelLayer, ComposedSkill
from spindle.doctrine import Doctrine


def _doc():
    return Doctrine(version="0.1.0")


def _skill_src(tmp_path, name):
    d = tmp_path / "src" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"# {name}\n")
    return d


def test_load_targets(tmp_path):
    root = tmp_path / "dist"
    d = root / "advance"
    d.mkdir(parents=True)
    (d / "surfaces.toml").write_text(
        '[[surface]]\nname="a"\npath="/p/a"\nharness="claude"\n'
        '[[surface]]\nname="b"\npath="/p/b"\nharness="codex"\nautonomy="self_evolving"\n'
    )
    targets = advance.load_targets(source_dir=root)
    assert [t.name for t in targets] == ["a", "b"]
    assert targets[1].harness == "codex"
    assert targets[1].autonomy_mode == "self_evolving"


def test_load_targets_empty_when_no_manifest(tmp_path):
    assert advance.load_targets(source_dir=tmp_path) == []


def test_precompute_binds_each_surface(tmp_path, monkeypatch):
    monkeypatch.setattr(binding_mod.paths, "spindle_home", lambda: tmp_path / "state")
    grill = _skill_src(tmp_path, "grill")

    def provider(scope, name, harness):
        if scope == "system":
            return ChannelLayer(scope="system", name="system",
                                skills=[ComposedSkill("grill", "/grill", "system", source_dir=str(grill))])
        return None

    repo_a = tmp_path / "a"
    repo_a.mkdir()
    repo_b = tmp_path / "b"
    repo_b.mkdir()
    targets = [advance.Target("a", str(repo_a)), advance.Target("b", str(repo_b))]
    results = advance.precompute(targets, provider, _doc())
    assert [name for name, _ in results] == ["a", "b"]
    assert all(r.ok for _, r in results)
    assert (repo_a / ".claude" / "skills" / "grill").is_symlink()
    assert (repo_b / ".claude" / "skills" / "grill").is_symlink()


def test_precompute_continues_past_a_failing_surface(tmp_path, monkeypatch):
    monkeypatch.setattr(binding_mod.paths, "spindle_home", lambda: tmp_path / "state")
    grill = _skill_src(tmp_path, "grill")

    def colliding_provider(scope, name, harness):
        # cluster channels collide → lint problem → that surface is BLOCKED
        if scope == "cluster":
            return ChannelLayer(scope="cluster", name=f"cluster:{name}",
                                skills=[ComposedSkill(name, "/x", "cluster", source_dir=str(grill))])
        return None

    repo = tmp_path / "bad"
    repo.mkdir()
    # appclass on an empty repo yields one cluster key; force two colliding by
    # using a target whose repo classifies into a cluster the provider answers twice.
    targets = [advance.Target("bad", str(repo))]
    # monkeypatch target_to_surface to inject two clusters that collide
    from spindle.channels import Surface
    monkeypatch.setattr(advance, "target_to_surface",
                        lambda t: Surface(name=t.name, harness="claude",
                                          autonomy_mode="deterministic", clusters=("c1", "c2")))
    results = advance.precompute(targets, colliding_provider, _doc())
    assert results[0][1].ok is False
    assert any("same-scope collision" in p for p in results[0][1].problems)


# ---- registry enumeration -----------------------------------------------

def _project_toml(projects_dir, name, *, status="active", harnesses=("claude",), repo="x"):
    projects_dir.mkdir(parents=True, exist_ok=True)
    hs = ", ".join(f'"{h}"' for h in harnesses)
    (projects_dir / f"{name}.toml").write_text(
        f'name = "{name}"\nkind = "service"\nowner = "shared"\nstatus = "{status}"\n'
        f'repo = "{repo}"\nharnesses = [{hs}]\n'
    )


def test_targets_from_registry_one_per_harness(tmp_path):
    projects = tmp_path / "projects"
    root = tmp_path / "checkouts"
    _project_toml(projects, "barn-owl", harnesses=("claude", "codex"))
    (root / "barn-owl").mkdir(parents=True)  # local checkout exists
    targets = advance.targets_from_registry(projects, repo_root=root)
    assert {(t.name, t.harness) for t in targets} == {("barn-owl", "claude"), ("barn-owl", "codex")}
    assert all(t.path == str(root / "barn-owl") for t in targets)


def test_targets_from_registry_skips_no_checkout(tmp_path):
    projects = tmp_path / "projects"
    root = tmp_path / "checkouts"
    root.mkdir()
    _project_toml(projects, "ghost")  # no checkout dir created
    assert advance.targets_from_registry(projects, repo_root=root) == []


def test_targets_from_registry_skips_archived_and_no_harness(tmp_path):
    projects = tmp_path / "projects"
    root = tmp_path / "checkouts"
    _project_toml(projects, "old", status="archived")
    _project_toml(projects, "nohar", harnesses=())
    (root / "old").mkdir(parents=True)
    (root / "nohar").mkdir(parents=True)
    assert advance.targets_from_registry(projects, repo_root=root) == []


def test_targets_from_registry_missing_dir_returns_empty(tmp_path):
    assert advance.targets_from_registry(tmp_path / "nope", repo_root=tmp_path) == []
