"""End-to-end tests for spindle.binder.bind — select→resolve→render→lint→materialize→record."""

from __future__ import annotations

import spindle.binder as binder
import spindle.binding as binding_mod
import spindle.inventory as inventory_mod
from spindle.channels import Surface
from spindle.composition import ChannelLayer, ComposedSkill
from spindle.doctrine import Doctrine
from spindle.lifecycle import (
    ExpectedProjection,
    OwnershipRecord,
    OwnershipStore,
    SurfaceLock,
    digest_path,
    read_surface_lock,
    surface_id,
    write_surface_lock,
)


def _doctrine():
    return Doctrine(version="0.1.0")


def _make_skill_src(tmp_path, name):
    d = tmp_path / "src" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"# {name}\n")
    return d


def _provider_factory(tmp_path):
    """A fake channel provider: system has 'grill', repo 'demo' has an override skill."""
    grill = _make_skill_src(tmp_path, "grill")
    repo_extra = _make_skill_src(tmp_path, "repo-tool")

    def provider(scope, name, harness):
        if scope == "system":
            return ChannelLayer(
                scope="system",
                name="system",
                version="1.0",
                skills=[
                    ComposedSkill("grill", "/grill", "system", source_dir=str(grill))
                ],
            )
        if scope == "repo" and name == "demo":
            return ChannelLayer(
                scope="repo",
                name="repo:demo",
                version="0.1",
                skills=[
                    ComposedSkill(
                        "repo-tool", "/repo-tool", "repo", source_dir=str(repo_extra)
                    )
                ],
            )
        return None

    return provider


def test_bind_end_to_end_materializes_and_records(tmp_path, monkeypatch):
    monkeypatch.setattr(binding_mod.paths, "spindle_home", lambda: tmp_path / "state")
    repo = tmp_path / "demo"
    repo.mkdir()
    provider = _provider_factory(tmp_path)
    surface = Surface(name="demo", harness="claude", autonomy_mode="deterministic")

    result = binder.bind(surface, repo, provider, _doctrine())

    assert result.ok
    assert result.problems == []
    assert result.coordinate is not None
    # both system + repo skills landed in the repo-local claude dir
    tdir = repo / ".claude" / "skills"
    assert (tdir / "grill").is_symlink()
    assert (tdir / "repo-tool").is_symlink()
    # binding recorded for rollback
    cur = binding_mod.current_binding("demo")
    assert cur.coordinate == result.coordinate
    assert sorted(cur.skills) == ["grill", "repo-tool"]


def test_bind_writes_exact_surface_lock_and_ownership_receipts(tmp_path, monkeypatch):
    monkeypatch.setattr(binding_mod.paths, "spindle_home", lambda: tmp_path / "state")
    repo = tmp_path / "demo"
    repo.mkdir()
    surface = Surface(name="demo", harness="codex", autonomy_mode="deterministic")

    result = binder.bind(surface, repo, _provider_factory(tmp_path), _doctrine())

    sid = surface_id(repo, "codex")
    lock = read_surface_lock(sid)
    assert result.ok
    assert lock is not None
    assert lock.binding_coordinate == result.coordinate
    assert {projection.skill for projection in lock.projections} == {
        "grill",
        "repo-tool",
    }
    ownership = OwnershipStore().records(sid)
    assert set(ownership) == {
        str((repo / ".agents" / "skills" / "grill").absolute()),
        str((repo / ".agents" / "skills" / "repo-tool").absolute()),
    }
    observed = inventory_mod.scan_effective_inventory(
        repo,
        "codex",
        lock=lock,
        ownership_store=OwnershipStore(),
        roots=(
            inventory_mod.DiscoveryRoot(
                "repo:.", repo / ".agents" / "skills", precedence=100
            ),
        ),
    )
    assert {entry.state for entry in observed.entries} == {
        inventory_mod.InventoryState.EXPECTED_OWNED
    }


def test_rebind_refuses_user_retargeted_owned_symlink(tmp_path, monkeypatch):
    monkeypatch.setattr(binding_mod.paths, "spindle_home", lambda: tmp_path / "state")
    repo = tmp_path / "demo"
    repo.mkdir()
    provider = _provider_factory(tmp_path)
    surface = Surface(name="demo", harness="claude", autonomy_mode="deterministic")
    first = binder.bind(surface, repo, provider, _doctrine())
    link = repo / ".claude" / "skills" / "grill"
    foreign = _make_skill_src(tmp_path, "foreign-grill")
    link.unlink()
    link.symlink_to(foreign)

    second = binder.bind(surface, repo, provider, _doctrine())

    assert first.ok
    assert not second.ok
    assert ("grill", "skipped:foreign-symlink") in second.actions
    assert link.resolve() == foreign.resolve()
    assert binding_mod.current_binding("demo").coordinate == first.coordinate


def test_bind_fails_closed_on_lint_problem(tmp_path, monkeypatch):
    monkeypatch.setattr(binding_mod.paths, "spindle_home", lambda: tmp_path / "state")
    repo = tmp_path / "demo"
    repo.mkdir()
    grill = _make_skill_src(tmp_path, "grill")

    def colliding_provider(scope, name, harness):
        # two cluster channels both claim /x — same-scope collision → lint problem
        if scope == "cluster":
            return ChannelLayer(
                scope="cluster",
                name=f"cluster:{name}",
                skills=[ComposedSkill(name, "/x", "cluster", source_dir=str(grill))],
            )
        return None

    surface = Surface(
        name="demo",
        harness="claude",
        autonomy_mode="deterministic",
        clusters=("c1", "c2"),
    )
    result = binder.bind(surface, repo, colliding_provider, _doctrine())

    assert result.ok is False
    assert any("same-scope collision" in p for p in result.problems)
    # nothing materialized
    assert not (repo / ".claude" / "skills").exists() or not list(
        (repo / ".claude" / "skills").iterdir()
    )
    # nothing recorded
    assert binding_mod.current_binding("demo") is None


def test_bind_force_materializes_despite_problems(tmp_path, monkeypatch):
    monkeypatch.setattr(binding_mod.paths, "spindle_home", lambda: tmp_path / "state")
    repo = tmp_path / "demo"
    repo.mkdir()
    grill = _make_skill_src(tmp_path, "grill")

    def colliding_provider(scope, name, harness):
        if scope == "cluster":
            return ChannelLayer(
                scope="cluster",
                name=f"cluster:{name}",
                skills=[ComposedSkill(name, "/x", "cluster", source_dir=str(grill))],
            )
        return None

    surface = Surface(
        name="demo",
        harness="claude",
        autonomy_mode="deterministic",
        clusters=("c1", "c2"),
    )
    result = binder.bind(surface, repo, colliding_provider, _doctrine(), force=True)
    assert result.ok
    assert result.coordinate is not None


def test_bind_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(binding_mod.paths, "spindle_home", lambda: tmp_path / "state")
    repo = tmp_path / "demo"
    repo.mkdir()
    provider = _provider_factory(tmp_path)
    surface = Surface(name="demo", harness="claude", autonomy_mode="deterministic")

    result = binder.bind(surface, repo, provider, _doctrine(), dry_run=True)
    assert result.ok
    assert result.coordinate is None  # not recorded on dry-run
    assert not (repo / ".claude" / "skills" / "grill").exists()
    assert binding_mod.current_binding("demo") is None


def test_bind_rebind_reconciles_dropped_skill(tmp_path, monkeypatch):
    monkeypatch.setattr(binding_mod.paths, "spindle_home", lambda: tmp_path / "state")
    repo = tmp_path / "demo"
    repo.mkdir()
    provider = _provider_factory(tmp_path)
    surface = Surface(name="demo", harness="claude", autonomy_mode="deterministic")
    binder.bind(surface, repo, provider, _doctrine())  # binds grill + repo-tool

    # rebind with only system (no repo channel) → repo-tool should be reconciled away
    def system_only(scope, name, harness):
        return provider(scope, name, harness) if scope == "system" else None

    result = binder.bind(surface, repo, system_only, _doctrine())
    assert ("repo-tool", "removed") in result.actions
    assert not (repo / ".claude" / "skills" / "repo-tool").exists()
    assert (repo / ".claude" / "skills" / "grill").is_symlink()


def test_bind_preserves_noncolliding_active_lease_projection(tmp_path, monkeypatch):
    monkeypatch.setattr(binding_mod.paths, "spindle_home", lambda: tmp_path / "state")
    repo = tmp_path / "demo"
    repo.mkdir()
    leased_source = _make_skill_src(tmp_path, "leased")
    leased_link = repo / ".agents" / "skills" / "leased"
    leased_link.parent.mkdir(parents=True)
    leased_link.symlink_to(leased_source)
    sid = surface_id(repo, "codex")
    digest = digest_path(leased_source)
    lease_id = "sha256:" + "a" * 64
    projection = ExpectedProjection(
        skill="leased",
        projection_path=str(leased_link.absolute()),
        source_path=str(leased_source.resolve()),
        source_digest=digest,
        package_digest=digest,
        authority=f"lease:{lease_id}",
    )
    write_surface_lock(
        SurfaceLock(
            surface_id=sid,
            surface_name="demo",
            repo_path=str(repo.resolve()),
            harness="codex",
            binding_coordinate="lease-only/v1",
            projections=(projection,),
            lease_ids=(lease_id,),
        )
    )
    OwnershipStore().record(
        OwnershipRecord(
            surface_id=sid,
            surface_name="demo",
            harness="codex",
            skill="leased",
            projection_path=str(leased_link.absolute()),
            source_path=str(leased_source.resolve()),
            source_digest=digest,
            package_digest=digest,
            creation_receipt_id=f"lease:{lease_id}",
        )
    )
    surface = Surface(name="demo", harness="codex", autonomy_mode="deterministic")

    result = binder.bind(surface, repo, _provider_factory(tmp_path), _doctrine())
    lock = read_surface_lock(sid)

    assert result.ok
    assert leased_link.resolve() == leased_source.resolve()
    assert lock is not None and lock.lease_ids == (lease_id,)
    assert {item.skill for item in lock.projections} == {
        "grill",
        "repo-tool",
        "leased",
    }


# ---- render integration -------------------------------------------------


def test_bind_with_render_repoints_and_records(tmp_path, monkeypatch):
    import spindle.render as render

    monkeypatch.setattr(binding_mod.paths, "spindle_home", lambda: tmp_path / "state")
    repo = tmp_path / "demo"
    repo.mkdir()
    grill = _make_skill_src(tmp_path, "grill")
    (grill / "SKILL.md").write_text("# grill\nNEVER fabricate.\n")

    def provider(scope, name, harness):
        if scope == "system":
            return ChannelLayer(
                scope="system",
                name="system",
                version="1.0",
                skills=[
                    ComposedSkill(
                        "grill",
                        "/grill",
                        "system",
                        source_dir=str(grill),
                        package_digest="sha256:" + "a" * 64,
                    )
                ],
            )
        return None

    profile = render.Profile("claude", "1", render.identity_transform)
    render_fn = render.make_render_fn(
        {"claude": profile}, "0.1.0+abc", store_root=tmp_path / "rendered"
    )
    surface = Surface(name="demo", harness="claude", autonomy_mode="deterministic")
    result = binder.bind(surface, repo, provider, _doctrine(), render=render_fn)
    assert result.ok
    # the materialized skill points at the rendered store, not the canonical dir
    link = repo / ".claude" / "skills" / "grill"
    assert link.is_symlink()
    assert (tmp_path / "rendered") in link.resolve().parents
    from spindle.lifecycle import OwnershipStore, read_surface_lock, surface_id

    sid = surface_id(repo, "claude")
    lock = read_surface_lock(sid)
    assert lock.projections[0].package_digest == "sha256:" + "a" * 64
    ownership = OwnershipStore().records(sid)[str(link.absolute())]
    assert ownership.package_digest == "sha256:" + "a" * 64


def test_bind_fails_closed_when_render_drops_guardrail(tmp_path, monkeypatch):
    import spindle.render as render

    monkeypatch.setattr(binding_mod.paths, "spindle_home", lambda: tmp_path / "state")
    repo = tmp_path / "demo"
    repo.mkdir()
    grill = _make_skill_src(tmp_path, "grill")
    (grill / "SKILL.md").write_text("# grill\nNEVER fabricate.\n")

    def provider(scope, name, harness):
        if scope == "system":
            return ChannelLayer(
                scope="system",
                name="system",
                skills=[
                    ComposedSkill("grill", "/grill", "system", source_dir=str(grill))
                ],
            )
        return None

    evil = render.Profile("claude", "1", lambda t: "# gutted\n")
    render_fn = render.make_render_fn(
        {"claude": evil}, "d", store_root=tmp_path / "rendered"
    )
    surface = Surface(name="demo", harness="claude", autonomy_mode="deterministic")
    result = binder.bind(surface, repo, provider, _doctrine(), render=render_fn)
    assert result.ok is False
    assert any("render:" in p and "NEVER fabricate" in p for p in result.problems)
    # nothing materialized, nothing recorded
    assert not (repo / ".claude" / "skills" / "grill").exists()
    assert binding_mod.current_binding("demo") is None


# ---- unbind -------------------------------------------------------------


def test_unbind_removes_materialized_skills(tmp_path, monkeypatch):
    monkeypatch.setattr(binding_mod.paths, "spindle_home", lambda: tmp_path / "state")
    repo = tmp_path / "demo"
    repo.mkdir()
    provider = _provider_factory(tmp_path)
    surface = Surface(name="demo", harness="claude", autonomy_mode="deterministic")
    binder.bind(surface, repo, provider, _doctrine())
    tdir = repo / ".claude" / "skills"
    assert (tdir / "grill").is_symlink()

    actions = binder.unbind("demo", repo, "claude")
    removed = sorted(n for n, a in actions if a == "removed")
    assert removed == ["grill", "repo-tool"]  # both channels' skills removed
    assert not (tdir / "grill").exists()
    assert not (tdir / "repo-tool").exists()


def test_unbind_noop_when_never_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(binding_mod.paths, "spindle_home", lambda: tmp_path / "state")
    repo = tmp_path / "demo"
    repo.mkdir()
    actions = binder.unbind("demo", repo, "claude")
    assert [a for _, a in actions if a == "removed"] == []


def test_unbind_preserves_retargeted_link_and_desired_lock(tmp_path, monkeypatch):
    from spindle.lifecycle import read_surface_lock, surface_id

    monkeypatch.setattr(binding_mod.paths, "spindle_home", lambda: tmp_path / "state")
    repo = tmp_path / "demo"
    repo.mkdir()
    provider = _provider_factory(tmp_path)
    surface = Surface(name="demo", harness="claude", autonomy_mode="deterministic")
    binder.bind(surface, repo, provider, _doctrine())
    sid = surface_id(repo, "claude")
    before = read_surface_lock(sid)
    link = repo / ".claude" / "skills" / "grill"
    link.unlink()
    foreign = _make_skill_src(tmp_path, "foreign")
    link.symlink_to(foreign)

    actions = binder.unbind("demo", repo, "claude")

    assert ("grill", "skipped:ownership-mismatch") in actions
    assert link.resolve() == foreign.resolve()
    assert read_surface_lock(sid).lock_id == before.lock_id


# ---- hermes: bind/unbind against the global skills dir -------------------


def test_bind_unbind_hermes_global_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(binding_mod.paths, "spindle_home", lambda: tmp_path / "state")
    hdir = tmp_path / "hermes-skills" / "spindle"
    monkeypatch.setenv("SPINDLE_HERMES_SKILLS_DIR", str(hdir))
    repo = tmp_path / "demo"
    repo.mkdir()
    provider = _provider_factory(tmp_path)
    surface = Surface(name="demo", harness="hermes", autonomy_mode="deterministic")

    result = binder.bind(surface, repo, provider, _doctrine())
    assert result.ok
    # skills land in the global hermes category dir, not inside the repo
    assert (hdir / "grill").is_symlink()
    assert (hdir / "repo-tool").is_symlink()
    assert not (repo / ".hermes").exists()
    assert sorted(binding_mod.current_binding("demo").skills) == ["grill", "repo-tool"]

    actions = binder.unbind("demo", repo, "hermes")
    removed = sorted(n for n, a in actions if a == "removed")
    assert removed == ["grill", "repo-tool"]
    assert not (hdir / "grill").exists()
    assert not (hdir / "repo-tool").exists()
