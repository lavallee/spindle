"""Tests for spindle.materialize — per-surface subset symlinking + safe reconcile."""

from __future__ import annotations

import spindle.materialize as mz
from spindle.composition import ComposedSkill, Composition


def _skill(name, src):
    return ComposedSkill(name=name, command=f"/{name}", scope="repo", source_dir=str(src))


def _make_source_skills(tmp_path, *names):
    out = {}
    for n in names:
        d = tmp_path / "src" / n
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"# {n}\n")
        out[n] = d
    return out


def test_target_dir_per_harness(tmp_path):
    assert mz.target_dir(tmp_path, "claude") == tmp_path / ".claude" / "skills"
    assert mz.target_dir(tmp_path, "codex") == tmp_path / ".codex" / "skills"
    assert mz.target_dir(tmp_path, "pi") == tmp_path / ".pi" / "skills"


def test_materialize_links_subset(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    srcs = _make_source_skills(tmp_path, "grill", "plan")
    comp = Composition(surface="r", autonomy_mode="deterministic",
                       skills=[_skill("grill", srcs["grill"]), _skill("plan", srcs["plan"])])
    results = mz.materialize(comp, repo, "claude")
    assert sorted(results) == [("grill", "linked"), ("plan", "linked")]
    tdir = repo / ".claude" / "skills"
    assert (tdir / "grill").is_symlink()
    assert (tdir / "grill").resolve() == srcs["grill"].resolve()


def test_materialize_is_idempotent(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    srcs = _make_source_skills(tmp_path, "grill")
    comp = Composition(surface="r", autonomy_mode="deterministic", skills=[_skill("grill", srcs["grill"])])
    mz.materialize(comp, repo, "claude")
    results = mz.materialize(comp, repo, "claude")
    assert results == [("grill", "kept")]


def test_materialize_reconciles_removed_skill(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    srcs = _make_source_skills(tmp_path, "grill", "plan")
    comp1 = Composition(surface="r", autonomy_mode="deterministic",
                        skills=[_skill("grill", srcs["grill"]), _skill("plan", srcs["plan"])])
    mz.materialize(comp1, repo, "claude")
    # next bind drops "plan"; previous tells materialize what it owned
    comp2 = Composition(surface="r", autonomy_mode="deterministic", skills=[_skill("grill", srcs["grill"])])
    results = mz.materialize(comp2, repo, "claude", previous={"grill", "plan"})
    assert ("plan", "removed") in results
    assert not (repo / ".claude" / "skills" / "plan").exists()
    assert (repo / ".claude" / "skills" / "grill").is_symlink()


def test_materialize_leaves_foreign_files_untouched(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    tdir = repo / ".claude" / "skills"
    tdir.mkdir(parents=True)
    (tdir / "handmade").mkdir()  # a real dir someone added — not ours
    (tdir / "handmade" / "SKILL.md").write_text("# mine\n")
    srcs = _make_source_skills(tmp_path, "grill")
    comp = Composition(surface="r", autonomy_mode="deterministic", skills=[_skill("grill", srcs["grill"])])
    # even if told "handmade" was previous, it's not a symlink → never deleted
    results = mz.materialize(comp, repo, "claude", previous={"handmade"})
    assert (tdir / "handmade").is_dir()
    assert ("handmade", "removed") not in results


def test_materialize_skips_skill_with_no_source(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    comp = Composition(surface="r", autonomy_mode="deterministic",
                       skills=[ComposedSkill("nosrc", "/nosrc", "repo")])  # no source_dir
    results = mz.materialize(comp, repo, "claude")
    assert results == [("nosrc", "skipped:no-source")]


def test_materialize_dry_run_writes_nothing(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    srcs = _make_source_skills(tmp_path, "grill")
    comp = Composition(surface="r", autonomy_mode="deterministic", skills=[_skill("grill", srcs["grill"])])
    results = mz.materialize(comp, repo, "claude", dry_run=True)
    assert results == [("grill", "linked")]
    assert not (repo / ".claude" / "skills" / "grill").exists()
