"""spindle CLI."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from . import active as active_mod
from . import adapters as adapters_mod
from . import advance as advance_mod
from . import appclass as appclass_mod
from . import binder as binder_mod
from . import broker as broker_mod
from . import capabilities as capabilities_mod
from . import channels as channels_mod
from . import chippability as chippability_mod
from . import conformance as conformance_mod
from . import custody as custody_mod
from . import distributions as distributions_mod
from . import doctrine as doctrine_mod
from . import evaluation as evaluation_mod
from . import fleet as fleet_mod
from . import gates as gates_mod
from . import hooks as hooks_mod
from . import ingest as ingest_mod
from . import inventory as inventory_mod
from . import intent as intent_mod
from . import ledger as ledger_mod
from . import leases as leases_mod
from . import lifecycle as lifecycle_mod
from . import liaison as liaison_mod
from . import llm as llm_mod
from . import materialize as materialize_mod
from . import maintenance as maintenance_mod
from . import minimalism as minimalism_mod
from . import optimize as optimize_mod
from . import operator as operator_mod
from . import packages as packages_mod
from . import paths as paths_mod
from . import peers as peers_mod
from . import policy as policy_mod
from . import preempt as preempt_mod
from . import profiles as profiles_mod
from . import rate as rate_mod
from . import realization as realization_mod
from . import render as render_mod
from . import resolver as resolver_mod
from . import roster as roster_mod
from . import scaffold as scaffold_mod
from . import scout as scout_mod
from . import scout_results as scout_results_mod
from . import skills as skills_mod
from . import startup as startup_mod
from . import sources as sources_mod
from . import trust as trust_mod
from . import verdicts as verdicts_mod
from .paths import (
    claude_md_path,
    claude_skills_dir,
    events_file,
    ledger_path,
    state_file,
)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append_dist_event(kind: str, distribution: str, version: str) -> None:
    event = {
        "kind": kind,
        "distribution": distribution,
        "version": version,
        "ts": _now_iso(),
    }
    p = ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


def _strip_version(spec: str) -> str:
    """Extract bare package name from a PEP 508 spec like 'sample-planning==0.1.0'."""
    return re.split(r"[=<>!~@\[]", spec)[0].strip()


def cmd_status(_args) -> int:
    results = skills_mod.status_skills()
    print(f"claude_skills:  {claude_skills_dir()}")
    print(
        f"preempted:      {'yes' if preempt_mod.is_preempted() else 'no'} ({claude_md_path()})"
    )
    print()
    for name, state in results:
        print(f"  {name:<22} {state}")
    return 0


# ---- preempt ------------------------------------------------------------


def cmd_preempt(_args) -> int:
    print(preempt_mod.preempt())
    return 0


def cmd_unpreempt(_args) -> int:
    print(preempt_mod.unpreempt())
    return 0


# ---- peers --------------------------------------------------------------


def cmd_peers_list(_args) -> int:
    rows = peers_mod.list_peers()
    if not rows:
        print("(no peers registered)")
        return 0
    width = max(len(p.get("slug", "")) for p in rows)
    for p in rows:
        slug = p.get("slug", "")
        kind = p.get("kind", "?")
        last = p.get("last_seen", "?")
        take = p.get("our_take", "")
        print(f"  {slug:<{width}}  {kind:<8}  {last}  {take}")
    return 0


def cmd_peers_add(args) -> int:
    ok = peers_mod.add(
        slug=args.slug,
        name=args.name or args.slug,
        url=args.url,
        kind=args.kind,
        our_take=args.our_take or "",
        notes=args.notes or "",
    )
    print("added" if ok else "already-present")
    return 0 if ok else 1


def cmd_peers_remove(args) -> int:
    ok = peers_mod.remove(args.slug)
    print("removed" if ok else "not-found")
    return 0 if ok else 1


# ---- verdicts -----------------------------------------------------------


def cmd_verdict_list(_args) -> int:
    rows = verdicts_mod.list_verdicts()
    if not rows:
        print("(no verdicts yet)")
        return 0
    width = max(len(r.get("slug", "")) for r in rows)
    for r in rows:
        slug = r.get("slug", "")
        verdict = r.get("verdict", "?")
        status = r.get("status", "?")
        source = r.get("source", "?")
        print(f"  {slug:<{width}}  {verdict:<10}  {status:<12}  ← {source}")
    return 0


def cmd_verdict_candidates(_args) -> int:
    """Surface draft verdicts a scout pass left for review (the loop's open end)."""
    rows = verdicts_mod.list_candidates()
    if not rows:
        print("(no candidate verdicts awaiting review)")
        return 0
    width = max(len(r.get("slug", "")) for r in rows)
    print(
        f"{len(rows)} candidate verdict(s) awaiting review "
        f"(spindle verdict show <slug> after promoting):"
    )
    for r in rows:
        slug = r.get("slug", "")
        verdict = r.get("verdict", "?")
        source = r.get("source", "?")
        print(f"  {slug:<{width}}  {verdict:<10}  ← {source}")
    return 0


def cmd_verdict_show(args) -> int:
    rec = verdicts_mod.get(args.slug)
    if rec is None:
        print(f"no verdict {args.slug!r}", file=sys.stderr)
        return 1
    fm, body = rec
    for k, v in fm.items():
        print(f"  {k:<14} {v}")
    print()
    print(body.rstrip())
    return 0


def cmd_verdict_add(args) -> int:
    body = ""
    if args.body_file:
        body = Path(args.body_file).read_text()
    elif args.body:
        body = args.body
    p = verdicts_mod.write(
        slug=args.slug,
        source=args.source,
        url=args.url or "",
        verdict=args.verdict,
        status=args.status,
        body=body,
        chippable=getattr(args, "chippable", "") or "",
        chip_alias=getattr(args, "chip_alias", "") or "",
    )
    print(f"wrote {p}")
    return 0


# ---- ingest -------------------------------------------------------------


def _derive_project(
    row: ingest_mod.IngestRow, explicit_project: str | None
) -> str | None:
    """Derive the project name for a single ingest row.

    Priority:
      1. --project flag (caller-supplied explicit_project)
      2. context.cwd basename from the task itself (authoritative per-task source)
      3. First segment of task_id (e.g. "magpie-ajs-0.1" → "magpie"; last resort)

    Never uses the spindle tool's own cwd or the plan slug from the JSONL project field.
    """
    if explicit_project:
        return explicit_project
    ctx = row.payload.get("context") or {}
    cwd = ctx.get("cwd")
    if cwd:
        name = Path(cwd).name
        if name:
            return name
    # Last resort: task_id prefix only if it looks like a project slug
    tid = row.task_id
    if not tid.startswith("_anon_"):
        first = tid.split("-")[0]
        if first:
            return first
    return None


def cmd_ingest(args) -> int:
    path = Path(args.path)
    if not path.exists():
        print(f"no such file: {path}", file=sys.stderr)
        return 1
    try:
        rows = ingest_mod.parse_jsonl(path)
    except ValueError as e:
        print(f"parse error: {e}", file=sys.stderr)
        return 2

    if not rows:
        print("nothing to ingest (file empty)")
        return 0
    print(f"parsed {len(rows)} entries from {path}")

    # Idempotency: skip entries whose task_ids were successfully ingested before.
    # A sidecar file next to the JSONL tracks task_id → sink entry_id mappings.
    sidecar_path = path.with_name(path.stem + ".ingested.json")
    ingested: dict[str, str] = {}
    reimport = getattr(args, "reimport", False)
    if sidecar_path.exists() and not reimport:
        try:
            ingested = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"[spindle ingest] warn: could not read sidecar {sidecar_path}: {e}")
    if ingested:
        orig_count = len(rows)
        rows = [
            r
            for r in rows
            if r.task_id not in ingested or r.task_id.startswith("_anon_")
        ]
        n_skipped = orig_count - len(rows)
        if n_skipped:
            print(
                f"skipped {n_skipped} already-ingested entries (use --reimport to force)"
            )
        if not rows:
            print("nothing new to ingest")
            return 0

    # Resolve project per entry. spindle-itemize has historically written the
    # plan slug (e.g. "ai-journalism-scouting") into the project field, which
    # fragments downstream task views. Each task already carries the correct repo
    # in context.cwd — use that basename instead. See _derive_project for the full
    # priority order. Never use the spindle tool's own cwd.
    if not args.keep_project:
        rewritten = 0
        skipped_concept = 0
        for r in rows:
            if r.payload.get("concept"):
                skipped_concept += 1
                continue
            existing = r.payload.get("project")
            target_project = _derive_project(r, args.project)
            if target_project and existing != target_project:
                ctx = r.payload.setdefault("context", {})
                if existing and "plan_slug" not in ctx:
                    ctx["plan_slug"] = existing
                r.payload["project"] = target_project
                rewritten += 1
        if rewritten:
            print(
                f"rewrote project on {rewritten} entries "
                f"(original plan slug stashed in context.plan_slug)"
            )
        if skipped_concept:
            print(f"skipped {skipped_concept} concept entries (no project field)")

    try:
        result = ingest_mod.ingest(
            rows,
            task_url=args.task_url,
            dry_run=args.dry_run,
            strict=args.strict,
        )
    except RuntimeError as e:
        print(f"strict-mode abort: {e}", file=sys.stderr)
        return 3
    except ValueError as e:
        print(f"ingest error: {e}", file=sys.stderr)
        return 2

    summary = f"posted={result.posted} skipped={result.skipped} failed={result.failed}"
    print(summary)
    if result.errors:
        print("errors:")
        for line_no, msg in result.errors:
            print(f"  line {line_no}: {msg}")

    # Persist successful task_ids so a re-run without --reimport is a no-op.
    if not args.dry_run and result.posted > 0:
        new_ids = {
            tid: eid
            for tid, eid in result.id_map.items()
            if not tid.startswith("_anon_")
        }
        ingested.update(new_ids)
        try:
            sidecar_path.write_text(json.dumps(ingested, indent=2), encoding="utf-8")
        except OSError as e:
            print(f"[spindle ingest] warn: could not write sidecar {sidecar_path}: {e}")

    return 0 if result.failed == 0 else 4


# ---- doctrine -----------------------------------------------------------


def _load_doctrine_or_fail():
    try:
        return doctrine_mod.load()
    except FileNotFoundError:
        print("no doctrine.toml in the active distribution", file=sys.stderr)
        return None


def cmd_doctrine_show(_args) -> int:
    doc = _load_doctrine_or_fail()
    if doc is None:
        return 1
    print(f"doctrine {doc.coordinate()}")
    print(f"\npreferences ({len(doc.preferences)}):")
    for p in doc.preferences:
        print(f"  [{p.scope:<7}] {p.id}: {p.favor}  ›  over {p.over}")
    print(f"\nabsolutes ({len(doc.absolutes)}):")
    for a in doc.absolutes:
        print(f"  [{a.scope:<7}] {a.id} {a.mode}: {a.statement}")
    print(f"\nmeta-principles ({len(doc.meta_principles)}):")
    for m in doc.meta_principles:
        print(f"  {m.id}: {m.statement}")
    return 0


def cmd_doctrine_validate(_args) -> int:
    doc = _load_doctrine_or_fail()
    if doc is None:
        return 1
    problems = doctrine_mod.validate(doc)
    if not problems:
        print(
            f"doctrine {doc.coordinate()} OK "
            f"({len(doc.preferences)} preferences, {len(doc.absolutes)} absolutes, "
            f"{len(doc.meta_principles)} meta-principles)"
        )
        return 0
    print(
        f"doctrine {doc.coordinate()} has {len(problems)} problem(s):", file=sys.stderr
    )
    for prob in problems:
        print(f"  - {prob}", file=sys.stderr)
    return 1


# ---- appclass -----------------------------------------------------------


def cmd_appclass(args) -> int:
    """Classify a local repo's app-type (Path B) and print its app-class key."""
    repo = Path(args.path)
    if not repo.exists():
        print(f"no such path: {repo}", file=sys.stderr)
        return 1
    sig = appclass_mod.signal_from_repo(repo, registry_kind=args.kind)
    cls = appclass_mod.classify(sig)
    print(f"{cls.name}  [{cls.language}]")
    print(f"  app-class: {cls.cluster_key()}")
    print(f"  tags:      {', '.join(cls.tags)}")
    return 0


# ---- gate ---------------------------------------------------------------


def cmd_gate_file(args) -> int:
    """File a spindle:doctrine gate into the configured decision queue."""
    result = gates_mod.file_gate(
        crux=args.crux,
        proposed_diff=args.diff or "",
        pilot=args.pilot or "",
        source=args.source or "",
        dry_run=args.dry_run,
    )
    if "dry_run" in result:
        import json as _json

        print("[dry-run] would write doctrine gate:")
        print(_json.dumps(result["dry_run"], indent=2))
        return 0
    entry_id = result.get("id", "?")
    print(f"filed doctrine gate → {entry_id} ({result.get('path', 'configured sink')})")
    return 0


def cmd_gate_from_result(args) -> int:
    """Parse an adjudicate-pass result file and file the doctrine gate it contains."""
    result_file = Path(args.result)
    if not result_file.exists():
        print(f"no such file: {result_file}", file=sys.stderr)
        return 1
    result = gates_mod.file_from_result(result_file, dry_run=args.dry_run)
    if "error" in result:
        print(result["error"], file=sys.stderr)
        return 1
    if "dry_run" in result:
        import json as _json

        print("[dry-run] would write doctrine gate:")
        print(_json.dumps(result["dry_run"], indent=2))
        return 0
    print(
        f"filed doctrine gate → {result.get('id', '?')} ({result.get('path', 'configured sink')})"
    )
    return 0


def cmd_unbind(args) -> int:
    """Remove a surface's materialized skills."""
    repo = Path(args.repo).resolve()
    name = args.name or repo.name
    actions = binder_mod.unbind(name, repo, args.harness, dry_run=args.dry_run)
    blocked = [(n, a) for n, a in actions if a.startswith("skipped:")]
    if blocked:
        print(f"unbind blocked for {name!r} [{args.harness}]", file=sys.stderr)
        for skill, action in blocked:
            print(f"  {action:<28} {skill}", file=sys.stderr)
        return 2
    removed = [n for n, a in actions if a == "removed"]
    if not removed:
        print(f"nothing bound for {name!r} [{args.harness}]")
        return 0
    for n in removed:
        print(f"  removed {n}")
    print(
        f"unbound {len(removed)} skill(s) from {name!r}"
        + (" (dry-run)" if args.dry_run else "")
    )
    return 0


# ---- bind ---------------------------------------------------------------


def _bind_context(doc, *, no_render: bool):
    """Build the (provider, render_fn) the binder needs from the active dist."""
    specs = skills_mod.discover_skills()
    index = {s.name: s.skill_dir for s in specs}
    revisions = {}
    package_revisions = {}
    for spec in specs:
        if spec.package not in package_revisions:
            package_revisions[spec.package] = packages_mod.resolve_package_revision(
                spec.package
            )
        revision = package_revisions[spec.package]
        revisions[spec.name] = revision
    provider = channels_mod.fs_provider(index, package_revisions=revisions)
    render_fn = binder_mod.identity_render
    if not no_render:
        client = llm_mod.from_env()
        profiles = profiles_mod.load_profiles(llm_client=client)
        model_profiles = profiles_mod.load_model_profiles(llm_client=client)
        if profiles or model_profiles:
            render_fn = render_mod.make_render_fn(
                profiles, doc.coordinate(), model_profiles=model_profiles
            )
    return provider, render_fn


def cmd_bind(args) -> int:
    """Compose and materialize a surface's skills (channel binder).

    Builds the surface (app-class clusters from the repo), sources channels via the
    filesystem provider over the active distribution, resolves + lints + materializes
    into the repo's harness-native skills dir, and records a binding coordinate.
    """
    repo = Path(args.repo).resolve()
    if not repo.exists():
        print(f"no such repo path: {repo}", file=sys.stderr)
        return 1
    try:
        doc = doctrine_mod.load()
    except FileNotFoundError:
        print("no doctrine.toml in the active distribution", file=sys.stderr)
        return 1

    sig = appclass_mod.signal_from_repo(repo, registry_kind=args.kind)
    cls = appclass_mod.classify(sig)
    surface = channels_mod.Surface(
        name=args.name or repo.name,
        harness=args.harness,
        autonomy_mode=args.autonomy,
        clusters=(cls.cluster_key(),),
        model=args.model,
    )

    try:
        provider, render_fn = _bind_context(doc, no_render=args.no_render)
    except (ValueError, lifecycle_mod.LifecycleError) as exc:
        print(
            f"bind blocked: could not resolve exact package identity: {exc}",
            file=sys.stderr,
        )
        return 2
    result = binder_mod.bind(
        surface,
        repo,
        provider,
        doc,
        render=render_fn,
        force=args.force,
        dry_run=args.dry_run,
    )

    model_tag = f" · model:{surface.model}" if surface.model else ""
    print(
        f"surface {surface.name!r} [{surface.harness} · {surface.autonomy_mode}{model_tag}]  "
        f"app-class: {cls.cluster_key()}"
    )
    if not result.ok:
        print(
            f"BLOCKED — {len(result.problems)} coherence problem(s):", file=sys.stderr
        )
        for p in result.problems:
            print(f"  - {p}", file=sys.stderr)
        print("  (re-run with --force to override)", file=sys.stderr)
        return 1
    if result.composition and result.composition.shadows:
        for sh in result.composition.shadows:
            kind = "COLLISION" if sh.same_scope else "override"
            print(f"  {kind}: {sh.command} {sh.winner} ‹ {sh.loser}")
    for name, action in result.actions:
        print(f"  {action:<20} {name}")
    if result.composition:
        tiers: dict[str, int] = {}
        for s in result.composition.skills:
            if s.tier:
                tiers[s.tier] = tiers.get(s.tier, 0) + 1
        if tiers:
            print(
                "  P10 tiers: "
                + ", ".join(f"{t}={n}" for t, n in sorted(tiers.items()))
            )
        # Touchpoint A: advisory (never a bind failure) for chip-annotated skills
        # that show no guardrail/gate line. Purely informational.
        for note in chippability_mod.advise_composition(result.composition):
            print(f"  advisory: {note}")
        runtime_profiled = sorted(
            skill.name
            for skill in result.composition.skills
            if skill.source_dir
            and realization_mod.has_runtime_profiles(skill.source_dir)
        )
        if runtime_profiled:
            print(
                "  runtime-profiled: "
                + ", ".join(runtime_profiled)
                + " (installed once; realize per agent session)"
            )
    if result.composition is not None and not result.composition.skills:
        print(
            "warning: composition resolved 0 skills — the subscribed channels list "
            "skills but no installed package ships them (check `spindle package list`; "
            "wheel installs need a bundled spindle-package.toml)",
            file=sys.stderr,
        )
    if args.dry_run:
        print("(dry-run — nothing written)")
    else:
        print(f"bound at coordinate {result.coordinate}")
    return 0


# ---- realize ------------------------------------------------------------


def _resolve_skill_target(target: str) -> Path | None:
    path = Path(target).expanduser()
    if path.is_dir():
        return path.resolve()
    found = skills_mod.read_skill_metadata(target)
    return found[1].skill_dir.resolve() if found is not None else None


def cmd_realize(args) -> int:
    """Create one immutable skill realization for an explicit agent session."""
    skill_dir = _resolve_skill_target(args.skill)
    if skill_dir is None:
        print(
            f"no installed skill or skill directory found for {args.skill!r}",
            file=sys.stderr,
        )
        return 1
    session_id = args.session_id or os.environ.get("SPINDLE_SESSION_ID")
    if not session_id:
        print(
            "realize requires --session-id or SPINDLE_SESSION_ID; "
            "routing must be session-local",
            file=sys.stderr,
        )
        return 1
    harness = args.harness or os.environ.get("SPINDLE_HARNESS")
    if not harness:
        print(
            "realize requires --harness or SPINDLE_HARNESS",
            file=sys.stderr,
        )
        return 1
    requested_model = (
        args.requested_model or args.model or os.environ.get("SPINDLE_REQUESTED_MODEL")
    )
    served_model = (
        args.served_model or args.model or os.environ.get("SPINDLE_SERVED_MODEL")
    )
    try:
        session = realization_mod.SessionProfile(
            session_id=session_id,
            harness=harness,
            requested_model=requested_model,
            served_model=served_model,
            effort=args.effort or os.environ.get("SPINDLE_EFFORT"),
            role=args.role or os.environ.get("SPINDLE_AGENT_ROLE"),
            harness_build=args.harness_build or os.environ.get("SPINDLE_HARNESS_BUILD"),
            toolset_digest=args.toolset_digest
            or os.environ.get("SPINDLE_TOOLSET_DIGEST"),
            policy_digest=args.policy_digest or os.environ.get("SPINDLE_POLICY_DIGEST"),
            memory_policy=args.memory_policy or os.environ.get("SPINDLE_MEMORY_POLICY"),
        )
        result = realization_mod.realize_skill(skill_dir, session)
    except realization_mod.RealizationError as exc:
        print(f"realization blocked: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        profile = result.profile_id or "invariant-core"
        print(f"realized {result.skill!r} for session {session_id!r}")
        print(f"  resolution: {result.status} ({result.reason})")
        print(f"  profile:    {profile}")
        print(f"  path:       {result.path}")
        print(f"  receipt:    {result.receipt_path}")
    if args.strict and not result.tuned:
        print(
            "strict realization requires an evaluated matching profile",
            file=sys.stderr,
        )
        return 2
    return 0


# ---- local inspection and temporary leases -----------------------------


def _surface_lock_or_base(
    repo: Path, harness: str, surface_name: str | None
) -> tuple[lifecycle_mod.SurfaceLock | None, lifecycle_mod.SurfaceLock]:
    sid = lifecycle_mod.surface_id(repo, harness)
    current = lifecycle_mod.read_surface_lock(sid)
    base = current or lifecycle_mod.SurfaceLock(
        surface_id=sid,
        surface_name=surface_name or repo.name,
        repo_path=str(repo),
        harness=harness,
        binding_coordinate="lease-only/v1",
        projections=(),
    )
    if base.lease_ids:
        base, _active, _expired = leases_mod.effective_lock_at(base)
    return current, base


def _candidate_inventory(
    repo: Path, harness: str, lock: lifecycle_mod.SurfaceLock
) -> inventory_mod.EffectiveInventory:
    return inventory_mod.scan_effective_inventory(
        repo,
        harness,
        surface_name=lock.surface_name,
        lock=lock,
    )


def _resolve_candidate(
    reference: str, *, offline: bool = False
) -> tuple[intent_mod.LocalCandidate, sources_mod.SourceReceipt | None]:
    if not sources_mod.is_remote_reference(reference):
        return intent_mod.resolve_local_candidate(reference), None
    resolved = sources_mod.resolve_remote_candidate(reference, offline=offline)
    return resolved.candidate, resolved.source_receipt


def _preflight_options(args) -> dict:
    return {
        "allow_executable": bool(getattr(args, "allow_executable", False)),
        "allow_network": bool(getattr(args, "allow_network", False)),
        "allow_credentials": bool(getattr(args, "allow_credentials", False)),
        "allowed_tools": tuple(getattr(args, "allow_tool", ()) or ()),
        "attestations": trust_mod.load_attestations(
            tuple(getattr(args, "attestation", ()) or ())
        ),
    }


def _organization_policy(repo: Path) -> policy_mod.OrganizationPolicy | None:
    try:
        return policy_mod.load_policy(repo)
    except policy_mod.PolicyError as exc:
        raise lifecycle_mod.LifecycleError(str(exc)) from exc


def _lease_findings(
    inventory: inventory_mod.EffectiveInventory,
    projection: lifecycle_mod.ExpectedProjection,
    *,
    cleanup: bool = False,
    desired_lock: lifecycle_mod.SurfaceLock | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    blockers: list[str] = []
    warnings: list[str] = []
    decisions = (
        tuple(
            lifecycle_mod.ConflictDecisionStore().get(decision_id)
            for decision_id in desired_lock.conflict_decisions
        )
        if desired_lock is not None
        else ()
    )
    for entry in inventory.entries:
        detail = f"{entry.name} [{entry.scope}] {entry.reason}"
        if entry.path == projection.projection_path and entry.state in {
            inventory_mod.InventoryState.MISSING,
            inventory_mod.InventoryState.STALE_OWNED,
        }:
            continue
        if cleanup and entry.path != projection.projection_path:
            if entry.state is not inventory_mod.InventoryState.EXPECTED_OWNED:
                warnings.append(detail)
            continue
        if entry.state is inventory_mod.InventoryState.CONFLICTING and any(
            entry.path is not None
            and decision.matches(
                surface=inventory.surface_id,
                harness=inventory.harness,
                skill=entry.name,
                observed_path=entry.path,
                observed_digest=entry.content_digest,
            )
            for decision in decisions
        ):
            warnings.append("allowed exact conflict: " + detail)
            continue
        if entry in inventory.blocking_entries():
            blockers.append(detail)
        elif entry.state in {
            inventory_mod.InventoryState.FOREIGN,
            inventory_mod.InventoryState.OPAQUE,
            inventory_mod.InventoryState.DISABLED,
            inventory_mod.InventoryState.BROKEN,
        }:
            warnings.append(detail)
    return tuple(sorted(set(blockers))), tuple(sorted(set(warnings)))


def _prepare_lease_plan(
    reference: str,
    *,
    repo: Path,
    harness: str,
    surface_name: str | None,
    kind: str,
    expiry: datetime,
    posture: str,
    agents: tuple[str, ...],
    task_digest: str | None = None,
    now: datetime | None = None,
    offline: bool = False,
    preflight_options: dict | None = None,
    projection_name: str | None = None,
):
    moment = (now or datetime.now(tz=UTC)).astimezone(UTC).replace(microsecond=0)
    candidate, source_receipt = _resolve_candidate(reference, offline=offline)
    policy_mod.assert_candidate_allowed(
        _organization_policy(repo),
        provider=candidate.revision.source.provider,
        posture=posture,
    )
    trust_mod.assert_not_quarantined(candidate.revision.content_digest)
    current, base = _surface_lock_or_base(repo, harness, surface_name)
    package_cache = (
        paths_mod.package_cache_dir()
        / candidate.revision.content_digest.removeprefix("sha256:")
        / candidate.revision.name
    )
    cached_skill = candidate.cached_skill_path(package_cache)
    skill_digest = dict(candidate.revision.skill_digests)[candidate.skill]
    lease = lifecycle_mod.Lease(
        skill=candidate.skill,
        package_digest=candidate.revision.content_digest,
        skill_digest=skill_digest,
        source=candidate.revision.source,
        source_path=str(cached_skill.absolute()),
        surface_id=base.surface_id,
        harness=harness,
        kind=kind,
        scope="session" if kind == "session" else "repo",
        starts_at=leases_mod.iso_utc(moment),
        expires_at=leases_mod.iso_utc(expiry),
        posture=posture,
        agents=agents,
        renewal_policy="none" if kind == "session" else "manual",
        task_digest=task_digest,
    )
    projected_skill = projection_name or (
        f"{candidate.skill}--candidate-{skill_digest.removeprefix('sha256:')[:8]}"
        if kind == "update"
        else candidate.skill
    )
    projection = lifecycle_mod.ExpectedProjection(
        skill=projected_skill,
        projection_path=str(
            (materialize_mod.target_dir(repo, harness) / projected_skill).absolute()
        ),
        source_path=lease.source_path,
        source_digest=lease.skill_digest,
        package_digest=lease.package_digest,
        authority=f"lease:{lease.lease_id}",
    )
    proposed = leases_mod.lock_with_lease(base, lease, projection)
    inventory = _candidate_inventory(repo, harness, proposed)
    card = intent_mod.build_intent_card(
        candidate,
        effective_entries=(
            entry.to_dict()
            for entry in inventory.entries
            if not (
                entry.path == projection.projection_path
                and entry.state is inventory_mod.InventoryState.MISSING
            )
        ),
    )
    preflight = trust_mod.preflight_candidate(
        candidate,
        card,
        source_receipt=source_receipt,
        **(preflight_options or {}),
    )
    inventory_blockers, inventory_warnings = _lease_findings(
        inventory, projection, desired_lock=proposed
    )
    blockers = tuple(sorted({*inventory_blockers, *preflight.blockers}))
    warnings = tuple(sorted({*inventory_warnings, *preflight.warnings}))
    plan = leases_mod.LeasePlan(
        operation=(
            "try" if kind == "session" else "update-try" if kind == "update" else "borrow"
        ),
        lease=lease,
        current_lock_id=current.lock_id if current is not None else None,
        inventory_id=inventory.inventory_id,
        proposed_lock=proposed,
        projection=projection,
        blockers=blockers,
        warnings=warnings,
        source_receipt_id=(source_receipt.receipt_id if source_receipt else None),
        preflight_report_id=preflight.report_id,
    )
    return candidate, current, inventory, plan, card, preflight


def _assert_current_lease_plan(
    repo: Path,
    current: lifecycle_mod.SurfaceLock | None,
    inventory: inventory_mod.EffectiveInventory,
    plan: leases_mod.LeasePlan,
) -> None:
    observed_lock = lifecycle_mod.read_surface_lock(plan.proposed_lock.surface_id)
    expected_id = current.lock_id if current is not None else None
    observed_id = observed_lock.lock_id if observed_lock is not None else None
    if observed_id != expected_id:
        raise lifecycle_mod.LifecycleError(
            "surface lock changed after lease planning; re-plan before mutation"
        )
    observed_inventory = _candidate_inventory(
        repo, plan.proposed_lock.harness, plan.proposed_lock
    )
    if observed_inventory.inventory_id != inventory.inventory_id:
        raise lifecycle_mod.LifecycleError(
            "effective inventory changed after lease planning; re-plan before mutation"
        )


def _activation_for_lease(
    lease: lifecycle_mod.Lease,
    projection: lifecycle_mod.ExpectedProjection,
    startup: startup_mod.StartupResult,
    *,
    model: str | None = None,
) -> adapters_mod.ActivationReceipt:
    descriptor = adapters_mod.REFERENCE_ADAPTERS[lease.harness]
    requested_model = (
        adapters_mod.EvidenceFact(
            model, adapters_mod.EvidenceAuthority.REQUESTED, "trial CLI --model"
        )
        if model
        else None
    )
    configured_model = (
        adapters_mod.EvidenceFact(
            model, adapters_mod.EvidenceAuthority.CONFIGURED, "trial launch command"
        )
        if model
        else None
    )
    plan = adapters_mod.ProjectionPlan(
        session_id=f"lease:{lease.lease_id}",
        agent_id=next((agent for agent in lease.agents if agent != "*"), "parent"),
        harness=lease.harness,
        adapter_id=descriptor.id,
        mode=adapters_mod.ProjectionMode.SKILL_PATH,
        target=projection.projection_path,
        realization=adapters_mod.RealizationReference(
            skill=lease.skill,
            path=Path(lease.source_path),
            package_digest=lease.package_digest,
            realization_digest=lease.skill_digest,
            realization_receipt_id=lease.lease_id,
        ),
        requested_model=requested_model,
        configured_model=configured_model,
        configured_policy=adapters_mod.EvidenceFact(
            lease.posture,
            adapters_mod.EvidenceAuthority.CONFIGURED,
            f"lease {lease.lease_id}",
        ),
    )
    evidence = adapters_mod.ActivationEvidence(
        projection_loaded=adapters_mod.EvidenceFact(
            startup.receipt.decision in {"ok", "warn"},
            adapters_mod.EvidenceAuthority.OBSERVED,
            f"startup receipt {startup.receipt.receipt_id}",
        )
    )
    return adapters_mod.write_activation_receipt(plan, evidence)


def _apply_lease_plan(
    repo: Path,
    candidate: intent_mod.LocalCandidate,
    current: lifecycle_mod.SurfaceLock | None,
    inventory: inventory_mod.EffectiveInventory,
    plan: leases_mod.LeasePlan,
    preflight: trust_mod.PreflightReport,
    *,
    model: str | None = None,
) -> tuple[startup_mod.StartupResult, adapters_mod.ActivationReceipt]:
    if plan.blockers:
        raise lifecycle_mod.LifecycleError("; ".join(plan.blockers))
    cached_package = lifecycle_mod.cache_package(candidate.revision)
    cached_skill = candidate.cached_skill_path(cached_package)
    if str(cached_skill.absolute()) != plan.lease.source_path:
        raise lifecycle_mod.LifecycleError("cached lease path differs from its plan")
    if lifecycle_mod.digest_path(cached_skill) != plan.lease.skill_digest:
        raise lifecycle_mod.LifecycleError("cached lease skill differs from its plan")
    if preflight.report_id != plan.preflight_report_id:
        raise lifecycle_mod.LifecycleError("lease plan preflight identity changed")
    trust_mod.assert_not_quarantined(plan.lease.package_digest)
    trust_mod.write_preflight_report(preflight)

    with startup_mod.SurfaceMutex(plan.lease.surface_id):
        _assert_current_lease_plan(repo, current, inventory, plan)
        leases_mod.write_lease_plan(plan)
        leases_mod.LeaseStore().record(plan.lease)
        lifecycle_mod.write_surface_lock(plan.proposed_lock)

    startup = startup_mod.run_startup(
        repo,
        plan.lease.harness,
        reconcile_owned=True,
        surface_name=plan.proposed_lock.surface_name,
        event_source="lease-activate",
    )
    if startup.receipt.decision not in {"ok", "warn"}:
        raise lifecycle_mod.LifecycleError(
            f"lease desired state was recorded but activation is "
            f"{startup.receipt.decision}; release {plan.lease.lease_id} after diagnosis"
        )
    activation = _activation_for_lease(
        plan.lease, plan.projection, startup, model=model
    )
    return startup, activation


def _release_lease(
    lease_id: str,
    *,
    repo: Path,
    harness: str | None,
    dry_run: bool,
    event: str = "released",
) -> dict:
    lease = leases_mod.LeaseStore().get(lease_id)
    if harness is not None and harness != lease.harness:
        raise lifecycle_mod.LifecycleError(
            f"lease belongs to {lease.harness!r}, not {harness!r}"
        )
    if lifecycle_mod.surface_id(repo, lease.harness) != lease.surface_id:
        raise lifecycle_mod.LifecycleError("lease does not belong to this repository")
    current = lifecycle_mod.read_surface_lock(lease.surface_id)
    if current is None or lease_id not in current.lease_ids:
        return {
            "action": "already-released",
            "lease": lease.to_dict(),
            "event": None,
        }
    projections = tuple(
        projection
        for projection in current.projections
        if projection.authority == f"lease:{lease_id}"
    )
    if len(projections) != 1:
        raise lifecycle_mod.LifecycleError(
            "active lease must own exactly one expected projection"
        )
    proposed = leases_mod.lock_without_leases(current, (lease_id,))
    inventory = _candidate_inventory(repo, lease.harness, proposed)
    blockers, warnings = _lease_findings(
        inventory, projections[0], cleanup=True, desired_lock=proposed
    )
    plan = leases_mod.LeasePlan(
        operation="release" if event != "expired" else "expire",
        lease=lease,
        current_lock_id=current.lock_id,
        inventory_id=inventory.inventory_id,
        proposed_lock=proposed,
        projection=projections[0],
        blockers=blockers,
        warnings=warnings,
    )
    if dry_run:
        return {"action": "would-release", "plan": plan.to_dict(), "event": None}
    if plan.blockers:
        raise lifecycle_mod.LifecycleError("; ".join(plan.blockers))
    with startup_mod.SurfaceMutex(lease.surface_id):
        _assert_current_lease_plan(repo, current, inventory, plan)
        leases_mod.write_lease_plan(plan)
        lifecycle_mod.write_surface_lock(proposed)
    startup = startup_mod.run_startup(
        repo,
        lease.harness,
        reconcile_owned=True,
        surface_name=proposed.surface_name,
        event_source="lease-release",
    )
    lease_event = leases_mod.LeaseEvent(
        event=event,
        lease_id=lease_id,
        surface_id=lease.surface_id,
        observed_at=_now_iso(),
        previous_lock_id=current.lock_id,
        next_lock_id=proposed.lock_id,
        startup_receipt_id=startup.receipt.receipt_id,
        removed_projections=tuple(
            action.projection_path
            for action in startup.receipt.applied_actions
            if action.kind == "remove"
        ),
    )
    event_path = leases_mod.write_lease_event(lease_event)
    return {
        "action": "released",
        "lease": lease.to_dict(),
        "plan": plan.to_dict(),
        "startup": startup.receipt.to_dict(),
        "event": lease_event.to_dict(),
        "event_path": str(event_path),
    }


def cmd_inspect(args) -> int:
    repo = Path(args.repo).resolve()
    try:
        candidate, source_receipt = _resolve_candidate(
            args.reference, offline=getattr(args, "offline", False)
        )
        inventory = _effective_inventory(args)
        card = intent_mod.build_intent_card(
            candidate,
            requested_intent=args.intent,
            effective_entries=(entry.to_dict() for entry in inventory.entries),
        )
        preflight = trust_mod.preflight_candidate(
            candidate,
            card,
            source_receipt=source_receipt,
            **_preflight_options(args),
        )
        preflight_path = (
            trust_mod.write_preflight_report(preflight)
            if source_receipt is not None
            else None
        )
    except lifecycle_mod.LifecycleError as exc:
        print(f"inspection blocked: {exc}", file=sys.stderr)
        return 2
    payload = card.to_dict()
    payload["preflight"] = preflight.to_dict()
    payload["preflight_receipt_path"] = (
        str(preflight_path) if preflight_path is not None else None
    )
    payload["source_receipt"] = (
        source_receipt.to_dict() if source_receipt is not None else None
    )
    payload["surface"] = {
        "repo_path": str(repo),
        "harness": args.harness,
        "inventory_id": inventory.inventory_id,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        facts = card.package_facts
        fit = card.fit_analysis
        print(f"{facts['skill']}  {card.card_id}")
        print(f"  outcome:    {facts['outcome']}")
        print(f"  package:    {facts['provenance']['package_digest']}")
        print(
            f"  context:    {facts['context_cost']['estimated_tokens']} estimated token(s)"
        )
        print(f"  authority:  {facts['authority']['default_trial_posture']}")
        print(f"  composition: {fit['composition']}")
        print(f"  behavior:   {fit['behavioral_fit']} ({fit['basis']})")
    return 0


def cmd_borrow(args) -> int:
    repo = Path(args.repo).resolve()
    now = datetime.now(tz=UTC).replace(microsecond=0)
    try:
        expiry = leases_mod.parse_expiry(args.until, now=now)
        candidate, current, inventory, plan, card, preflight = _prepare_lease_plan(
            args.reference,
            repo=repo,
            harness=args.harness,
            surface_name=args.name,
            kind="borrow",
            expiry=expiry,
            posture=args.posture,
            agents=tuple(args.agent or ("*",)),
            now=now,
            offline=args.offline,
            preflight_options=_preflight_options(args),
        )
        if args.dry_run:
            payload = {
                "action": "would-borrow",
                "plan": plan.to_dict(),
                "intent_card": card.to_dict(),
                "preflight": preflight.to_dict(),
            }
        else:
            startup, activation = _apply_lease_plan(
                repo,
                candidate,
                current,
                inventory,
                plan,
                preflight,
                model=args.model,
            )
            payload = {
                "action": "borrowed",
                "plan": plan.to_dict(),
                "lease": plan.lease.to_dict(),
                "startup": startup.receipt.to_dict(),
                "activation_receipt_id": activation.receipt_id,
                "preflight_report_id": preflight.report_id,
            }
    except (lifecycle_mod.LifecycleError, adapters_mod.AdapterError) as exc:
        print(f"borrow blocked: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"lease action: {payload['action']}")
        print(f"  lease:   {plan.lease.lease_id}")
        print(f"  expires: {plan.lease.expires_at}")
        print(f"  posture: {plan.lease.posture}")
        for blocker in plan.blockers:
            print(f"  BLOCKED: {blocker}")
        for warning in plan.warnings:
            print(f"  warning: {warning}")
    return 2 if plan.blockers else 0


def cmd_release(args) -> int:
    try:
        payload = _release_lease(
            args.lease_id,
            repo=Path(args.repo).resolve(),
            harness=args.harness,
            dry_run=args.dry_run,
        )
    except lifecycle_mod.LifecycleError as exc:
        print(f"release blocked: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"lease action: {payload['action']}")
        print(f"  lease: {args.lease_id}")
        if payload.get("event"):
            print(f"  event: {payload['event']['event_id']}")
    return 0


def _trial_command(harness: str, skill: str, task: str, model: str | None) -> list[str]:
    if harness == "claude":
        prompt = f"Use /{skill} for this task.\n\n{task}"
        command = [
            "claude",
            "-p",
            "--no-session-persistence",
            "--permission-mode",
            "plan",
            "--allowedTools",
            "Read,Glob,Grep",
        ]
        if model:
            command.extend(("--model", model))
        return [*command, prompt]
    if harness == "codex":
        prompt = f"Use ${skill} for this task.\n\n{task}"
        command = ["codex", "-a", "never", "-s", "read-only"]
        if model:
            command.extend(("-m", model))
        return [*command, "exec", "--ephemeral", prompt]
    raise lifecycle_mod.LifecycleError(f"trial adapter unavailable for {harness!r}")


def cmd_try(args) -> int:
    repo = Path(args.repo).resolve()
    task_file = Path(args.task_file)
    try:
        task = task_file.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"trial blocked: cannot read task file: {exc}", file=sys.stderr)
        return 2
    task_digest = lifecycle_mod.content_id({"task": task})
    now = datetime.now(tz=UTC).replace(microsecond=0)
    try:
        lease_kind = getattr(args, "lease_kind", "session")
        candidate, current, inventory, plan, card, preflight = _prepare_lease_plan(
            args.reference,
            repo=repo,
            harness=args.harness,
            surface_name=args.name,
            kind=lease_kind,
            expiry=now + timedelta(hours=24),
            posture="read-only",
            agents=("parent",),
            task_digest=task_digest,
            now=now,
            offline=args.offline,
            preflight_options=_preflight_options(args),
            projection_name=getattr(args, "projection_name", None),
        )
        command = _trial_command(args.harness, plan.projection.skill, task, args.model)
        command_shape = tuple("<task>" if item == command[-1] else item for item in command)
        if args.dry_run:
            payload = {
                "action": "would-try",
                "plan": plan.to_dict(),
                "intent_card": card.to_dict(),
                "preflight": preflight.to_dict(),
                "command_shape": list(command_shape),
            }
            result_code = 2 if plan.blockers else 0
        else:
            startup, activation = _apply_lease_plan(
                repo,
                candidate,
                current,
                inventory,
                plan,
                preflight,
                model=args.model,
            )
            completed_code = 127
            stdout = ""
            stderr = ""
            cleanup: dict | None = None
            try:
                completed = subprocess.run(
                    command,
                    cwd=repo,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                completed_code = completed.returncode
                stdout = completed.stdout or ""
                stderr = completed.stderr or ""
            except OSError as exc:
                print(f"trial harness failed to launch: {exc}", file=sys.stderr)
                stderr = str(exc)
            finally:
                cleanup = _release_lease(
                    plan.lease.lease_id,
                    repo=repo,
                    harness=args.harness,
                    dry_run=False,
                    event="trial-cleanup",
                )
            event_payload = cleanup.get("event") if cleanup else None
            receipt = leases_mod.TrialRunReceipt(
                lease_id=plan.lease.lease_id,
                harness=args.harness,
                task_digest=task_digest,
                command_shape=command_shape,
                exit_code=completed_code,
                startup_receipt_id=startup.receipt.receipt_id,
                activation_receipt_id=activation.receipt_id,
                cleanup_event_id=(
                    str(event_payload["event_id"])
                    if isinstance(event_payload, dict)
                    else None
                ),
                stdout_digest=lifecycle_mod.content_id({"stdout": stdout}),
                stderr_digest=lifecycle_mod.content_id({"stderr": stderr}),
            )
            receipt_path = leases_mod.write_trial_run_receipt(receipt)
            payload = {
                "action": "tried",
                "lease": plan.lease.to_dict(),
                "plan": plan.to_dict(),
                "preflight_report_id": preflight.report_id,
                "startup_receipt_id": startup.receipt.receipt_id,
                "activation_receipt_id": activation.receipt_id,
                "cleanup": cleanup,
                "run_receipt": receipt.to_dict(),
                "run_receipt_path": str(receipt_path),
            }
            result_code = completed_code
    except (
        lifecycle_mod.LifecycleError,
        adapters_mod.AdapterError,
        realization_mod.RealizationError,
    ) as exc:
        print(f"trial blocked: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.dry_run:
        print(f"trial action: {payload['action']}")
        print(f"  lease:   {plan.lease.lease_id}")
        print(f"  posture: {plan.lease.posture}")
    else:
        if stdout:
            print(stdout, end="" if stdout.endswith("\n") else "\n")
        if stderr:
            print(stderr, file=sys.stderr, end="" if stderr.endswith("\n") else "\n")
        print(f"trial receipt: {payload['run_receipt']['receipt_id']}")
        print(f"temporary lease released: {plan.lease.lease_id}")
    return result_code


def _quarantine_package_digest(value: str, *, offline: bool) -> str:
    if re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        return value
    candidate, _receipt = _resolve_candidate(value, offline=offline)
    return candidate.revision.content_digest


def cmd_source_quarantine(args) -> int:
    try:
        package_digest = _quarantine_package_digest(args.package, offline=args.offline)
        event = trust_mod.set_quarantine(
            package_digest,
            quarantined=args.source_action == "quarantine",
            reason=args.reason,
            actor=args.actor or os.environ.get("USER", "user"),
            dry_run=args.dry_run,
        )
    except lifecycle_mod.LifecycleError as exc:
        print(f"source policy blocked: {exc}", file=sys.stderr)
        return 2
    payload = {
        "action": "would-record" if args.dry_run else "recorded",
        "event": event.to_dict(),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['action']}: {event.action} {event.package_digest}")
        print(f"  event: {event.event_id}")
    return 0


def cmd_source_status(args) -> int:
    try:
        package_digest = _quarantine_package_digest(args.package, offline=args.offline)
        status = trust_mod.quarantine_status(package_digest)
    except lifecycle_mod.LifecycleError as exc:
        print(f"source status blocked: {exc}", file=sys.stderr)
        return 2
    payload = {
        "package_digest": package_digest,
        "status": status or {"status": "available", "event_id": None, "reason": None},
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{package_digest}  {payload['status']['status']}")
        if payload["status"].get("event_id"):
            print(f"  event:  {payload['status']['event_id']}")
            print(f"  reason: {payload['status']['reason']}")
    return 0


# ---- durable adoption and maintenance ----------------------------------


def _read_source_receipt(receipt_id: str | None) -> sources_mod.SourceReceipt | None:
    if receipt_id is None:
        return None
    target = paths_mod.source_receipts_dir() / f"{receipt_id.removeprefix('sha256:')}.json"
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise lifecycle_mod.LifecycleError(
            f"invalid source receipt {receipt_id}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise lifecycle_mod.LifecycleError("source receipt must be an object")
    receipt = sources_mod.SourceReceipt.from_dict(raw)
    if receipt.receipt_id != receipt_id or target.stem != receipt_id.removeprefix(
        "sha256:"
    ):
        raise lifecycle_mod.LifecycleError("source receipt identity mismatch")
    return receipt


def _default_update_reference(
    lease: lifecycle_mod.Lease,
    source_receipt: sources_mod.SourceReceipt | None,
) -> str:
    if source_receipt is None or source_receipt.requested_revision == source_receipt.resolved_commit:
        return "manual"
    prefix = "git:" if Path(source_receipt.locator).is_absolute() else "git+"
    return (
        f"{prefix}{source_receipt.locator}@{source_receipt.requested_revision}"
        f"#{lease.skill}"
    )


def _lease_cache_coordinate(lease: lifecycle_mod.Lease) -> tuple[str, str]:
    package_root = (
        paths_mod.package_cache_dir()
        / lease.package_digest.removeprefix("sha256:")
    ).resolve()
    source = Path(lease.source_path).resolve()
    try:
        relative = source.relative_to(package_root)
    except ValueError as exc:
        raise lifecycle_mod.LifecycleError(
            "lease source path is outside its content-addressed package cache"
        ) from exc
    if not relative.parts:
        raise lifecycle_mod.LifecycleError("lease source path does not name a package")
    package_name = relative.parts[0]
    skill_subpath = Path(*relative.parts[1:]).as_posix() if len(relative.parts) > 1 else "."
    return package_name, skill_subpath


def _active_adoption(
    lock: lifecycle_mod.SurfaceLock, skill: str
) -> maintenance_mod.AdoptionRecord | None:
    matches = [
        record
        for record in maintenance_mod.active_adoptions(lock)
        if record.skill == skill
    ]
    if len(matches) > 1:
        raise lifecycle_mod.LifecycleError(
            f"surface has multiple active adoption records for {skill!r}"
        )
    return matches[0] if matches else None


def _adoption_from_lease(args, lease: lifecycle_mod.Lease):
    creation = maintenance_mod.find_lease_plan_facts(lease.lease_id)
    trial = maintenance_mod.find_successful_trial(lease.lease_id)
    activation_id = trial.get("activation_receipt_id")
    if not isinstance(activation_id, str) or not activation_id:
        raise lifecycle_mod.LifecycleError(
            "successful trial lacks an activation receipt and cannot be adopted"
        )
    source_receipt_id = creation.get("source_receipt_id")
    source_receipt = _read_source_receipt(
        str(source_receipt_id) if source_receipt_id is not None else None
    )
    package_name, skill_subpath = _lease_cache_coordinate(lease)
    update_reference = args.update_channel or _default_update_reference(
        lease, source_receipt
    )
    repo = Path(args.repo).resolve()
    current, base = _surface_lock_or_base(repo, lease.harness, args.name)
    if base.surface_id != lease.surface_id:
        raise lifecycle_mod.LifecycleError("lease does not belong to this surface")
    incumbent = _active_adoption(base, lease.skill)
    if incumbent is not None and lease.kind != "update":
        raise lifecycle_mod.LifecycleError(
            f"{lease.skill!r} is already adopted; use an update trial"
        )
    if incumbent is None and lease.kind == "update":
        raise lifecycle_mod.LifecycleError("update trial has no active incumbent")
    if incumbent is not None and incumbent.package_digest == lease.package_digest:
        raise lifecycle_mod.LifecycleError("update candidate is byte-identical to incumbent")
    record = maintenance_mod.AdoptionRecord(
        skill=lease.skill,
        package_name=package_name,
        package_digest=lease.package_digest,
        skill_digest=lease.skill_digest,
        skill_subpath=skill_subpath,
        source=lease.source,
        surface_id=lease.surface_id,
        harness=lease.harness,
        scope=args.scope,
        owner=args.owner or os.environ.get("USER", "user"),
        adopted_at=_now_iso(),
        update_reference=update_reference,
        authority_ceiling=args.authority_ceiling or lease.posture,
        retirement_policy=args.retirement_policy,
        lease_id=lease.lease_id,
        trial_run_receipt_id=str(trial["receipt_id"]),
        activation_receipt_id=activation_id,
        preflight_report_id=(
            str(creation["preflight_report_id"])
            if creation.get("preflight_report_id") is not None
            else None
        ),
        source_receipt_id=(
            str(source_receipt_id) if source_receipt_id is not None else None
        ),
        previous_adoption_id=(incumbent.adoption_id if incumbent else None),
        evidence_coordinate=maintenance_mod.activation_coordinate(activation_id),
        evaluation_claim_ids=tuple(args.evaluation_claim or ()),
    )
    policy_mod.assert_adoption_allowed(
        _organization_policy(repo),
        record,
        harness_build=args.harness_build,
    )
    trust_mod.assert_not_quarantined(record.package_digest)
    projection = maintenance_mod.projection_for_adoption(
        record, materialize_mod.target_dir(repo, lease.harness) / lease.skill
    )
    proposed = maintenance_mod.lock_with_adoption(
        base,
        record,
        projection,
        remove_lease_id=(lease.lease_id if lease.lease_id in base.lease_ids else None),
        replace_adoption_id=(incumbent.adoption_id if incumbent else None),
    )
    inventory = _candidate_inventory(repo, lease.harness, proposed)
    blockers, warnings = _lease_findings(
        inventory, projection, desired_lock=proposed
    )
    operation = "update-promote" if incumbent else "adopt"
    plan = maintenance_mod.AdoptionPlan(
        operation=operation,
        skill=lease.skill,
        surface_id=lease.surface_id,
        current_lock_id=base.lock_id,
        proposed_lock=proposed,
        adoption=record,
        affected_adoption_id=incumbent.adoption_id if incumbent else None,
        evidence_receipt_id=str(trial["receipt_id"]),
        blockers=blockers,
        warnings=warnings,
    )
    return repo, current, base, inventory, plan, record


def _apply_adoption_plan(
    repo: Path,
    current: lifecycle_mod.SurfaceLock | None,
    base: lifecycle_mod.SurfaceLock,
    inventory: inventory_mod.EffectiveInventory,
    plan: maintenance_mod.AdoptionPlan,
    record: maintenance_mod.AdoptionRecord,
    *,
    reason: str,
    actor: str,
) -> tuple[startup_mod.StartupResult, maintenance_mod.MaintenanceEvent]:
    if plan.blockers:
        raise lifecycle_mod.LifecycleError("; ".join(plan.blockers))
    trust_mod.assert_not_quarantined(record.package_digest)
    with startup_mod.SurfaceMutex(record.surface_id):
        observed = lifecycle_mod.read_surface_lock(record.surface_id)
        if (observed.lock_id if observed else None) != (
            current.lock_id if current else None
        ):
            raise lifecycle_mod.LifecycleError(
                "surface lock changed after adoption planning; re-plan"
            )
        observed_inventory = _candidate_inventory(repo, record.harness, plan.proposed_lock)
        if observed_inventory.inventory_id != inventory.inventory_id:
            raise lifecycle_mod.LifecycleError(
                "effective inventory changed after adoption planning; re-plan"
            )
        maintenance_mod.AdoptionStore().record(record)
        maintenance_mod.write_adoption_plan(plan)
        lifecycle_mod.write_surface_lock(plan.proposed_lock)
    startup = startup_mod.run_startup(
        repo,
        record.harness,
        reconcile_owned=True,
        surface_name=plan.proposed_lock.surface_name,
        event_source="adoption-apply",
    )
    if startup.receipt.decision not in {"ok", "warn"}:
        raise lifecycle_mod.LifecycleError(
            f"adoption desired state was recorded but startup is {startup.receipt.decision}"
        )
    event = maintenance_mod.MaintenanceEvent(
        operation=plan.operation,
        skill=record.skill,
        surface_id=record.surface_id,
        adoption_id=record.adoption_id,
        previous_adoption_id=record.previous_adoption_id,
        prior_lock_id=base.lock_id,
        next_lock_id=plan.proposed_lock.lock_id,
        reason=reason,
        actor=actor,
        observed_at=_now_iso(),
        startup_receipt_id=startup.receipt.receipt_id,
    )
    maintenance_mod.write_maintenance_event(event)
    maintenance_mod.record_status(event, "active")
    return startup, event


def cmd_adopt(args) -> int:
    try:
        lease = leases_mod.LeaseStore().get(args.lease_id)
        repo, current, base, inventory, plan, record = _adoption_from_lease(args, lease)
        if args.dry_run:
            payload = {"action": "would-adopt", "plan": plan.to_dict()}
        else:
            actor = args.owner or os.environ.get("USER", "user")
            startup, event = _apply_adoption_plan(
                repo,
                current,
                base,
                inventory,
                plan,
                record,
                reason=args.reason,
                actor=actor,
            )
            payload = {
                "action": "updated" if plan.operation == "update-promote" else "adopted",
                "adoption": record.to_dict(),
                "plan": plan.to_dict(),
                "event": event.to_dict(),
                "startup": startup.receipt.to_dict(),
            }
    except (
        lifecycle_mod.LifecycleError,
        adapters_mod.AdapterError,
    ) as exc:
        print(f"adoption blocked: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"adoption action: {payload['action']}")
        print(f"  adoption: {record.adoption_id}")
        print(f"  lock:     {plan.proposed_lock.lock_id}")
        for blocker in plan.blockers:
            print(f"  BLOCKED: {blocker}")
        for warning in plan.warnings:
            print(f"  warning: {warning}")
    return 2 if plan.blockers else 0


def _maintenance_record_for_skill(
    repo: Path, harness: str, skill: str
) -> tuple[lifecycle_mod.SurfaceLock, maintenance_mod.AdoptionRecord, str]:
    sid = lifecycle_mod.surface_id(repo, harness)
    lock = lifecycle_mod.read_surface_lock(sid)
    if lock is None:
        raise lifecycle_mod.LifecycleError("surface has no desired-state lock")
    active = _active_adoption(lock, skill)
    if active is not None:
        status = maintenance_mod.current_status(sid, skill)
        return lock, active, str((status or {}).get("status", "active"))
    status = maintenance_mod.current_status(sid, skill)
    if status is None or not status.get("adoption_id"):
        raise lifecycle_mod.LifecycleError(f"{skill!r} has no adoption on this surface")
    record = maintenance_mod.AdoptionStore().get(str(status["adoption_id"]))
    return lock, record, str(status.get("status", "unknown"))


def _prepare_maintenance_transition(args):
    repo = Path(args.repo).resolve()
    lock, current_record, status = _maintenance_record_for_skill(
        repo, args.harness, args.skill
    )
    operation = args.operation
    target_record = current_record
    if operation == "rollback":
        if current_record.previous_adoption_id is None:
            raise lifecycle_mod.LifecycleError("adoption has no prior revision to restore")
        target_record = maintenance_mod.AdoptionStore().get(
            current_record.previous_adoption_id
        )
        if current_record.adoption_id not in lock.adoption_ids:
            raise lifecycle_mod.LifecycleError("only an active adoption can be rolled back")
        projection = maintenance_mod.projection_for_adoption(
            target_record,
            materialize_mod.target_dir(repo, args.harness) / args.skill,
        )
        proposed = maintenance_mod.lock_with_adoption(
            lock,
            target_record,
            projection,
            replace_adoption_id=current_record.adoption_id,
        )
    elif operation in {"disable", "retire"}:
        if status == "retired":
            raise lifecycle_mod.LifecycleError("adoption is already retired")
        proposed = (
            maintenance_mod.lock_without_adoption(lock, current_record.adoption_id)
            if current_record.adoption_id in lock.adoption_ids
            else lock
        )
    elif operation == "enable":
        if status != "disabled":
            raise lifecycle_mod.LifecycleError("only a disabled adoption can be enabled")
        trust_mod.assert_not_quarantined(current_record.package_digest)
        projection = maintenance_mod.projection_for_adoption(
            current_record,
            materialize_mod.target_dir(repo, args.harness) / args.skill,
        )
        proposed = maintenance_mod.lock_with_adoption(lock, current_record, projection)
    elif operation == "deprecate":
        if status == "retired":
            raise lifecycle_mod.LifecycleError("retired adoption cannot be deprecated")
        proposed = lock
    else:
        raise lifecycle_mod.LifecycleError(f"unsupported maintenance action: {operation}")
    inventory = _candidate_inventory(repo, args.harness, proposed)
    projection = next(
        (
            item
            for item in (lock.projections + proposed.projections)
            if item.skill == args.skill
        ),
        lifecycle_mod.ExpectedProjection(
            skill=args.skill,
            projection_path=str(
                (materialize_mod.target_dir(repo, args.harness) / args.skill).absolute()
            ),
            source_path=str(target_record.cached_skill_path().absolute()),
            source_digest=target_record.skill_digest,
            package_digest=target_record.package_digest,
            authority=f"adoption:{target_record.adoption_id}",
        ),
    )
    blockers, warnings = _lease_findings(
        inventory,
        projection,
        cleanup=operation in {"disable", "retire"},
        desired_lock=proposed,
    )
    plan = maintenance_mod.AdoptionPlan(
        operation=operation,
        skill=args.skill,
        surface_id=lock.surface_id,
        current_lock_id=lock.lock_id,
        proposed_lock=proposed,
        adoption=target_record if operation in {"rollback", "enable"} else None,
        affected_adoption_id=current_record.adoption_id,
        evidence_receipt_id=None,
        blockers=blockers,
        warnings=warnings,
    )
    return repo, lock, inventory, plan, current_record, target_record


def _apply_maintenance_transition(
    repo: Path,
    current: lifecycle_mod.SurfaceLock,
    inventory: inventory_mod.EffectiveInventory,
    plan: maintenance_mod.AdoptionPlan,
    current_record: maintenance_mod.AdoptionRecord,
    target_record: maintenance_mod.AdoptionRecord,
    *,
    reason: str,
    actor: str,
):
    if plan.blockers:
        raise lifecycle_mod.LifecycleError("; ".join(plan.blockers))
    with startup_mod.SurfaceMutex(current.surface_id):
        observed = lifecycle_mod.read_surface_lock(current.surface_id)
        if observed is None or observed.lock_id != current.lock_id:
            raise lifecycle_mod.LifecycleError(
                "surface lock changed after maintenance planning; re-plan"
            )
        observed_inventory = _candidate_inventory(repo, current.harness, plan.proposed_lock)
        if observed_inventory.inventory_id != inventory.inventory_id:
            raise lifecycle_mod.LifecycleError(
                "effective inventory changed after maintenance planning; re-plan"
            )
        maintenance_mod.write_adoption_plan(plan)
        if plan.proposed_lock.lock_id != current.lock_id:
            lifecycle_mod.write_surface_lock(plan.proposed_lock)
    startup = None
    if plan.proposed_lock.lock_id != current.lock_id:
        startup = startup_mod.run_startup(
            repo,
            current.harness,
            reconcile_owned=True,
            surface_name=current.surface_name,
            event_source=f"adoption-{plan.operation}",
        )
        if startup.receipt.decision not in {"ok", "warn"}:
            raise lifecycle_mod.LifecycleError(
                f"maintenance desired state changed but startup is {startup.receipt.decision}"
            )
    event = maintenance_mod.MaintenanceEvent(
        operation=plan.operation,
        skill=plan.skill,
        surface_id=current.surface_id,
        adoption_id=target_record.adoption_id,
        previous_adoption_id=(
            current_record.adoption_id
            if plan.operation == "rollback"
            else current_record.previous_adoption_id
        ),
        prior_lock_id=current.lock_id,
        next_lock_id=plan.proposed_lock.lock_id,
        reason=reason,
        actor=actor,
        observed_at=_now_iso(),
        startup_receipt_id=(startup.receipt.receipt_id if startup else None),
    )
    maintenance_mod.write_maintenance_event(event)
    next_status = {
        "rollback": "active",
        "disable": "disabled",
        "enable": "active",
        "deprecate": "deprecated",
        "retire": "retired",
    }[plan.operation]
    maintenance_mod.record_status(event, next_status)
    return event, startup


def cmd_maintenance_action(args) -> int:
    try:
        repo, current, inventory, plan, incumbent, target = (
            _prepare_maintenance_transition(args)
        )
        if args.dry_run:
            payload = {"action": f"would-{args.operation}", "plan": plan.to_dict()}
        else:
            actor = args.actor or os.environ.get("USER", "user")
            event, startup = _apply_maintenance_transition(
                repo,
                current,
                inventory,
                plan,
                incumbent,
                target,
                reason=args.reason,
                actor=actor,
            )
            payload = {
                "action": args.operation,
                "plan": plan.to_dict(),
                "event": event.to_dict(),
                "startup": startup.receipt.to_dict() if startup else None,
            }
    except lifecycle_mod.LifecycleError as exc:
        print(f"{args.operation} blocked: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"maintenance action: {payload['action']}")
        print(f"  skill: {args.skill}")
        print(f"  lock:  {plan.proposed_lock.lock_id}")
    return 2 if plan.blockers else 0


def cmd_health(args) -> int:
    repo = Path(args.repo).resolve()
    try:
        sid = lifecycle_mod.surface_id(repo, args.harness)
        lock = lifecycle_mod.read_surface_lock(sid)
        inventory = inventory_mod.scan_effective_inventory(
            repo,
            args.harness,
            surface_name=args.name or repo.name,
            lock=lock,
        )
        coordinate = tuple(
            (key, value)
            for key, value in (
                ("harness", args.harness),
                ("model", args.model),
                ("harness_build", args.harness_build),
                ("toolset_digest", args.toolset_digest),
                ("policy_digest", args.policy_digest),
                ("source_revision", args.source_revision),
                ("package_digest", args.package_digest),
            )
            if value
        )
        inventory_findings = tuple(
            (entry.name, f"inventory-{entry.state.value}")
            for entry in inventory.entries
            if entry.state is not inventory_mod.InventoryState.EXPECTED_OWNED
            and entry.name
        )
        report = maintenance_mod.health_report(
            lock,
            surface_id=sid,
            inventory_id=inventory.inventory_id,
            current_coordinate=coordinate,
            inventory_findings=inventory_findings,
        )
    except lifecycle_mod.LifecycleError as exc:
        print(f"health blocked: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"health {report.report_id}  inventory {report.inventory_id}")
        if not report.skills:
            print("  (no current or retained adoptions)")
        for row in report.skills:
            findings = ", ".join(row["findings"]) or "healthy"
            print(f"  {row['skill']:<24} {row['status']:<10} {findings}")
    return 0


def _update_candidate_payload(args, record: maintenance_mod.AdoptionRecord):
    if record.update_reference == "manual":
        raise lifecycle_mod.LifecycleError(
            f"{record.skill!r} has a manual update channel; supply a new trial explicitly"
        )
    candidate, source_receipt = _resolve_candidate(
        record.update_reference, offline=args.offline
    )
    if candidate.skill != record.skill:
        raise lifecycle_mod.LifecycleError("update channel resolved a different skill")
    repo = Path(args.repo).resolve()
    sid = lifecycle_mod.surface_id(repo, record.harness)
    lock = lifecycle_mod.read_surface_lock(sid)
    inventory = inventory_mod.scan_effective_inventory(
        repo,
        record.harness,
        surface_name=args.name or repo.name,
        lock=lock,
    )
    card = intent_mod.build_intent_card(
        candidate,
        effective_entries=(entry.to_dict() for entry in inventory.entries),
    )
    preflight = trust_mod.preflight_candidate(
        candidate,
        card,
        source_receipt=source_receipt,
        **_preflight_options(args),
    )
    if source_receipt is not None:
        trust_mod.write_preflight_report(preflight)
    changed = candidate.revision.content_digest != record.package_digest
    return {
        "skill": record.skill,
        "adoption_id": record.adoption_id,
        "current": {
            "package_digest": record.package_digest,
            "skill_digest": record.skill_digest,
            "source_revision": record.source.revision,
            "evaluation_claim_ids": list(record.evaluation_claim_ids),
        },
        "candidate": {
            "reference": record.update_reference,
            "package_digest": candidate.revision.content_digest,
            "skill_digest": dict(candidate.revision.skill_digests)[candidate.skill],
            "source_revision": candidate.revision.source.revision,
            "source_receipt_id": source_receipt.receipt_id if source_receipt else None,
            "preflight_report_id": preflight.report_id,
            "blockers": list(preflight.blockers),
            "warnings": list(preflight.warnings),
            "evaluation_claim_ids": [],
        },
        "changed": changed,
        "evaluation_inheritance": "none",
    }


def cmd_update_plan(args) -> int:
    repo = Path(args.repo).resolve()
    try:
        sid = lifecycle_mod.surface_id(repo, args.harness)
        lock = lifecycle_mod.read_surface_lock(sid)
        if lock is None:
            raise lifecycle_mod.LifecycleError("surface has no desired-state lock")
        records = maintenance_mod.active_adoptions(lock)
        rows = [_update_candidate_payload(args, record) for record in records]
    except lifecycle_mod.LifecycleError as exc:
        print(f"update plan blocked: {exc}", file=sys.stderr)
        return 2
    payload = {
        "surface_id": sid,
        "lock_id": lock.lock_id,
        "updates": rows,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        if not rows:
            print("(no active adoptions)")
        for row in rows:
            state = "candidate" if row["changed"] else "current"
            print(f"  {row['skill']:<24} {state}  {row['candidate']['source_revision']}")
            for blocker in row["candidate"]["blockers"]:
                print(f"    BLOCKED: {blocker}")
    return 2 if any(row["candidate"]["blockers"] for row in rows) else 0


def cmd_update_try(args) -> int:
    repo = Path(args.repo).resolve()
    try:
        lock, record, status = _maintenance_record_for_skill(
            repo, args.harness, args.skill
        )
        del lock
        if status not in {"active", "deprecated"}:
            raise lifecycle_mod.LifecycleError("update trial requires an active adoption")
        if record.update_reference == "manual":
            raise lifecycle_mod.LifecycleError("adoption has no refreshable update channel")
        candidate, _receipt = _resolve_candidate(
            record.update_reference, offline=args.offline
        )
        if candidate.revision.content_digest == record.package_digest:
            raise lifecycle_mod.LifecycleError("update channel still resolves the incumbent bytes")
    except lifecycle_mod.LifecycleError as exc:
        print(f"update trial blocked: {exc}", file=sys.stderr)
        return 2
    args.reference = record.update_reference
    args.lease_kind = "update"
    args.projection_name = None
    # The first resolution pinned and verified the candidate. Reuse those exact
    # cached bytes when cmd_try builds its lease instead of fetching a mutable
    # update channel twice in one operation.
    args.offline = True
    return cmd_try(args)


def cmd_custody_path(args) -> int:
    try:
        _lock, record, _status = _maintenance_record_for_skill(
            Path(args.repo).resolve(), args.harness, args.skill
        )
    except lifecycle_mod.LifecycleError as exc:
        print(f"{args.path_action} plan blocked: {exc}", file=sys.stderr)
        return 2
    if args.path_action == "vendor":
        payload = {
            "action": "vendor-plan",
            "skill": record.skill,
            "source_package": str(record.cached_package_path()),
            "package_digest": record.package_digest,
            "destination": str(Path(args.destination).resolve()),
            "mutation": "none",
            "next": "copy into a reviewed local package, inspect it, then try before adoption",
        }
    else:
        payload = {
            "action": "distill-plan",
            "skill": record.skill,
            "package_digest": record.package_digest,
            "skill_digest": record.skill_digest,
            "mutation": "none",
            "next": "run named-arm ablations and stage the minimal residue as a new trial revision",
        }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['action']}: {record.skill}")
        print(f"  next: {payload['next']}")
    return 0


def _capability_requirements(values):
    requirements: list[conformance_mod.CapabilityRequirement] = []
    for value in values or ():
        name, separator, status = value.partition(":")
        requirements.append(
            conformance_mod.CapabilityRequirement(
                name=name,
                required_status=status if separator else "pass",
            )
        )
    return tuple(requirements)


def cmd_adapter_matrix(args) -> int:
    try:
        observation = (
            conformance_mod.load_observation(args.observation)
            if args.observation
            else None
        )
        matrix = conformance_mod.capability_matrix(
            args.harness,
            harness_build=args.build,
            observation=observation,
        )
        requirements = _capability_requirements(args.require)
        negotiation = (
            conformance_mod.negotiate(matrix, requirements)
            if requirements
            else None
        )
    except conformance_mod.ConformanceError as exc:
        print(f"adapter matrix blocked: {exc}", file=sys.stderr)
        return 2
    payload = {"matrix": matrix, "negotiation": negotiation}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"adapter: {matrix['adapter_id']} @ {matrix['harness_build']}")
        for name, capability in matrix["capabilities"].items():
            print(f"  {name:<24} {capability['status']}")
        if negotiation:
            print(f"negotiation: {negotiation['decision']}")
    return 2 if negotiation and not negotiation["compatible"] else 0


def cmd_adapter_certify(args) -> int:
    try:
        observation = conformance_mod.load_observation(args.observation)
        receipt, path = conformance_mod.certify(observation, dry_run=args.dry_run)
    except conformance_mod.ConformanceError as exc:
        print(f"adapter certification blocked: {exc}", file=sys.stderr)
        return 2
    payload = {"certification": receipt, "path": str(path) if path else None}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"adapter certification: {receipt['status']}")
        print(f"  id:    {receipt['certification_id']}")
        print(f"  build: {receipt['harness']} {receipt['harness_build']}")
        for gap in receipt["capability_gaps"]:
            print(f"  gap: {gap}")
    return 0 if receipt["status"] == "certified" else 2


def cmd_adapter_verify(args) -> int:
    try:
        receipt = conformance_mod.load_certification(args.certification)
    except conformance_mod.ConformanceError as exc:
        print(f"adapter verification blocked: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    else:
        print(f"verified {receipt['certification_id']}: {receipt['status']}")
    return 0


def cmd_policy(args) -> int:
    try:
        policy = policy_mod.load_policy(args.repo)
        if policy is None:
            raise policy_mod.PolicyError("no .spindle/policy.toml or SPINDLE_POLICY")
        if args.policy_action == "show":
            payload = {"policy": policy.to_dict()}
            code = 0
        else:
            audit = policy_mod.audit_policy(
                policy,
                args.repo,
                args.harness,
                harness_build=args.harness_build,
            )
            payload = {"policy": policy.to_dict(), "audit": audit}
            code = 0 if audit["decision"] == "pass" else 2
    except (policy_mod.PolicyError, lifecycle_mod.LifecycleError) as exc:
        print(f"organization policy blocked: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.policy_action == "show":
        print(f"organization policy: {policy.policy_id} ({policy.path})")
    else:
        print(f"organization policy audit: {payload['audit']['decision']}")
        for finding in payload["audit"]["findings"]:
            print(f"  {finding['kind']}: {finding['detail']}")
    return code


# ---- effective lifecycle inventory -------------------------------------


def _effective_inventory(args) -> inventory_mod.EffectiveInventory:
    repo = Path(args.repo).resolve()
    sid = lifecycle_mod.surface_id(repo, args.harness)
    lock = lifecycle_mod.read_surface_lock(sid)
    return inventory_mod.scan_effective_inventory(
        repo,
        args.harness,
        surface_name=args.name or repo.name,
        lock=lock,
    )


def _print_inventory(inventory: inventory_mod.EffectiveInventory, *, diff_only=False):
    print(
        f"surface {inventory.surface_name!r} [{inventory.harness}]  "
        f"inventory {inventory.inventory_id}"
    )
    print(f"  desired: {inventory.lock_id or '(no surface lock)'}")
    counts = inventory.counts()
    if counts:
        print(
            "  states:  " + ", ".join(f"{key}={value}" for key, value in counts.items())
        )
    print()
    entries = inventory.entries
    if diff_only:
        entries = tuple(
            entry
            for entry in entries
            if entry.state is not inventory_mod.InventoryState.EXPECTED_OWNED
        )
    if not entries:
        print("(no effective-state differences)")
        return
    width = max(len(entry.name) for entry in entries)
    for entry in entries:
        path = entry.path or "(harness-reported scope required)"
        print(
            f"  {entry.name:<{width}}  {entry.state.value:<20} {entry.scope:<20} {path}"
        )
        if entry.state is not inventory_mod.InventoryState.EXPECTED_OWNED:
            print(f"  {'':<{width}}  {'':<20} {'':<20} ↳ {entry.reason}")


def cmd_inventory(args) -> int:
    try:
        inventory = _effective_inventory(args)
    except lifecycle_mod.LifecycleError as exc:
        print(f"inventory blocked: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(inventory.to_dict(), indent=2, sort_keys=True))
    else:
        _print_inventory(inventory)
    return 2 if args.strict and inventory.blocking_entries() else 0


def cmd_why(args) -> int:
    try:
        inventory = _effective_inventory(args)
    except lifecycle_mod.LifecycleError as exc:
        print(f"inventory blocked: {exc}", file=sys.stderr)
        return 2
    entries = inventory.entries_for(args.skill)
    if not entries:
        print(f"no effective skill named {args.skill!r}", file=sys.stderr)
        return 1
    if args.json:
        print(
            json.dumps(
                {
                    "inventory_id": inventory.inventory_id,
                    "skill": args.skill,
                    "entries": [entry.to_dict() for entry in entries],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    print(f"{args.skill!r} appears in {len(entries)} effective scope(s):")
    for entry in entries:
        print(f"  {entry.state.value:<20} {entry.scope:<20} {entry.path or '(opaque)'}")
        print(f"  {'':<20} {'':<20} {entry.reason}")
        if entry.ownership_id:
            print(f"  {'ownership':<20} {'':<20} {entry.ownership_id}")
        if entry.content_digest:
            print(f"  {'content':<20} {'':<20} {entry.content_digest}")
    return 0


def cmd_diff_effective(args) -> int:
    try:
        inventory = _effective_inventory(args)
    except lifecycle_mod.LifecycleError as exc:
        print(f"inventory blocked: {exc}", file=sys.stderr)
        return 2
    changed = tuple(
        entry
        for entry in inventory.entries
        if entry.state is not inventory_mod.InventoryState.EXPECTED_OWNED
    )
    if args.json:
        print(
            json.dumps(
                {
                    "inventory_id": inventory.inventory_id,
                    "lock_id": inventory.lock_id,
                    "differences": [entry.to_dict() for entry in changed],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        _print_inventory(inventory, diff_only=True)
    return 2 if args.strict and inventory.blocking_entries() else 0


def cmd_doctor_startup(args) -> int:
    try:
        inventory = _effective_inventory(args)
        actions: tuple[inventory_mod.ReconcileAction, ...] = ()
        if args.reconcile_owned:
            actions = inventory_mod.reconcile_owned(inventory, dry_run=args.dry_run)
            if actions and not args.dry_run:
                inventory = _effective_inventory(args)
        hook_state = hooks_mod.hook_status(
            Path(args.repo).resolve(), args.harness, scope="repo"
        )
    except lifecycle_mod.LifecycleError as exc:
        print(f"startup doctor blocked: {exc}", file=sys.stderr)
        return 2
    inventory_blocked = bool(inventory.blocking_entries())
    hooks_blocked = hook_state["state"] in {"blocked", "restart-required"}
    if inventory_blocked or hooks_blocked:
        decision = "blocked"
    elif hook_state["state"] != "observed":
        decision = "warn"
    else:
        decision = "ok"
    if args.json:
        print(
            json.dumps(
                {
                    "inventory": inventory.to_dict(),
                    "actions": [action.to_dict() for action in actions],
                    "hooks": hook_state,
                    "decision": decision,
                    "dry_run": args.dry_run,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        if actions:
            print("owned reconciliation:")
            for action in actions:
                print(f"  {action.action:<28} {action.skill}  {action.projection_path}")
            print()
        _print_inventory(inventory, diff_only=True)
        print(f"\nhooks: {hook_state['state']} ({hook_state['target_path']})")
        print(f"startup decision: {decision.upper()}")
    return 2 if decision == "blocked" else 0


# ---- startup bootstrap / launch -----------------------------------------


def _read_hook_payload() -> dict:
    if sys.stdin.isatty():
        return {}
    try:
        text = sys.stdin.read()
    except OSError:
        return {}
    if not text.strip():
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _startup_event(args, payload: dict) -> str:
    source = payload.get("source")
    if isinstance(source, str) and source:
        return source.lower().replace("_", "-")
    trigger = payload.get("trigger")
    if isinstance(trigger, str) and trigger:
        prefix = (args.event or payload.get("hook_event_name") or "hook").lower()
        return f"{prefix}:{trigger.lower().replace('_', '-')}"
    if args.event:
        return re.sub(r"(?<!^)(?=[A-Z])", "-", args.event).lower()
    hook_name = payload.get("hook_event_name") or payload.get("event")
    if isinstance(hook_name, str) and hook_name:
        return re.sub(r"(?<!^)(?=[A-Z])", "-", hook_name).lower()
    return "session-start" if args.hook else "pre-launch"


def _startup_payload(result: startup_mod.StartupResult) -> dict:
    return {
        "plan": result.plan.to_dict(),
        "receipt": result.receipt.to_dict(),
        "plan_path": str(result.plan_path),
        "receipt_path": str(result.receipt_path),
    }


def _startup_runtime_facts(payload: dict) -> dict[str, str]:
    facts: dict[str, str] = {}
    for key in (
        "session_id",
        "turn_id",
        "model",
        "permission_mode",
        "agent_id",
        "agent_type",
        "hook_event_name",
        "source",
        "trigger",
    ):
        value = payload.get(key)
        if isinstance(value, (str, int, float, bool)):
            facts[key] = str(value)
    return facts


def _print_startup_result(result: startup_mod.StartupResult, *, hook: bool) -> None:
    receipt = result.receipt
    marker = (
        f"Spindle: {receipt.decision}; "
        f"{len(receipt.applied_actions)} owned action(s); "
        f"{len(receipt.foreign_conflicts)} foreign conflict(s); "
        f"receipt {receipt.receipt_id.removeprefix('sha256:')[:12]}"
    )
    print(marker)
    if not hook:
        print(f"  plan:    {result.plan_path}")
        print(f"  receipt: {result.receipt_path}")


def _hook_event_name(args, payload: dict) -> str:
    value = payload.get("hook_event_name") or args.event
    if isinstance(value, str) and value:
        normalized = value.replace("-", "").lower()
        names = {
            "sessionstart": "SessionStart",
            "subagentstart": "SubagentStart",
            "setup": "Setup",
        }
        return names.get(normalized, value)
    return "SessionStart"


def _startup_exit(decision: str) -> int:
    if decision == "blocked":
        return 2
    if decision == "restart-required":
        return 3
    return 0


def cmd_bootstrap(args) -> int:
    payload = _read_hook_payload() if args.hook else {}
    harness = args.hook or args.harness
    if harness is None:
        print("bootstrap requires --harness or --hook", file=sys.stderr)
        return 2
    if args.hook and args.harness and args.hook != args.harness:
        print("--hook and --harness must name the same harness", file=sys.stderr)
        return 2
    repo = Path(args.repo or payload.get("cwd") or ".").resolve()
    if not repo.exists():
        print(f"no such repo path: {repo}", file=sys.stderr)
        return 2
    adapter_build = (
        args.adapter_build
        or payload.get("harness_build")
        or payload.get("version")
        or os.environ.get("SPINDLE_HARNESS_BUILD")
        or f"{harness}:unreported"
    )
    try:
        result = startup_mod.run_startup(
            repo,
            harness,
            reconcile_owned=args.reconcile_owned,
            surface_name=args.name,
            event_source=_startup_event(args, payload),
            adapter_build=str(adapter_build),
            already_discovered=bool(args.hook or args.already_discovered),
            digest_mode="cache-only" if args.hook else "deep",
            runtime_facts=_startup_runtime_facts(payload),
        )
    except lifecycle_mod.LifecycleError as exc:
        print(f"startup bootstrap blocked: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(_startup_payload(result), indent=2, sort_keys=True))
    elif args.hook:
        marker = (
            f"Spindle: {result.receipt.decision}; "
            f"{len(result.receipt.applied_actions)} owned action(s); "
            f"{len(result.receipt.foreign_conflicts)} foreign conflict(s); "
            f"receipt {result.receipt.receipt_id.removeprefix('sha256:')[:12]}"
        )
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": _hook_event_name(args, payload),
                        "additionalContext": marker,
                    }
                },
                separators=(",", ":"),
            )
        )
    else:
        _print_startup_result(result, hook=False)
    # Native harnesses only parse structured stdout on exit 0. The hook is a
    # post-discovery observer, so carry blocked/restart-required in its compact
    # context marker; enforcement belongs to the pre-launch bootstrap boundary.
    return 0 if args.hook else _startup_exit(result.receipt.decision)


def cmd_launch(args) -> int:
    repo = Path(args.repo).resolve()
    if not repo.exists():
        print(f"no such repo path: {repo}", file=sys.stderr)
        return 2
    try:
        result = startup_mod.run_startup(
            repo,
            args.harness,
            reconcile_owned=True,
            surface_name=args.name,
            event_source="pre-launch",
            adapter_build=args.adapter_build or f"{args.harness}:unreported",
            already_discovered=False,
        )
    except lifecycle_mod.LifecycleError as exc:
        print(f"launch blocked: {exc}", file=sys.stderr)
        return 2
    _print_startup_result(result, hook=False)
    decision_exit = _startup_exit(result.receipt.decision)
    if decision_exit:
        print("harness was not launched", file=sys.stderr)
        return decision_exit
    forwarded = list(args.harness_args)
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]
    command = [args.harness, *forwarded]
    try:
        completed = subprocess.run(command, cwd=repo, check=False)
    except OSError as exc:
        print(f"could not launch {args.harness!r}: {exc}", file=sys.stderr)
        return 127
    return completed.returncode


# ---- harness-native operator UX ----------------------------------------


def _print_harness_result(payload: dict) -> None:
    print(f"harness action: {payload.get('action', 'status')}")
    plan = payload.get("plan")
    if isinstance(plan, dict):
        workspace = plan.get("workspace")
        if isinstance(workspace, dict):
            projection = workspace.get("operator_projection", {})
            hook = workspace.get("hook_configuration", {})
            print(f"  operator: {projection.get('path', '(unavailable)')}")
            print(f"  hooks:    {hook.get('path', '(unavailable)')}")
    operator = payload.get("operator")
    if isinstance(operator, dict):
        print(f"  operator: {operator.get('state', 'unknown')}")
        print(f"  invoke:   {operator.get('invocation', '(unavailable)')}")
        hook = operator.get("hooks")
        if isinstance(hook, dict):
            print(f"  hooks:    {hook.get('state', 'unknown')}")
    if payload.get("operator_ready") and not payload.get("surface_ready", True):
        print("  surface:  blocked; operator is available for diagnosis")
    if payload.get("next"):
        print(f"  next:     {payload['next']}")
    elif payload.get("requires_new_session"):
        print("  next:     start a new harness session and review hook trust")


def cmd_harness_setup(args) -> int:
    try:
        payload = operator_mod.setup_operator(
            args.repo,
            args.harness,
            surface_name=args.name,
            dry_run=args.dry_run,
        )
    except lifecycle_mod.LifecycleError as exc:
        print(f"harness setup blocked: {exc}", file=sys.stderr)
        return 2
    display = "Codex" if args.harness == "codex" else "Claude Code"
    invocation = "$spindle" if args.harness == "codex" else "/spindle"
    if payload["action"].startswith("would-"):
        payload["next"] = (
            f"Apply this plan without --dry-run, then start a new {display} "
            f"session and invoke {invocation}."
        )
    elif payload["requires_new_session"]:
        payload["next"] = (
            f"Start a new {display} session and invoke {invocation}; review hook "
            "trust when the harness asks."
        )
    elif payload["action"] != "blocked":
        payload["next"] = f"Invoke {invocation} in the current session."
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_harness_result(payload)
    if payload["action"] == "blocked":
        return 2
    return 1 if payload["action"] == "partial" else 0


def cmd_harness_status(args) -> int:
    try:
        operator = operator_mod.operator_status(args.repo, args.harness)
    except lifecycle_mod.LifecycleError as exc:
        print(f"harness status blocked: {exc}", file=sys.stderr)
        return 2
    payload = {"action": "status", "operator": operator}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_harness_result(payload)
    healthy_hooks = {"observed", "observed-warn"}
    return (
        0
        if operator["state"] == "current"
        and operator["hooks"]["state"] in healthy_hooks
        else 1
    )


def cmd_harness_context(args) -> int:
    try:
        payload = operator_mod.harness_context(args.repo, args.harness)
    except lifecycle_mod.LifecycleError as exc:
        print(f"harness context blocked: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        surface = payload["surface"]
        operator = payload["operator"]
        print(
            f"{surface['name']} [{surface['harness']}]  "
            f"operator {operator['state']}  hooks {payload['runtime']['hook_state']}"
        )
        print(
            f"  desired: {surface['lock_id'] or '(none)'}  "
            f"inventory: {surface['inventory_id']}"
        )
        for command in payload["recommended"]:
            print(f"  next: {command}")
    return 0


def cmd_harness_remove(args) -> int:
    try:
        payload = operator_mod.remove_operator(
            args.repo,
            args.harness,
            dry_run=args.dry_run,
        )
    except lifecycle_mod.LifecycleError as exc:
        print(f"harness removal blocked: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_harness_result(payload)
    if payload["action"] == "blocked":
        return 2
    return 1 if payload["action"] == "partial" else 0


# ---- native hook kit management ----------------------------------------


def _hook_repo(args) -> Path:
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        raise lifecycle_mod.LifecycleError(f"no such repo path: {repo}")
    return repo


def _print_hook_plan(plan: hooks_mod.HookPlan) -> None:
    print(f"hook plan: {plan.plan_id}")
    print(f"  target:          {plan.target_path}")
    print(f"  add:             {len(plan.additions)} fragment(s)")
    print(f"  already owned:   {len(plan.owned)} fragment(s)")
    print(f"  foreign present: {len(plan.foreign_present)} fragment(s)")
    for blocker in plan.blockers:
        print(f"  BLOCKED: {blocker}")
    for warning in plan.warnings:
        print(f"  warning: {warning}")


def cmd_hooks_plan(args) -> int:
    try:
        plan = hooks_mod.plan_hooks(_hook_repo(args), args.harness, scope=args.scope)
    except lifecycle_mod.LifecycleError as exc:
        print(f"hook plan blocked: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
    else:
        _print_hook_plan(plan)
    return 2 if plan.blockers else 0


def cmd_hooks_install(args) -> int:
    try:
        result = hooks_mod.install_hooks(
            _hook_repo(args),
            args.harness,
            scope=args.scope,
            dry_run=args.dry_run,
        )
    except lifecycle_mod.LifecycleError as exc:
        print(f"hook install blocked: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        _print_hook_plan(result.plan)
        print(f"hook action: {result.action}")
        if result.receipt is not None:
            print(f"  ownership: {result.receipt.receipt_id}")
    return 2 if result.action == "blocked" else 0


def cmd_hooks_status(args) -> int:
    try:
        status = hooks_mod.hook_status(_hook_repo(args), args.harness, scope=args.scope)
    except lifecycle_mod.LifecycleError as exc:
        print(f"hook status blocked: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(f"hook state: {status['state']}")
        print(f"  target: {status['target_path']}")
        if status["heartbeat"] is not None:
            print(f"  heartbeat: {status['heartbeat']['receipt_id']}")
        for blocker in status["blockers"]:
            print(f"  BLOCKED: {blocker}")
        for warning in status["warnings"]:
            print(f"  warning: {warning}")
    if status["state"] in {"blocked", "restart-required"}:
        return 2
    return 0 if status["state"] == "observed" else 1


def cmd_hooks_remove(args) -> int:
    try:
        result = hooks_mod.remove_hooks(
            _hook_repo(args),
            args.harness,
            scope=args.scope,
            dry_run=args.dry_run,
        )
    except lifecycle_mod.LifecycleError as exc:
        print(f"hook removal blocked: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        _print_hook_plan(result.plan)
        print(f"hook action: {result.action}")
    return 2 if result.action.startswith("blocked") else 0


# ---- explicit foreign conflict decisions -------------------------------


def _conflict_lock(args) -> lifecycle_mod.SurfaceLock:
    repo = Path(args.repo).resolve()
    sid = lifecycle_mod.surface_id(repo, args.harness)
    lock = lifecycle_mod.read_surface_lock(sid)
    if lock is not None:
        return lock
    return lifecycle_mod.SurfaceLock(
        surface_id=sid,
        surface_name=args.name or repo.name,
        repo_path=str(repo),
        harness=args.harness,
        binding_coordinate="conflict-only/v1",
        projections=(),
    )


def _lock_with_conflicts(
    lock: lifecycle_mod.SurfaceLock, decision_ids: tuple[str, ...]
) -> lifecycle_mod.SurfaceLock:
    return lifecycle_mod.SurfaceLock(
        surface_id=lock.surface_id,
        surface_name=lock.surface_name,
        repo_path=lock.repo_path,
        harness=lock.harness,
        binding_coordinate=lock.binding_coordinate,
        projections=lock.projections,
        adoption_ids=lock.adoption_ids,
        lease_ids=lock.lease_ids,
        conflict_decisions=tuple(sorted(set(decision_ids))),
    )


def cmd_conflict_allow(args) -> int:
    try:
        inventory = _effective_inventory(args)
        candidates = [
            entry
            for entry in inventory.entries
            if entry.name == args.skill
            and entry.state is inventory_mod.InventoryState.CONFLICTING
            and (args.path is None or entry.path == str(Path(args.path).absolute()))
        ]
        if len(candidates) != 1:
            paths = [entry.path for entry in candidates]
            raise lifecycle_mod.LifecycleError(
                f"conflict allow requires exactly one matching path; observed {paths}"
            )
        entry = candidates[0]
        if entry.path is None or entry.content_digest is None:
            raise lifecycle_mod.LifecycleError(
                "conflict must have an inspectable path and exact content digest"
            )
        lock = _conflict_lock(args)
        decision = lifecycle_mod.ConflictDecision(
            surface_id=lock.surface_id,
            harness=args.harness,
            skill=entry.name,
            observed_path=entry.path,
            observed_digest=entry.content_digest,
            disposition="allow",
            reason=args.reason,
        )
        proposed = _lock_with_conflicts(
            lock, (*lock.conflict_decisions, decision.decision_id)
        )
        action = (
            "no-change"
            if decision.decision_id in lock.conflict_decisions
            else "would-allow"
            if args.dry_run
            else "allowed"
        )
        if not args.dry_run and action != "no-change":
            with startup_mod.SurfaceMutex(lock.surface_id):
                current = _conflict_lock(args)
                if current.lock_id != lock.lock_id:
                    raise lifecycle_mod.LifecycleError(
                        "surface lock changed after conflict planning"
                    )
                observed = _effective_inventory(args)
                if observed.inventory_id != inventory.inventory_id:
                    raise lifecycle_mod.LifecycleError(
                        "effective inventory changed after conflict planning"
                    )
                lifecycle_mod.ConflictDecisionStore().record(decision)
                lifecycle_mod.write_surface_lock(proposed)
    except lifecycle_mod.LifecycleError as exc:
        print(f"conflict decision blocked: {exc}", file=sys.stderr)
        return 2
    payload = {
        "action": action,
        "decision": decision.to_dict(),
        "current_lock_id": lock.lock_id,
        "proposed_lock_id": proposed.lock_id,
        "dry_run": args.dry_run,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"conflict action: {action}")
        print(f"  decision: {decision.decision_id}")
        print(f"  path:     {decision.observed_path}")
        print(f"  digest:   {decision.observed_digest}")
    return 0


def cmd_conflict_list(args) -> int:
    try:
        lock = _conflict_lock(args)
        store = lifecycle_mod.ConflictDecisionStore()
        decisions = [store.get(decision_id) for decision_id in lock.conflict_decisions]
    except lifecycle_mod.LifecycleError as exc:
        print(f"conflict list blocked: {exc}", file=sys.stderr)
        return 2
    payload = {
        "surface_id": lock.surface_id,
        "lock_id": lock.lock_id,
        "decisions": [decision.to_dict() for decision in decisions],
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        if not decisions:
            print("no explicit foreign conflict decisions")
        for decision in decisions:
            print(
                f"{decision.decision_id}  {decision.skill}  "
                f"{decision.disposition}  {decision.observed_path}"
            )
    return 0


def cmd_conflict_revoke(args) -> int:
    try:
        lock = _conflict_lock(args)
        if args.decision_id not in lock.conflict_decisions:
            raise lifecycle_mod.LifecycleError(
                "conflict decision is not active in this surface lock"
            )
        decision = lifecycle_mod.ConflictDecisionStore().get(args.decision_id)
        proposed = _lock_with_conflicts(
            lock,
            tuple(item for item in lock.conflict_decisions if item != args.decision_id),
        )
        action = "would-revoke" if args.dry_run else "revoked"
        if not args.dry_run:
            with startup_mod.SurfaceMutex(lock.surface_id):
                current = _conflict_lock(args)
                if current.lock_id != lock.lock_id:
                    raise lifecycle_mod.LifecycleError(
                        "surface lock changed after conflict planning"
                    )
                lifecycle_mod.write_surface_lock(proposed)
    except lifecycle_mod.LifecycleError as exc:
        print(f"conflict revoke blocked: {exc}", file=sys.stderr)
        return 2
    payload = {
        "action": action,
        "decision": decision.to_dict(),
        "current_lock_id": lock.lock_id,
        "proposed_lock_id": proposed.lock_id,
        "dry_run": args.dry_run,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"conflict action: {action}")
        print(f"  decision retained in history: {decision.decision_id}")
    return 0


# ---- advance ------------------------------------------------------------


def cmd_advance_run(args) -> int:
    """Precompute compositions for all known surfaces (advance-team pass)."""
    try:
        doc = doctrine_mod.load()
    except FileNotFoundError:
        print("no doctrine.toml in the active distribution", file=sys.stderr)
        return 1
    if args.from_registry:
        targets = advance_mod.targets_from_registry(
            Path(args.from_registry) if args.from_registry is not True else None
        )
        if not targets:
            print(
                "no surfaces from registry (set SPINDLE_PROJECTS_DIR or pass a path; "
                "needs local checkouts under the repo root)"
            )
            return 0
    else:
        targets = advance_mod.load_targets()
        if not targets:
            print(
                "no surfaces configured (see <source_dir>/advance/surfaces.toml, "
                "or use --from-registry)"
            )
            return 0
    provider, render_fn = _bind_context(doc, no_render=args.no_render)
    results = advance_mod.precompute(
        targets, provider, doc, render=render_fn, force=args.force, dry_run=args.dry_run
    )
    ok = sum(1 for _, r in results if r.ok)
    for name, r in results:
        status = "ok" if r.ok else f"BLOCKED ({len(r.problems)})"
        coord = f" {r.coordinate}" if r.coordinate else ""
        print(f"  {status:<14} {name}{coord}")
    print(
        f"precomputed {ok}/{len(results)} surface(s)"
        + (" (dry-run)" if args.dry_run else "")
    )
    return 0 if ok == len(results) else 1


# ---- liaison ------------------------------------------------------------


def cmd_liaison_request(args) -> int:
    """Articulate a surface's ad-hoc need as a what-request and log it (demand stream)."""
    repo = Path(args.repo).resolve()
    if not repo.exists():
        print(f"no such repo path: {repo}", file=sys.stderr)
        return 1
    req = liaison_mod.gather_request(
        repo,
        args.intent,
        harness=args.harness,
        autonomy_mode=args.autonomy,
        name=args.name,
        registry_kind=args.kind,
        desired_outcomes=args.outcome or [],
        acceptance=args.accept or [],
    )
    path = liaison_mod.log_request(req)
    print(f"what-request for {req.surface!r} [{req.harness} · {req.autonomy_mode}]")
    print(f"  intent:   {req.intent}")
    if req.desired_outcomes:
        print(f"  outcomes: {'; '.join(req.desired_outcomes)}")
    if req.acceptance:
        print(f"  accept:   {'; '.join(req.acceptance)}")
    print(f"  app-class: {req.local_facts.get('app_class')}")
    print(f"logged → {path}  (feeds the advance team)")

    if args.bind:
        try:
            doc = doctrine_mod.load()
        except FileNotFoundError:
            print(
                "(--bind: no doctrine in active distribution; skipped)", file=sys.stderr
            )
            return 0
        provider, render_fn = _bind_context(doc, no_render=False)
        result = liaison_mod.answer(req, repo, provider, doc, render=render_fn)
        if result.ok:
            print(
                f"  → bound the surface's current best set (coordinate {result.coordinate})"
            )
        else:
            print(
                f"  → bind blocked: {len(result.problems)} problem(s)", file=sys.stderr
            )
    return 0


def cmd_liaison_log(args) -> int:
    """Show a surface's logged what-requests (its demand stream)."""
    reqs = liaison_mod.read_requests(args.surface)
    if not reqs:
        print(f"(no what-requests logged for {args.surface!r})")
        return 0
    print(f"{len(reqs)} what-request(s) for {args.surface!r}:")
    for r in reqs:
        print(f"  {r.ts}  {r.intent}")
    return 0


# ---- roster + broker (the marketplace facade) ---------------------------


def cmd_roster_list(args) -> int:
    """Show the roster of upstream skill sources Spindle can broker from."""
    srcs = roster_mod.list_sources()
    if not srcs:
        print("(no roster sources — see <source_dir>/roster/sources.toml)")
        return 0
    for s in srcs:
        flag = "on " if s.get("enabled") else "off"
        print(
            f"  [{flag}] {s.get('slug', ''):<14} {s.get('kind', ''):<12} {s.get('notes', '')}"
        )
    return 0


def cmd_broker(args) -> int:
    """Broker a what-request against external skill rosters: search → rank → propose.

    Proposes only (P7/P8 — never auto-installs). Offline by default: live providers
    shell out to the source tools, so a source must be enabled AND its tool present
    to return anything. ``--acquire N`` brings proposal N in (transpose stub +
    records the outcome to the acquisitions ledger).
    """
    if args.agent:
        req = liaison_mod.gather_agent_request(
            args.agent,
            args.intent,
            harness=args.harness,
            autonomy_mode=args.autonomy,
            desired_outcomes=args.outcome or [],
        )
    else:
        repo = Path(args.repo or ".").resolve()
        req = liaison_mod.gather_request(
            repo,
            args.intent,
            harness=args.harness,
            autonomy_mode=args.autonomy,
            desired_outcomes=args.outcome or [],
            registry_kind=args.kind,
        )
    providers = roster_mod.live_providers()
    proposals = broker_mod.broker(
        req, providers=providers, limit=args.limit, min_fit=args.min_fit
    )
    print(f"what-request {req.surface!r}: {req.intent!r}")
    if not proposals:
        print(
            "  (no external candidates — enable a roster source and install its tool, "
            "or widen the query)"
        )
        return 0
    for i, a in enumerate(proposals):
        print(
            f"  [{i}] fit={a.fit:<6} {a.candidate.source}:{a.candidate.id}  "
            f"{a.candidate.title}"
        )
    if args.acquire is not None:
        if not (0 <= args.acquire < len(proposals)):
            print(f"no proposal [{args.acquire}]", file=sys.stderr)
            return 1
        acq = broker_mod.acquire(proposals[args.acquire])
        print(
            f"acquired {acq.candidate.source}:{acq.candidate.id} "
            f"(transposed={acq.provenance.get('transposed')}) — recorded to ledger"
        )
    return 0


def cmd_acquisitions(args) -> int:
    """Show the acquisitions ledger — what external skills were brokered, and outcomes."""
    recs = broker_mod.read_acquisitions()
    if not recs:
        print("(no acquisitions recorded)")
        return 0
    for r in recs:
        c = r.get("candidate", {})
        worked = r.get("worked")
        mark = "" if worked is None else (" ✓" if worked else " ✗")
        print(
            f"  {r.get('ts', '')}  {r.get('status', ''):<9} "
            f"{c.get('source', '')}:{c.get('id', '')}  fit={r.get('fit')}{mark}"
        )
    return 0


# ---- optimize (validation-gated skill optimization) ---------------------


def cmd_optimize(args) -> int:
    """Optimize a skill's text against a held-out eval, accepting edits only on
    measured improvement (SkillOpt loop). Needs a scorer (--score-cmd) and a
    proposer (ANTHROPIC_API_KEY); offline it explains the loop and exits.

    The scorer command is run per candidate with $SPINDLE_SKILL_FILE set to a temp
    file holding the candidate skill; it prints the held-out score. Guardrails are
    preserved by construction (a guardrail-dropping edit is rejected unscored).
    """
    path = Path(args.skill)
    if not path.exists():
        print(f"no such skill file: {path}", file=sys.stderr)
        return 1
    text = path.read_text(encoding="utf-8")

    if not args.score_cmd:
        print(
            "optimize needs a held-out scorer: --score-cmd '<cmd printing a score>' "
            "(the candidate skill is written to $SPINDLE_SKILL_FILE)."
        )
        print(
            "  the loop: baseline → propose bounded edit → guardrail-check → score "
            "held-out → accept iff it improves (else reject + buffer)."
        )
        return 0
    client = llm_mod.from_env()
    if client is None:
        print(
            "optimize needs a proposer: set ANTHROPIC_API_KEY (an LLM proposes one "
            "bounded edit per epoch). The scorer + gate + guardrail floor are ready."
        )
        return 0

    score = optimize_mod.command_scorer(args.score_cmd)
    propose = optimize_mod.llm_proposer(client)
    result = optimize_mod.optimize(
        text,
        score=score,
        propose=propose,
        skill=path.stem,
        epochs=args.epochs,
        min_improvement=args.min_improvement,
    )
    print(
        f"skillopt {result.skill!r}: baseline {result.baseline:.4f} → "
        f"{result.best:.4f} (Δ{result.delta:+.4f}, {result.accepted_count}/"
        f"{len(result.epochs)} edits accepted)"
    )
    for e in result.epochs:
        mark = "✓ accept" if e.accepted else "✗ reject"
        print(
            f"  epoch {e.epoch}: {mark}  score={e.score:.4f}  [{e.reason}]  {e.rationale}"
        )
    if result.improved and not args.dry_run:
        if args.out:
            outp = Path(args.out)
        else:
            outp = path.with_suffix(path.suffix + ".optimized")
        outp.write_text(result.best_text, encoding="utf-8")
        print(f"wrote optimized skill → {outp}  (review before replacing the original)")
    elif not result.improved:
        print(
            "no edit cleared the gate — the skill is unchanged (a real, honest result)."
        )
    return 0


# ---- scout --------------------------------------------------------------


def cmd_scout(args) -> int:
    """Emit runner commands for a scout pass, or apply a pass result.

    Default mode prints one command per peer using the configured scout command
    template.

    --write-candidates: same as default but the --notify callback is wired
    to `spindle scout --apply-results` so a runner can write candidate verdicts
    automatically into the local candidates queue.

    --apply-results FILE: parse a runner result JSON/markdown and write any
    candidate verdict blocks it contains into the candidates queue.
    """
    # ---- apply-results mode ----
    if args.apply_results:
        result_file = Path(args.apply_results)
        if not result_file.exists():
            print(f"no such file: {result_file}", file=sys.stderr)
            return 1
        written = scout_results_mod.apply_results(result_file)
        if written:
            for p in written:
                print(f"wrote candidate: {p}")
        else:
            print("no candidate verdicts found in result")
        # Close the loop: advance last_seen for the peer this pass covered, so the
        # next pass diffs from when we actually looked. The scout job names its
        # result file <peer-slug>.json (see spindle.scout.emit_scout_jobs). Best-effort:
        # writing candidates is the real job, so a peers-file/active-dist hiccup
        # here must not fail the command.
        # Runner result files can be generically named; when available, the peer
        # travels in payload tags. Fall back to the filename for hand-run applies.
        slug = result_file.stem
        try:
            _payload = json.loads(result_file.read_text())
            slug = (_payload.get("tags") or {}).get("peer") or slug
        except Exception:
            pass
        try:
            if peers_mod.touch(slug):
                print(f"advanced last_seen for peer {slug!r}")
        except Exception as exc:  # noqa: BLE001 — last_seen bump is non-critical
            print(f"(could not advance last_seen for {slug!r}: {exc})", file=sys.stderr)
        return 0

    # ---- emit runner commands ----
    try:
        commands = scout_mod.emit_scout_jobs(
            slug=args.slug or None,
            write_candidates=args.write_candidates,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for cmd in commands:
        print(cmd)
    return 0


# ---- fleet --------------------------------------------------------------


def cmd_fleet_status(_args) -> int:
    machines = fleet_mod.fleet_status()
    if not machines:
        print("(no fleet events yet — run `spindle fleet sync` first)")
        return 0
    this = fleet_mod.machine_id()
    width = max(len(m.machine) for m in machines)
    for m in machines:
        marker = " *" if m.machine == this else "  "
        dists = (
            ", ".join(f"{n}@{v}" for n, v in sorted(m.distributions.items()))
            or "(none)"
        )
        last = m.last_event_ts or "—"
        print(
            f"{marker} {m.machine:<{width}}  events={m.event_count:<4}  last={last}  dists=[{dists}]"
        )
    return 0


def cmd_fleet_sync(args) -> int:
    try:
        result = fleet_mod.fleet_sync(remote=args.remote, push=not args.no_push)
    except fleet_mod.GitError as e:
        print(f"git error: {e}", file=sys.stderr)
        return 1
    print(f"repo:      {result.repo}")
    print(f"machine:   {result.machine}")
    print(f"committed: {result.committed}")
    print(f"remote:    {result.remote or '(none)'}")
    if result.remote:
        print(f"pulled:    {result.pulled}")
        print(f"pushed:    {result.pushed}")
    if result.detail:
        print("detail:")
        for line in result.detail.splitlines():
            print(f"  {line}")
    return 0


# ---- state --------------------------------------------------------------


def cmd_state_show(_args) -> int:
    state = ledger_mod.show_state()
    print(f"  {'machine_id':<18} {state.machine_id}")
    print(f"  {'rebuilt_at':<18} {state.rebuilt_at}")
    if state.preempted_by:
        print(f"  {'preempted_by':<18} {state.preempted_by}")
    if state.distributions:
        print(f"  {'distributions':<18} {list(state.distributions.keys())[0]}")
        for name in list(state.distributions.keys())[1:]:
            print(f"  {'':<18} {name}")
        print()
        for name, dist in sorted(state.distributions.items()):
            print(f"    {name}")
            print(f"      version:         {dist.version}")
            print(f"      installed_at:    {dist.installed_at}")
            if dist.packages:
                pkg_str = ", ".join(
                    f"{k}={v}" for k, v in sorted(dist.packages.items())
                )
                print(f"      packages:        {pkg_str}")
            if dist.skills_linked:
                skills_str = ", ".join(dist.skills_linked)
                print(f"      skills_linked:   {skills_str}")
    else:
        print(f"  {'distributions':<18} (none)")
    return 0


def cmd_state_rebuild(_args) -> int:
    state = ledger_mod.materialize()
    events_path = events_file()
    state_path = state_file()
    print(f"rebuilt state from {events_path}")
    print(f"wrote {state_path}")
    print(f"machine_id:       {state.machine_id}")
    print(f"rebuilt_at:       {state.rebuilt_at}")
    print(f"distributions:    {len(state.distributions)}")
    return 0


def _print_json_or_action(payload: dict, *, emit_json: bool) -> None:
    if emit_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"state action: {payload['action']}")


def cmd_state_export(args) -> int:
    try:
        payload = custody_mod.export_state(
            args.output,
            include_cache=args.include_cache,
            dry_run=args.dry_run,
        )
    except custody_mod.CustodyError as exc:
        print(f"state export blocked: {exc}", file=sys.stderr)
        return 2
    _print_json_or_action(payload, emit_json=args.json)
    return 0


def cmd_state_import(args) -> int:
    try:
        payload = custody_mod.import_state(
            args.bundle,
            destination=Path(args.destination).resolve() if args.destination else None,
            dry_run=args.dry_run,
        )
    except custody_mod.CustodyError as exc:
        print(f"state import blocked: {exc}", file=sys.stderr)
        return 2
    _print_json_or_action(payload, emit_json=args.json)
    return 0


def cmd_state_gc(args) -> int:
    try:
        if args.apply:
            payload = custody_mod.apply_cache_gc(args.apply, dry_run=args.dry_run)
        else:
            plan = custody_mod.cache_gc_plan()
            payload = {"action": "gc-plan", "plan": plan}
    except (custody_mod.CustodyError, lifecycle_mod.LifecycleError) as exc:
        print(f"cache GC blocked: {exc}", file=sys.stderr)
        return 2
    _print_json_or_action(payload, emit_json=args.json)
    plan = payload["plan"]
    return 2 if plan["blockers"] else 0


def cmd_state_recover(args) -> int:
    try:
        if args.apply:
            payload = custody_mod.apply_recovery(args.apply, dry_run=args.dry_run)
        else:
            plan = custody_mod.recovery_plan()
            payload = {"action": "recovery-plan", "plan": plan}
    except custody_mod.CustodyError as exc:
        print(f"state recovery blocked: {exc}", file=sys.stderr)
        return 2
    _print_json_or_action(payload, emit_json=args.json)
    return 2 if payload["plan"]["blockers"] else 0


def cmd_migrate(args) -> int:
    try:
        if args.migration_action == "plan":
            plan = custody_mod.migration_plan(args.repo, args.harness)
            payload = {"action": "migration-plan", "plan": plan}
        else:
            payload = custody_mod.record_migration(
                args.plan_id, args.repo, args.harness
            )
    except (
        custody_mod.CustodyError,
        lifecycle_mod.LifecycleError,
    ) as exc:
        print(f"migration blocked: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"migration action: {payload['action']}")
    return 2 if payload["plan"]["blockers"] else 0


# ---- package ------------------------------------------------------------


def cmd_package_list(_args) -> int:
    pkgs = packages_mod.list_installed_packages()
    if not pkgs:
        print("(no spindle packages installed)")
        return 0
    name_width = max(len(p.name) for p in pkgs)
    for p in pkgs:
        dist = p.distribution or "(standalone)"
        skills = ", ".join(p.skills) if p.skills else "(none)"
        print(f"  {p.name:<{name_width}}  {p.version:<8}  {dist:<16}  skills: {skills}")
    return 0


def cmd_package_show(args) -> int:
    meta = packages_mod.read_package_metadata(args.name)
    if meta is None:
        print(f"no package {args.name!r}", file=sys.stderr)
        return 1
    print(f"  {'name':<14} {meta.name}")
    print(f"  {'version':<14} {meta.version}")
    print(f"  {'distribution':<14} {meta.distribution or '(standalone)'}")
    print(f"  {'skills':<14} {', '.join(meta.skills) if meta.skills else '(none)'}")
    print(
        f"  {'capabilities':<14} {', '.join(meta.capabilities) if meta.capabilities else '(none)'}"
    )
    print(f"  {'package_dir':<14} {meta.package_dir}")
    try:
        revision = packages_mod.resolve_package_revision(args.name)
    except (ValueError, lifecycle_mod.LifecycleError) as exc:
        print(f"  {'content':<14} unavailable ({exc})")
    else:
        print(f"  {'content':<14} {revision.content_digest}")
        print(f"  {'revision':<14} {revision.source.revision}")
        print(f"  {'provider':<14} {revision.source.provider}")
        print(f"  {'editable':<14} {'yes' if revision.editable else 'no'}")
    if meta.sources:
        for src in meta.sources:
            print(
                f"  {'source':<14} {src.peer}  {src.url}  (transposed {src.transposed_at})"
            )
    return 0


def cmd_package_snapshot(args) -> int:
    try:
        revision = packages_mod.resolve_package_revision(args.name)
    except (ValueError, lifecycle_mod.LifecycleError) as exc:
        print(f"snapshot blocked: {exc}", file=sys.stderr)
        return 2
    destination = (
        paths_mod.package_cache_dir()
        / revision.content_digest.removeprefix("sha256:")
        / revision.name
    )
    if not args.dry_run:
        try:
            destination = lifecycle_mod.cache_package(revision)
        except lifecycle_mod.LifecycleError as exc:
            print(f"snapshot blocked: {exc}", file=sys.stderr)
            return 2
    payload = {
        "revision": revision.to_dict(),
        "cache_path": str(destination),
        "dry_run": args.dry_run,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        action = "would cache" if args.dry_run else "cached"
        print(f"{action} {revision.name}@{revision.version}")
        print(f"  content: {revision.content_digest}")
        print(f"  path:    {destination}")
    return 0


# ---- package new --------------------------------------------------------


def cmd_package_new(args) -> int:
    skills = args.skill or []
    capabilities = args.capabilities or []
    try:
        written = scaffold_mod.package_new(
            name=args.name,
            dest=args.dest,
            skills=skills,
            capabilities=capabilities,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for p in written:
        print(p)
    return 0


# ---- dist new -----------------------------------------------------------


def cmd_dist_new(args) -> int:
    packages = args.package or []
    try:
        written = scaffold_mod.dist_new(
            name=args.name,
            dest=args.dest,
            source_dir=args.source_dir or "../../",
            packages=packages,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for p in written:
        print(p)
    return 0


# ---- dist ---------------------------------------------------------------


def cmd_dist_list(_args) -> int:
    dists = distributions_mod.list_installed_distributions()
    if not dists:
        print("(no spindle distributions installed)")
        return 0
    name_width = max(len(d.name) for d in dists)
    for d in dists:
        pkg_count = len(d.packages)
        print(
            f"  {d.name:<{name_width}}  {d.version:<8}  {pkg_count} package{'s' if pkg_count != 1 else ''}"
        )
    return 0


def cmd_dist_show(args) -> int:
    meta = distributions_mod.read_distribution_metadata(args.name)
    if meta is None:
        print(f"no distribution {args.name!r}", file=sys.stderr)
        return 1
    print(f"  {'name':<16} {meta.name}")
    print(f"  {'version':<16} {meta.version}")
    print(f"  {'display_name':<16} {meta.display_name}")
    print(f"  {'description':<16} {meta.description or '(none)'}")
    print(f"  {'home_url':<16} {meta.home_url or '(none)'}")
    print(f"  {'source_dir':<16} {meta.source_dir}")
    print(f"  {'preempt_snippet':<16} {meta.preempt_snippet or '(none)'}")
    if meta.packages:
        print(f"  {'packages':<16} {meta.packages[0]}")
        for pkg in meta.packages[1:]:
            print(f"  {'':<16} {pkg}")
    else:
        print(f"  {'packages':<16} (none)")
    return 0


def cmd_dist_install(args) -> int:
    before_names = {d.name for d in distributions_mod.list_installed_distributions()}

    if not args.dry_run:
        try:
            _out, err = resolver_mod.uv_install(args.source)
            if err:
                print(err, end="", file=sys.stderr)
        except resolver_mod.ResolverError as e:
            print(f"install error: {e}", file=sys.stderr)
            if e.stderr:
                print(e.stderr, end="", file=sys.stderr)
            return 1

    after = distributions_mod.list_installed_distributions()
    after_by_name = {d.name: d for d in after}
    new_names = sorted(set(after_by_name) - before_names)

    # If a new distribution appeared, link only its skills; otherwise link all.
    dist_filter: str | None = new_names[0] if len(new_names) == 1 else None
    dist_meta = after_by_name.get(dist_filter) if dist_filter else None

    results = skills_mod.install_skills(distribution=dist_filter, dry_run=args.dry_run)
    for name, action in results:
        print(f"  {name:<22} {action}")

    if not args.dry_run and dist_filter and dist_meta:
        # Build packages dict with installed versions
        import importlib.metadata

        packages = {}
        for pkg_spec in dist_meta.packages:
            # Strip version specifiers (e.g., "sample-planning==0.1.0" -> "sample-planning")
            pkg_name = _strip_version(pkg_spec)
            try:
                pkg_dist = importlib.metadata.distribution(pkg_name)
                packages[pkg_name] = pkg_dist.version
            except importlib.metadata.PackageNotFoundError:
                packages[pkg_name] = ""
        # Build skills_linked list from install results
        skills_linked = [
            name
            for name, action in results
            if "installed" in action or "linked" in action
        ]
        ledger_mod.log_event(
            "dist_install",
            distribution=dist_filter,
            version=dist_meta.version,
            packages=packages,
            skills_linked=skills_linked,
        )

    return 0


def cmd_dist_uninstall(args) -> int:
    meta = distributions_mod.read_distribution_metadata(args.name)
    if meta is None:
        print(f"no distribution {args.name!r}", file=sys.stderr)
        return 1

    results = skills_mod.uninstall_skills(distribution=args.name, dry_run=args.dry_run)
    for name, action in results:
        print(f"  {name:<22} {action}")

    if args.remove_packages and not args.dry_run:
        pkg_names = [_strip_version(p) for p in meta.packages]
        pkg_names.append(args.name)
        for pkg in pkg_names:
            try:
                resolver_mod.uv_uninstall(pkg)
                print(f"  {pkg:<22} removed-package")
            except resolver_mod.ResolverError as e:
                print(f"  {pkg:<22} remove-error: {e}", file=sys.stderr)

    if not args.dry_run:
        ledger_mod.log_event(
            "dist_uninstall", distribution=args.name, version=meta.version
        )

    return 0


def _resolve_active_method() -> str:
    """Determine which resolution method was used to get the active distribution."""
    import os

    if os.environ.get("SPINDLE_ACTIVE_DIST_DIR"):
        return "SPINDLE_ACTIVE_DIST_DIR"
    if os.environ.get("SPINDLE_ACTIVE_DIST_NAME"):
        return "SPINDLE_ACTIVE_DIST_NAME"
    pointer_file = active_mod._active_pointer_file()
    if pointer_file.exists():
        return f"pointer file ({pointer_file})"
    installed = distributions_mod.list_installed_distributions()
    if len(installed) == 1:
        return "only-installed fallback"
    return "unknown"


def cmd_dist_activate(args) -> int:
    if args.name is None:
        try:
            current = active_mod.active_distribution()
        except active_mod.ActiveDistributionError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        method = _resolve_active_method()
        print(f"active:  {current}")
        print(f"method:  {method}")
        return 0
    else:
        try:
            active_mod.set_active(args.name)
        except active_mod.ActiveDistributionError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"activated: {args.name}")
        return 0


# ---- skill ---------------------------------------------------------------


def cmd_skill_list(_args) -> int:
    skills = skills_mod.discover_skills()
    if not skills:
        print("(no spindle skills discovered)")
        return 0
    name_width = max(len(s.name) for s in skills)
    pkg_width = max(len(s.package) for s in skills)
    for s in skills:
        print(f"  {s.name:<{name_width}}  {s.package:<{pkg_width}}  {s.skill_dir}")
    return 0


def cmd_skill_show(args) -> int:
    result = skills_mod.read_skill_metadata(args.name)
    if result is None:
        print(f"no skill {args.name!r}", file=sys.stderr)
        return 1
    fm, spec = result
    print(f"  {'name':<16} {spec.name}")
    print(f"  {'package':<16} {spec.package}")
    print(f"  {'skill_dir':<16} {spec.skill_dir}")
    if fm:
        for key in sorted(fm.keys()):
            if key not in ("name",):
                print(f"  {key:<16} {fm[key]}")
    return 0


# ---- rate ---------------------------------------------------------------


def cmd_rate(args) -> int:
    thumbs = "up" if args.thumbs_up else "down"
    try:
        fb, ld = rate_mod.rate(args.skill, thumbs, args.note or "")
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"feedback → {fb}")
    print(f"ledger   → {ld}")
    return 0


# ---- capability ---------------------------------------------------------


def cmd_capability_list(_args) -> int:
    caps = capabilities_mod.list_capabilities()
    if not caps:
        print("(no capabilities declared)")
        return 0
    cap_width = max(len(cap) for cap in caps)
    for cap in sorted(caps.keys()):
        packages = ", ".join(caps[cap])
        print(f"  {cap:<{cap_width}}  {packages}")
    return 0


def cmd_capability_show(args) -> int:
    result = capabilities_mod.show_capability(args.name)
    if not result["packages"]:
        print(f"no capability {args.name!r}", file=sys.stderr)
        return 1
    print(f"  {'name':<16} {result['name']}")
    if result["packages"]:
        print(f"  {'packages':<16} {result['packages'][0]}")
        for pkg in result["packages"][1:]:
            print(f"  {'':<16} {pkg}")
    else:
        print(f"  {'packages':<16} (none)")
    if result["sources"]:
        for src in result["sources"]:
            peer = src.get("peer", "?")
            url = src.get("url", "?")
            transposed = src.get("transposed_at", "?")
            notes = src.get("notes", "")
            notes_str = f"  {notes}" if notes else ""
            print(
                f"  {'source':<16} {peer}  {url}  (transposed {transposed}){notes_str}"
            )
    return 0


# ---- evaluation ---------------------------------------------------------


def cmd_eval_validate(args) -> int:
    try:
        manifest = evaluation_mod.load_manifest(args.manifest)
        findings = evaluation_mod.validate_manifest(args.manifest)
    except evaluation_mod.EvaluationError as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(evaluation_mod.manifest_as_dict(manifest), indent=2))
    for finding in findings:
        print(f"warning: {finding}", file=sys.stderr)
    return 0 if not findings else 2


def cmd_eval_run(args) -> int:
    try:
        manifest = evaluation_mod.load_manifest(args.manifest)
        output, receipt = evaluation_mod.run_evaluation(
            manifest,
            split=args.split,
            receipt_path=args.receipt,
        )
    except evaluation_mod.EvaluationError as exc:
        print(f"evaluation error: {exc}", file=sys.stderr)
        return 1
    for name, summary in receipt["summaries"].items():
        if summary["runs"]:
            print(
                f"{name}: cases={summary['cases']} errors={summary['errors']} "
                f"baseline={summary['mean_score']['baseline']} "
                f"variant={summary['mean_score']['variant']} delta={summary['delta']}"
            )
    promotion = receipt["promotion"]
    status = "eligible" if promotion["eligible"] else "blocked"
    reasons = ",".join(promotion["reasons"]) or "held-out-improvement"
    print(f"promotion: {status} ({reasons})")
    print(f"receipt: {output}")
    return 0 if not any(run["status"] == "error" for run in receipt["runs"]) else 2


def cmd_eval_show(args) -> int:
    try:
        receipt = evaluation_mod.load_receipt(args.receipt)
    except evaluation_mod.EvaluationError as exc:
        print(f"receipt error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    print(f"evaluation: {receipt.get('evaluation_id', '?')}")
    print(f"run:        {receipt.get('run_id', '?')}")
    print(
        f"skill:      {receipt.get('skill', '?')} @ {receipt.get('skill_sha256', '?')[:12]}"
    )
    for name, summary in receipt.get("summaries", {}).items():
        if summary.get("runs"):
            print(
                f"{name:<11} cases={summary['cases']} errors={summary['errors']} "
                f"delta={summary['delta']}"
            )
    promotion = receipt.get("promotion", {})
    print(f"promotion:  {'eligible' if promotion.get('eligible') else 'blocked'}")
    for reason in promotion.get("reasons", []):
        print(f"  - {reason}")
    return 0


def _coordinate_arguments(values: tuple[str, ...] | list[str] | None):
    coordinate: list[tuple[str, str]] = []
    for value in values or ():
        key, separator, item = value.partition("=")
        if not separator or not key.strip() or not item.strip():
            raise minimalism_mod.MinimalismError(
                "coordinate values must use non-empty KEY=VALUE syntax"
            )
        coordinate.append((key.strip(), item.strip()))
    if len(dict(coordinate)) != len(coordinate):
        raise minimalism_mod.MinimalismError("coordinate keys must be unique")
    return tuple(sorted(coordinate))


def cmd_matrix_validate(args) -> int:
    try:
        manifest = minimalism_mod.load_manifest(args.manifest)
    except minimalism_mod.MinimalismError as exc:
        print(f"invalid minimalism experiment: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(manifest.to_dict(), indent=2, sort_keys=True))
    return 0


def cmd_matrix_run(args) -> int:
    try:
        manifest = minimalism_mod.load_manifest(args.manifest)
        output, receipt = minimalism_mod.run_evaluation(
            manifest, split=args.split, receipt_path=args.receipt
        )
    except minimalism_mod.MinimalismError as exc:
        print(f"minimalism evaluation error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    else:
        decision = receipt["distillation_gate"]
        outcome = "eligible" if decision["eligible"] else "blocked"
        print(f"distillation: {outcome}")
        print(f"  candidate: {decision['candidate_arm']}")
        print(f"  reference: {decision['reference_arm']}")
        print(f"  lower bound: {decision['one_sided_95_lower_bound']}")
        for reason in decision["reasons"]:
            print(f"  - {reason}")
        print(f"receipt: {output}")
    return 0 if not any(run["status"] == "error" for run in receipt["runs"]) else 2


def cmd_matrix_freshness(args) -> int:
    try:
        receipt = minimalism_mod.load_receipt(args.receipt)
        coordinate = _coordinate_arguments(args.coordinate)
        report = minimalism_mod.receipt_freshness(receipt, coordinate)
    except minimalism_mod.MinimalismError as exc:
        print(f"minimalism freshness error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"freshness: {report['decision']}")
        for key in report["changed"]:
            print(f"  changed: {key}")
        for key in report["missing_current_coordinates"]:
            print(f"  missing: {key}")
    return 0 if report["fresh"] else 2


def cmd_distillation(args) -> int:
    try:
        if args.distill_action == "classify":
            payload = minimalism_mod.classify_material(args.package)
        elif args.distill_action == "plan":
            payload = minimalism_mod.distillation_plan(args.package)
        else:
            payload = minimalism_mod.stage_trial_revision(
                args.package,
                args.proposal,
                args.destination,
                dry_run=args.dry_run,
            )
    except (minimalism_mod.MinimalismError, lifecycle_mod.LifecycleError) as exc:
        print(f"distillation {args.distill_action} blocked: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.distill_action == "classify":
        print(f"classification: {payload['classification_id']}")
        for category, count in payload["counts"].items():
            if count:
                print(f"  {category}: {count}")
    elif args.distill_action == "plan":
        print(f"distillation plan: {payload['plan_id']}")
        for proposal in payload["proposals"]:
            print(f"  {proposal['proposal_id']}  {proposal['action']} {proposal['path']}")
    else:
        print(f"distillation action: {payload['action']}")
        print(f"  destination: {payload['destination']}")
    return 0


# ---- chippability -------------------------------------------------------


def _append_candidate(path: Path, report: chippability_mod.ChippabilityReport) -> None:
    """Append one chip candidate in the chip candidates.jsonl convention.

    Written by hand — spindle imports nothing from chip. The record shape is
    the public convention documented at https://github.com/lavallee/chip
    (docs/candidates.md): {observedAt, shape, occurrenceRefs, fixtureRefs,
    count, notedBy}. ``fixtureRefs`` is left empty here: harvesting real inputs
    as held-out fixtures is a separate, situated act, not something a static
    scan can do."""
    record = {
        "observedAt": _now_iso(),
        "shape": report.draft_shape,
        "occurrenceRefs": [f"skill:{report.package}/{report.skill}"],
        "fixtureRefs": [],
        "count": 1,
        "notedBy": "spindle:chippability",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _append_chippability_ledger(report: chippability_mod.ChippabilityReport) -> None:
    """Touchpoint C: append {at, skill, package, score, hint} to the ledger."""
    from .paths import chippability_ledger_path

    record = {
        "at": _now_iso(),
        "skill": report.skill,
        "package": report.package,
        "score": report.score,
        "hint": report.classification_hint,
    }
    p = chippability_ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def cmd_chippability(args) -> int:
    """Score every skill under a package-dir or skill-dir for chip-shape.

    Static only — regex/line scans over SKILL.md + bundled files. No chip import,
    no chip host. Appends a chippability ledger record per skill (touchpoint C),
    and, with --emit-candidates, appends chip candidates for the chip-candidate
    skills in the public candidates.jsonl convention."""
    root = Path(args.target)
    if not root.exists():
        print(f"no such path: {root}", file=sys.stderr)
        return 1
    skill_dirs = chippability_mod.discover_skill_dirs(root)
    if not skill_dirs:
        print(f"no skills found under {root}", file=sys.stderr)
        return 1
    package = chippability_mod.package_name_for(root)

    reports = [chippability_mod.assess_skill(d, package=package) for d in skill_dirs]
    reports.sort(key=lambda r: (-r.score, r.skill))

    emit_path = Path(args.emit_candidates) if args.emit_candidates else None
    emitted = 0
    for report in reports:
        _append_chippability_ledger(report)
        if emit_path is not None and report.classification_hint == "chip-candidate":
            _append_candidate(emit_path, report)
            emitted += 1

    if args.json:
        payload = [
            {
                "skill": r.skill,
                "package": r.package,
                "score": r.score,
                "f": r.f,
                "g": r.g,
                "classification_hint": r.classification_hint,
                "draft_shape": r.draft_shape,
                "signals": [
                    {
                        "name": s.name,
                        "polarity": s.polarity,
                        "evidence_line": s.evidence_line,
                    }
                    for s in r.signals
                ],
            }
            for r in reports
        ]
        print(json.dumps(payload, indent=2))
        return 0

    name_width = max(len(r.skill) for r in reports)
    print(f"  {'skill':<{name_width}}  {'score':>5}  {'f':>3} {'g':>3}  hint")
    for r in reports:
        print(
            f"  {r.skill:<{name_width}}  {r.score:>5}  {r.f:>3} {r.g:>3}  {r.classification_hint}"
        )
    print(f"\nassessed {len(reports)} skill(s) in {package!r}; ledger updated.")
    if emit_path is not None:
        print(f"emitted {emitted} chip candidate(s) → {emit_path}")
    return 0


# ---- main ---------------------------------------------------------------


def _add_candidate_source_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--offline",
        action="store_true",
        help="use only verified cached source objects and snapshots",
    )
    parser.add_argument(
        "--allow-executable",
        action="store_true",
        help="approve bundled executable and script-like resources for this operation",
    )
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="approve statically indicated network authority for this operation",
    )
    parser.add_argument(
        "--allow-credentials",
        action="store_true",
        help="approve statically indicated credential access for this operation",
    )
    parser.add_argument(
        "--allow-tool",
        action="append",
        help="approve one declared tool dependency (repeatable)",
    )
    parser.add_argument(
        "--attestation",
        action="append",
        help="attach an opaque third-party artifact as NAME=PATH (repeatable)",
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="spindle",
        description=(
            "Spindle — evidence-bearing skill inspection, composition, "
            "activation, evaluation, and custody"
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("status", help="show install + preempt state")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("preempt", help="add preempt snippet to ~/.claude/CLAUDE.md")
    sp.set_defaults(func=cmd_preempt)
    sp = sub.add_parser("unpreempt", help="remove preempt snippet")
    sp.set_defaults(func=cmd_unpreempt)

    sp = sub.add_parser("peers", help="manage peer registry")
    pps = sp.add_subparsers(dest="peers_cmd", required=True)
    pps.add_parser("list").set_defaults(func=cmd_peers_list)
    add = pps.add_parser("add")
    add.add_argument("slug")
    add.add_argument("--name")
    add.add_argument("--url", required=True)
    add.add_argument(
        "--kind", default="github", choices=["github", "blog", "rss", "other"]
    )
    add.add_argument("--our-take")
    add.add_argument("--notes")
    add.set_defaults(func=cmd_peers_add)
    rm = pps.add_parser("remove")
    rm.add_argument("slug")
    rm.set_defaults(func=cmd_peers_remove)

    sp = sub.add_parser("verdict", help="manage verdicts")
    vds = sp.add_subparsers(dest="verdict_cmd", required=True)
    vds.add_parser("list").set_defaults(func=cmd_verdict_list)
    vds.add_parser(
        "candidates", help="list draft verdicts a scout pass left for review"
    ).set_defaults(func=cmd_verdict_candidates)
    show = vds.add_parser("show")
    show.add_argument("slug")
    show.set_defaults(func=cmd_verdict_show)
    add = vds.add_parser("add")
    add.add_argument("slug")
    add.add_argument("--source", required=True)
    add.add_argument("--url")
    add.add_argument(
        "--verdict",
        default="tracking",
        choices=["tracking", "borrow", "graft", "ignore", "try"],
    )
    add.add_argument(
        "--status",
        default="candidate",
        choices=["candidate", "in-use", "rejected", "superseded"],
    )
    add.add_argument("--body")
    add.add_argument("--body-file")
    add.add_argument(
        "--chippable", help="chip-shape judgment (open text; e.g. yes/no/candidate)"
    )
    add.add_argument("--chip-alias", help="associated chip alias (advisory)")
    add.set_defaults(func=cmd_verdict_add)

    sp = sub.add_parser(
        "doctrine", help="show/validate the active distribution's doctrine"
    )
    dcs = sp.add_subparsers(dest="doctrine_cmd", required=True)
    dcs.add_parser(
        "show", help="print preferences, absolutes, meta-principles"
    ).set_defaults(func=cmd_doctrine_show)
    dcs.add_parser("validate", help="check the doctrine is well-formed").set_defaults(
        func=cmd_doctrine_validate
    )

    sp = sub.add_parser("appclass", help="classify a repo's app-type (Path B)")
    sp.add_argument("path", help="path to a local repo checkout")
    sp.add_argument(
        "--kind", help="project registry kind, if known (library/service/...)"
    )
    sp.set_defaults(func=cmd_appclass)

    sp = sub.add_parser(
        "bind", help="compose + materialize a surface's skills (channel binder)"
    )
    sp.add_argument("repo", help="path to the target repo/surface checkout")
    sp.add_argument("--name", help="surface name (defaults to repo dir name)")
    sp.add_argument(
        "--harness",
        default="claude",
        help="claude | codex | pi | hermes (default claude); hermes "
        "materializes into the global ~/.hermes/skills/spindle dir",
    )
    sp.add_argument(
        "--model",
        default=None,
        help="model/tier to tune render density for (e.g. frontier); "
        "None = no model tuning",
    )
    sp.add_argument(
        "--autonomy",
        default="deterministic",
        choices=["deterministic", "self_evolving"],
    )
    sp.add_argument("--kind", help="project registry kind, if known")
    sp.add_argument(
        "--force", action="store_true", help="materialize despite lint problems"
    )
    sp.add_argument(
        "--no-render",
        action="store_true",
        help="skip dialect rendering (verbatim skills)",
    )
    sp.add_argument(
        "--dry-run", action="store_true", help="show the plan, write nothing"
    )
    sp.set_defaults(func=cmd_bind)

    sp = sub.add_parser(
        "realize",
        help="resolve one installed skill for an explicit agent session",
    )
    sp.add_argument("skill", help="installed skill name or path to a skill directory")
    sp.add_argument("--session-id", help="agent-session id (or SPINDLE_SESSION_ID)")
    sp.add_argument(
        "--harness",
        help="runtime harness, e.g. codex or claude (or SPINDLE_HARNESS)",
    )
    sp.add_argument(
        "--model",
        help="assert the same requested and served model (convenience shorthand)",
    )
    sp.add_argument("--requested-model", help="model requested by the task router")
    sp.add_argument("--served-model", help="model identity actually served")
    sp.add_argument("--effort", help="reasoning/effort level actually granted")
    sp.add_argument("--role", help="agent role, e.g. reviewer or explorer")
    sp.add_argument("--harness-build", help="observable harness build/version")
    sp.add_argument(
        "--toolset-digest", help="digest naming the available tool envelope"
    )
    sp.add_argument("--policy-digest", help="digest naming the active policy envelope")
    sp.add_argument("--memory-policy", help="memory or compaction policy coordinate")
    sp.add_argument(
        "--strict",
        action="store_true",
        help="exit 2 unless an evaluated profile matches",
    )
    sp.add_argument(
        "--json", action="store_true", help="emit the realization result as JSON"
    )
    sp.set_defaults(func=cmd_realize)

    sp = sub.add_parser(
        "inspect",
        help="build a read-only intent card for a local or installed candidate",
    )
    sp.add_argument(
        "reference",
        help="skill path, installed skill/package, or <package>#<skill>",
    )
    sp.add_argument(
        "--for",
        dest="intent",
        help="task intent used only for separately labeled fit analysis",
    )
    sp.add_argument("--repo", default=".", help="surface path (default current dir)")
    sp.add_argument(
        "--here", action="store_const", const=".", dest="repo", help="use current dir"
    )
    sp.add_argument("--name", help="surface name (defaults to repo dir name)")
    sp.add_argument("--harness", default="claude", choices=["claude", "codex"])
    _add_candidate_source_options(sp)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_inspect)

    sp = sub.add_parser(
        "borrow",
        help="temporarily add an exact local candidate to desired state",
    )
    sp.add_argument(
        "reference",
        help="skill path, installed skill/package, or <package>#<skill>",
    )
    sp.add_argument(
        "--until", required=True, help="expiry instant or duration such as 30m, 2h, 7d"
    )
    sp.add_argument("--repo", default=".", help="surface path (default current dir)")
    sp.add_argument(
        "--here", action="store_const", const=".", dest="repo", help="use current dir"
    )
    sp.add_argument("--name", help="surface name (defaults to repo dir name)")
    sp.add_argument("--harness", default="claude", choices=["claude", "codex"])
    sp.add_argument("--model", help="configured model coordinate for activation evidence")
    sp.add_argument(
        "--agent",
        action="append",
        help="agent identity permitted by the lease (repeatable; default any)",
    )
    sp.add_argument(
        "--posture",
        default="read-only",
        choices=["read-only", "sandboxed", "full"],
        help="authority posture (default read-only)",
    )
    _add_candidate_source_options(sp)
    sp.add_argument("--dry-run", action="store_true", help="show the exact plan only")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_borrow)

    sp = sub.add_parser(
        "try",
        help="run one disposable read-only session with an exact local candidate",
    )
    sp.add_argument(
        "reference",
        help="skill path, installed skill/package, or <package>#<skill>",
    )
    sp.add_argument("--task-file", required=True, help="UTF-8 task prompt file")
    sp.add_argument("--repo", default=".", help="surface path (default current dir)")
    sp.add_argument(
        "--here", action="store_const", const=".", dest="repo", help="use current dir"
    )
    sp.add_argument("--name", help="surface name (defaults to repo dir name)")
    sp.add_argument("--harness", required=True, choices=["claude", "codex"])
    sp.add_argument("--model", help="model passed to the disposable harness run")
    _add_candidate_source_options(sp)
    sp.add_argument("--dry-run", action="store_true", help="show the lease and launch plan")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_try)

    sp = sub.add_parser(
        "release", help="release an active lease and remove only its owned projection"
    )
    sp.add_argument("lease_id")
    sp.add_argument("--repo", default=".", help="surface path (default current dir)")
    sp.add_argument(
        "--here", action="store_const", const=".", dest="repo", help="use current dir"
    )
    sp.add_argument("--harness", choices=["claude", "codex"])
    sp.add_argument("--dry-run", action="store_true", help="show cleanup plan only")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_release)

    sp = sub.add_parser(
        "source", help="inspect and control package source trust state"
    )
    source_commands = sp.add_subparsers(dest="source_action", required=True)
    for action in ("quarantine", "unquarantine"):
        source = source_commands.add_parser(
            action,
            help=f"{action} an exact package digest for future lease creation",
        )
        source.add_argument("package", help="package digest or resolvable candidate reference")
        source.add_argument("--reason", required=True, help="durable policy decision reason")
        source.add_argument("--actor", help="decision owner (defaults to current user)")
        source.add_argument("--offline", action="store_true")
        source.add_argument("--dry-run", action="store_true")
        source.add_argument("--json", action="store_true")
        source.set_defaults(func=cmd_source_quarantine)
    source = source_commands.add_parser(
        "status", help="show current quarantine policy for a package"
    )
    source.add_argument("package", help="package digest or resolvable candidate reference")
    source.add_argument("--offline", action="store_true")
    source.add_argument("--json", action="store_true")
    source.set_defaults(func=cmd_source_status)

    sp = sub.add_parser(
        "adopt",
        help="promote the exact bytes from a successful trial into durable ownership",
    )
    sp.add_argument("lease_id", help="content identity of the successful trial lease")
    sp.add_argument("--repo", default=".", help="surface path (default current dir)")
    sp.add_argument(
        "--here", action="store_const", const=".", dest="repo", help="use current dir"
    )
    sp.add_argument("--name", help="surface name (defaults to repo dir name)")
    sp.add_argument("--scope", default="repo", choices=["repo"])
    sp.add_argument("--owner", help="adoption owner (defaults to current user)")
    sp.add_argument(
        "--reason",
        default="successful trial promoted",
        help="durable rationale for promotion",
    )
    sp.add_argument(
        "--update-channel",
        help="refreshable source reference; pinned trials otherwise default to manual",
    )
    sp.add_argument(
        "--authority-ceiling",
        choices=["read-only", "sandboxed", "full"],
        help="maximum authority allowed after adoption (defaults to trial posture)",
    )
    sp.add_argument(
        "--retirement-policy",
        default="manual",
        choices=["manual", "source-revocation"],
    )
    sp.add_argument(
        "--evaluation-claim",
        action="append",
        help="behavioral evidence identity earned by these exact bytes (repeatable)",
    )
    sp.add_argument(
        "--harness-build",
        help="exact harness build for organization policy and adoption evidence",
    )
    sp.add_argument("--dry-run", action="store_true", help="show the exact change only")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_adopt)

    for action in ("disable", "enable", "deprecate", "retire", "rollback"):
        sp = sub.add_parser(action, help=f"{action} a durably adopted skill")
        sp.add_argument("skill")
        sp.add_argument("--repo", default=".", help="surface path")
        sp.add_argument(
            "--here",
            action="store_const",
            const=".",
            dest="repo",
            help="use current dir",
        )
        sp.add_argument("--name", help="surface name (defaults to repo dir name)")
        sp.add_argument("--harness", default="codex", choices=["claude", "codex"])
        sp.add_argument("--reason", required=True, help="durable lifecycle rationale")
        sp.add_argument("--actor", help="decision owner (defaults to current user)")
        sp.add_argument("--dry-run", action="store_true", help="show the exact change only")
        sp.add_argument("--json", action="store_true")
        sp.set_defaults(func=cmd_maintenance_action, operation=action)

    sp = sub.add_parser(
        "health",
        help="report adoption freshness, evidence coverage, state, and runtime drift",
    )
    sp.add_argument("--repo", default=".", help="surface path")
    sp.add_argument(
        "--here", action="store_const", const=".", dest="repo", help="use current dir"
    )
    sp.add_argument("--name", help="surface name (defaults to repo dir name)")
    sp.add_argument("--harness", default="codex", choices=["claude", "codex"])
    sp.add_argument("--model", help="currently served model coordinate")
    sp.add_argument("--harness-build", help="current harness build/version")
    sp.add_argument("--toolset-digest", help="current tool envelope digest")
    sp.add_argument("--policy-digest", help="current permission/policy digest")
    sp.add_argument("--source-revision", help="current upstream source revision")
    sp.add_argument("--package-digest", help="current selected package digest")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_health)

    sp = sub.add_parser("update", help="plan or trial refreshes for active adoptions")
    update_commands = sp.add_subparsers(dest="update_action", required=True)
    update = update_commands.add_parser(
        "plan", help="resolve update channels without changing desired state"
    )
    update.add_argument("--repo", default=".", help="surface path")
    update.add_argument(
        "--here", action="store_const", const=".", dest="repo", help="use current dir"
    )
    update.add_argument("--name", help="surface name (defaults to repo dir name)")
    update.add_argument("--harness", default="codex", choices=["claude", "codex"])
    _add_candidate_source_options(update)
    update.add_argument("--json", action="store_true")
    update.set_defaults(func=cmd_update_plan)

    update = update_commands.add_parser(
        "try", help="run changed bytes beside the incumbent in a disposable session"
    )
    update.add_argument("skill")
    update.add_argument("--task-file", required=True, help="UTF-8 task prompt file")
    update.add_argument("--repo", default=".", help="surface path")
    update.add_argument(
        "--here", action="store_const", const=".", dest="repo", help="use current dir"
    )
    update.add_argument("--name", help="surface name (defaults to repo dir name)")
    update.add_argument("--harness", default="codex", choices=["claude", "codex"])
    update.add_argument("--model", help="model passed to the disposable harness run")
    _add_candidate_source_options(update)
    update.add_argument("--dry-run", action="store_true")
    update.add_argument("--json", action="store_true")
    update.set_defaults(func=cmd_update_try)

    sp = sub.add_parser("vendor", help="plan a move into owned local custody")
    sp.add_argument("skill")
    sp.add_argument("--destination", required=True)
    sp.add_argument("--repo", default=".")
    sp.add_argument("--here", action="store_const", const=".", dest="repo")
    sp.add_argument("--harness", default="codex", choices=["claude", "codex"])
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_custody_path, path_action="vendor")

    sp = sub.add_parser("distill", help="plan evidence-backed skill minimization")
    sp.add_argument("skill")
    sp.add_argument("--repo", default=".")
    sp.add_argument("--here", action="store_const", const=".", dest="repo")
    sp.add_argument("--harness", default="codex", choices=["claude", "codex"])
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_custody_path, path_action="distill")

    sp = sub.add_parser(
        "adapter", help="negotiate capabilities and certify exact harness builds"
    )
    adapter_commands = sp.add_subparsers(dest="adapter_action", required=True)
    adapter = adapter_commands.add_parser(
        "matrix", help="show fail-closed capabilities for one named build"
    )
    adapter.add_argument("--harness", required=True, choices=["claude", "codex"])
    adapter.add_argument("--build", required=True)
    adapter.add_argument("--observation", help="conformance observation JSON")
    adapter.add_argument(
        "--require",
        action="append",
        help="required capability or CAPABILITY:partial (repeatable)",
    )
    adapter.add_argument("--json", action="store_true")
    adapter.set_defaults(func=cmd_adapter_matrix)
    adapter = adapter_commands.add_parser(
        "certify", help="write an evidence-backed build certification"
    )
    adapter.add_argument("observation")
    adapter.add_argument("--dry-run", action="store_true")
    adapter.add_argument("--json", action="store_true")
    adapter.set_defaults(func=cmd_adapter_certify)
    adapter = adapter_commands.add_parser(
        "verify", help="verify a content-addressed certification receipt"
    )
    adapter.add_argument("certification")
    adapter.add_argument("--json", action="store_true")
    adapter.set_defaults(func=cmd_adapter_verify)

    sp = sub.add_parser(
        "policy", help="inspect and audit organization lifecycle requirements"
    )
    policy_commands = sp.add_subparsers(dest="policy_action", required=True)
    for action in ("show", "check"):
        policy = policy_commands.add_parser(action)
        policy.add_argument("--repo", default=".")
        policy.add_argument("--here", action="store_const", const=".", dest="repo")
        policy.add_argument(
            "--harness", default="codex", choices=["claude", "codex"]
        )
        policy.add_argument("--harness-build")
        policy.add_argument("--json", action="store_true")
        policy.set_defaults(func=cmd_policy)

    sp = sub.add_parser(
        "harness",
        help="install and drive Spindle from inside Codex or Claude Code",
    )
    harness_commands = sp.add_subparsers(dest="harness_action", required=True)
    for action, action_help, action_func in (
        (
            "setup",
            "project the Spindle operator skill and native startup hooks",
            cmd_harness_setup,
        ),
        (
            "status",
            "inspect operator version, projection custody, and hook state",
            cmd_harness_status,
        ),
        (
            "context",
            "emit the compact current-state and action contract for an agent",
            cmd_harness_context,
        ),
        (
            "remove",
            "remove only the exactly owned operator projection and hook fragments",
            cmd_harness_remove,
        ),
    ):
        harness_parser = harness_commands.add_parser(action, help=action_help)
        harness_parser.add_argument(
            "--harness",
            choices=["claude", "codex"],
            required=action != "context",
            help=(
                "active harness; context auto-detects it from the session when omitted"
            ),
        )
        harness_parser.add_argument(
            "--repo", default=".", help="surface path (default current dir)"
        )
        harness_parser.add_argument(
            "--here",
            action="store_const",
            const=".",
            dest="repo",
            help="use current dir",
        )
        harness_parser.add_argument("--json", action="store_true")
        if action == "setup":
            harness_parser.add_argument(
                "--name", help="surface name (defaults to repo dir name)"
            )
        if action in {"setup", "remove"}:
            harness_parser.add_argument(
                "--dry-run", action="store_true", help="plan without writing"
            )
        harness_parser.set_defaults(func=action_func)

    sp = sub.add_parser(
        "bootstrap",
        help="plan, verify, and optionally reconcile startup skill state",
    )
    sp.add_argument("--harness", choices=["claude", "codex"])
    sp.add_argument(
        "--hook",
        choices=["claude", "codex"],
        help="run as a post-discovery native hook observer",
    )
    mode = sp.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="inspect and attest without mutation (default)",
    )
    mode.add_argument(
        "--reconcile-owned",
        action="store_true",
        help="apply only exact ownership-proven repairs",
    )
    sp.add_argument("--repo", help="surface path (default payload cwd/current dir)")
    sp.add_argument(
        "--here", action="store_const", const=".", dest="repo", help="use current dir"
    )
    sp.add_argument("--name", help="surface name (defaults to repo dir name)")
    sp.add_argument("--event", help="startup event source recorded in the receipt")
    sp.add_argument("--adapter-build", help="observed harness/adapter build")
    sp.add_argument(
        "--already-discovered",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_bootstrap)

    sp = sub.add_parser(
        "launch",
        help="reconcile startup state before launching a reference harness",
    )
    sp.add_argument("harness", choices=["claude", "codex"])
    sp.add_argument("--repo", default=".", help="surface path (default current dir)")
    sp.add_argument(
        "--here", action="store_const", const=".", dest="repo", help="use current dir"
    )
    sp.add_argument("--name", help="surface name (defaults to repo dir name)")
    sp.add_argument("--adapter-build", help="observed harness build")
    sp.set_defaults(func=cmd_launch, harness_args=[])

    sp = sub.add_parser(
        "hooks",
        help="plan, install, inspect, or remove stable native startup hook kits",
    )
    hook_sub = sp.add_subparsers(dest="hooks_cmd", required=True)
    for hook_command, hook_help, hook_func in (
        ("plan", "preview a structural hook configuration merge", cmd_hooks_plan),
        ("install", "install and record owned hook fragments", cmd_hooks_install),
        (
            "status",
            "compare definitions, controls, and observed heartbeat",
            cmd_hooks_status,
        ),
        ("remove", "remove only exactly owned hook fragments", cmd_hooks_remove),
    ):
        hook_parser = hook_sub.add_parser(hook_command, help=hook_help)
        hook_parser.add_argument(
            "--harness", required=True, choices=["claude", "codex"]
        )
        hook_parser.add_argument("--scope", default="repo", choices=["repo", "user"])
        hook_parser.add_argument(
            "--repo", default=".", help="surface path (default current dir)"
        )
        hook_parser.add_argument(
            "--here",
            action="store_const",
            const=".",
            dest="repo",
            help="use current dir",
        )
        hook_parser.add_argument("--json", action="store_true")
        if hook_command in {"install", "remove"}:
            hook_parser.add_argument(
                "--dry-run", action="store_true", help="plan without writing"
            )
        if hook_command == "status":
            hook_parser.add_argument(
                "--effective",
                action="store_true",
                help="include configuration controls and observed heartbeat",
            )
        hook_parser.set_defaults(func=hook_func)

    sp = sub.add_parser(
        "conflict",
        help="record or revoke exact, explicit decisions about foreign skill collisions",
    )
    conflict_sub = sp.add_subparsers(dest="conflict_cmd", required=True)
    for conflict_command, conflict_help, conflict_func in (
        ("allow", "preserve one exact observed foreign conflict", cmd_conflict_allow),
        ("list", "list active exact conflict decisions", cmd_conflict_list),
        (
            "revoke",
            "remove a decision from desired state but retain history",
            cmd_conflict_revoke,
        ),
    ):
        conflict_parser = conflict_sub.add_parser(conflict_command, help=conflict_help)
        if conflict_command == "allow":
            conflict_parser.add_argument("skill")
            conflict_parser.add_argument(
                "--path",
                help="exact observed path (required when a name has multiple conflicts)",
            )
            conflict_parser.add_argument(
                "--reason", required=True, help="why this exact conflict is acceptable"
            )
        elif conflict_command == "revoke":
            conflict_parser.add_argument("decision_id")
        conflict_parser.add_argument(
            "--repo", default=".", help="surface path (default current dir)"
        )
        conflict_parser.add_argument(
            "--here",
            action="store_const",
            const=".",
            dest="repo",
            help="use current dir",
        )
        conflict_parser.add_argument("--name", help="surface name")
        conflict_parser.add_argument(
            "--harness", default="claude", choices=["claude", "codex"]
        )
        conflict_parser.add_argument("--json", action="store_true")
        if conflict_command in {"allow", "revoke"}:
            conflict_parser.add_argument("--dry-run", action="store_true")
        conflict_parser.set_defaults(func=conflict_func)

    sp = sub.add_parser(
        "inventory",
        help="inspect the effective skill inventory across harness scopes",
    )
    sp.add_argument(
        "--effective",
        action="store_true",
        help="include every locally observable harness discovery scope",
    )
    sp.add_argument("--repo", default=".", help="surface path (default current dir)")
    sp.add_argument(
        "--here", action="store_const", const=".", dest="repo", help="use current dir"
    )
    sp.add_argument("--name", help="surface name (defaults to repo dir name)")
    sp.add_argument("--harness", default="claude", choices=["claude", "codex"])
    sp.add_argument("--json", action="store_true")
    sp.add_argument(
        "--strict", action="store_true", help="exit 2 when blocking drift exists"
    )
    sp.set_defaults(func=cmd_inventory)

    sp = sub.add_parser("why", help="explain why and where an effective skill appears")
    sp.add_argument("skill")
    sp.add_argument(
        "--effective",
        action="store_true",
        help="explain the complete effective harness view",
    )
    sp.add_argument("--repo", default=".", help="surface path (default current dir)")
    sp.add_argument(
        "--here", action="store_const", const=".", dest="repo", help="use current dir"
    )
    sp.add_argument("--name", help="surface name (defaults to repo dir name)")
    sp.add_argument("--harness", default="claude", choices=["claude", "codex"])
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_why)

    sp = sub.add_parser("diff", help="show desired-versus-effective skill state")
    sp.add_argument(
        "--effective",
        action="store_true",
        help="compare the complete effective harness inventory",
    )
    sp.add_argument("--repo", default=".", help="surface path (default current dir)")
    sp.add_argument(
        "--here", action="store_const", const=".", dest="repo", help="use current dir"
    )
    sp.add_argument("--name", help="surface name (defaults to repo dir name)")
    sp.add_argument("--harness", default="claude", choices=["claude", "codex"])
    sp.add_argument("--json", action="store_true")
    sp.add_argument(
        "--strict", action="store_true", help="exit 2 when blocking drift exists"
    )
    sp.set_defaults(func=cmd_diff_effective)

    sp = sub.add_parser(
        "doctor", help="verify startup skill state and optionally reconcile owned drift"
    )
    sp.add_argument(
        "--startup",
        action="store_true",
        help="run the startup desired/effective-state audit",
    )
    sp.add_argument("--repo", default=".", help="surface path (default current dir)")
    sp.add_argument(
        "--here", action="store_const", const=".", dest="repo", help="use current dir"
    )
    sp.add_argument("--name", help="surface name (defaults to repo dir name)")
    sp.add_argument("--harness", default="claude", choices=["claude", "codex"])
    sp.add_argument(
        "--reconcile-owned",
        action="store_true",
        help="remove only stale projections with exact ownership receipts",
    )
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_doctor_startup)

    sp = sub.add_parser("unbind", help="remove a surface's materialized skills")
    sp.add_argument("repo", help="path to the target repo/surface checkout")
    sp.add_argument("--name", help="surface name (defaults to repo dir name)")
    sp.add_argument("--harness", default="claude")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_unbind)

    sp = sub.add_parser(
        "advance", help="advance team: precompute compositions for all surfaces"
    )
    avs = sp.add_subparsers(dest="advance_cmd", required=True)
    ar = avs.add_parser("run", help="bind every configured surface ahead of time")
    ar.add_argument(
        "--from-registry",
        nargs="?",
        const=True,
        default=False,
        metavar="PROJECTS_DIR",
        help="enumerate surfaces from a TOML project registry (default $SPINDLE_PROJECTS_DIR)",
    )
    ar.add_argument("--force", action="store_true")
    ar.add_argument("--no-render", action="store_true")
    ar.add_argument("--dry-run", action="store_true")
    ar.set_defaults(func=cmd_advance_run)

    sp = sub.add_parser(
        "liaison", help="the in-repo edge: articulate + log a surface's needs"
    )
    lns = sp.add_subparsers(dest="liaison_cmd", required=True)
    lr = lns.add_parser("request", help="articulate an ad-hoc need as a what-request")
    lr.add_argument("repo", help="path to the surface's repo")
    lr.add_argument("--intent", required=True, help="the ask, in your words")
    lr.add_argument("--outcome", action="append", help="a desired outcome (repeatable)")
    lr.add_argument(
        "--accept", action="append", help="an acceptance criterion (repeatable)"
    )
    lr.add_argument("--name", help="surface name (defaults to repo dir name)")
    lr.add_argument("--harness", default="claude")
    lr.add_argument(
        "--autonomy",
        default="deterministic",
        choices=["deterministic", "self_evolving"],
    )
    lr.add_argument("--kind", help="project registry kind, if known")
    lr.add_argument(
        "--bind",
        action="store_true",
        help="also answer it: bind the surface's current best skills",
    )
    lr.set_defaults(func=cmd_liaison_request)
    ll = lns.add_parser(
        "log", help="show a surface's logged what-requests (demand stream)"
    )
    ll.add_argument("surface")
    ll.set_defaults(func=cmd_liaison_log)

    sp = sub.add_parser("roster", help="upstream skill sources Spindle can broker from")
    rss = sp.add_subparsers(dest="roster_cmd", required=True)
    rl = rss.add_parser("list", help="list roster sources")
    rl.set_defaults(func=cmd_roster_list)

    sp = sub.add_parser(
        "broker",
        help="broker a what-request against external rosters (search → rank → propose)",
    )
    sp.add_argument("intent", help="the ask, in your words")
    sp.add_argument("--repo", help="repo path for app-class self-knowledge (default .)")
    sp.add_argument(
        "--agent", help="agent id — articulate the request for an agent, not a repo"
    )
    sp.add_argument("--harness", default="claude")
    sp.add_argument(
        "--autonomy",
        default="self_evolving",
        choices=["deterministic", "self_evolving"],
    )
    sp.add_argument("--kind", help="project registry kind, if known")
    sp.add_argument("--outcome", action="append", help="a desired outcome (repeatable)")
    sp.add_argument("--limit", type=int, default=3, help="max proposals (default 3)")
    sp.add_argument(
        "--min-fit", type=float, default=0.0, help="drop proposals below this fit"
    )
    sp.add_argument(
        "--acquire",
        type=int,
        metavar="N",
        help="acquire proposal N (transpose stub + record outcome)",
    )
    sp.set_defaults(func=cmd_broker)

    sp = sub.add_parser(
        "acquisitions", help="show the acquisitions ledger (what was brokered)"
    )
    sp.set_defaults(func=cmd_acquisitions)

    sp = sub.add_parser(
        "optimize",
        help="validation-gated skill optimization (SkillOpt): accept edits only if a held-out score improves",
    )
    sp.add_argument("skill", help="path to the SKILL.md to optimize")
    sp.add_argument(
        "--score-cmd",
        help="command that prints a held-out score; candidate at $SPINDLE_SKILL_FILE",
    )
    sp.add_argument(
        "--epochs", type=int, default=5, help="max optimization epochs (default 5)"
    )
    sp.add_argument(
        "--min-improvement",
        type=float,
        default=0.0,
        help="required held-out gain to accept an edit (default any improvement)",
    )
    sp.add_argument(
        "--out", help="where to write the optimized skill (default <skill>.optimized)"
    )
    sp.add_argument(
        "--dry-run", action="store_true", help="run the loop, write nothing"
    )
    sp.set_defaults(func=cmd_optimize)

    sp = sub.add_parser("gate", help="file doctrine gates into the decision queue")
    gts = sp.add_subparsers(dest="gate_cmd", required=True)
    gf = gts.add_parser("file", help="file an spindle:doctrine gate")
    gf.add_argument(
        "--crux", required=True, help="the decision in one or two sentences"
    )
    gf.add_argument("--diff", help="proposed doctrine diff (this-over-that)")
    gf.add_argument("--pilot", help="experiment that would settle it, or 'values call'")
    gf.add_argument("--source", help="peer slug the challenge came from")
    gf.add_argument(
        "--dry-run", action="store_true", help="print the body, don't write"
    )
    gf.set_defaults(func=cmd_gate_file)
    gfr = gts.add_parser(
        "from-result", help="file a gate from an adjudicate-pass result file"
    )
    gfr.add_argument("result", help="path to the adjudicate-pass result (JSON or md)")
    gfr.add_argument("--dry-run", action="store_true")
    gfr.set_defaults(func=cmd_gate_from_result)

    sp = sub.add_parser(
        "scout",
        help="emit runner commands for a scout pass, or apply a pass result",
    )
    sp.add_argument("--slug", help="restrict to one peer (default: all)")
    sp.add_argument(
        "--write-candidates",
        action="store_true",
        help="wire notify callback to write verdicts into the local candidates queue",
    )
    sp.add_argument(
        "--apply-results",
        metavar="FILE",
        help="parse a runner result file and write candidate verdicts into _candidates/",
    )
    sp.set_defaults(func=cmd_scout)

    sp = sub.add_parser(
        "ingest",
        help="ingest an itemized-plan.todos.jsonl into a task sink (topo-ordered)",
    )
    sp.add_argument("path", help="path to the JSONL sidecar")
    sp.add_argument(
        "--task-url",
        default=ingest_mod.DEFAULT_TASK_URL,
        help="optional task service URL (env: SPINDLE_TASK_URL); "
        "default writes to the local JSONL task queue",
    )
    sp.add_argument(
        "--dry-run",
        action="store_true",
        help="parse and topo-sort but don't write to the task sink",
    )
    sp.add_argument(
        "--strict",
        action="store_true",
        help="abort on the first sink failure (default: continue + report)",
    )
    sp.add_argument(
        "--project",
        help="project name to register all entries under (overrides context.cwd and task_id inference). "
        "Original plan slug is stashed in context.plan_slug for traceability.",
    )
    sp.add_argument(
        "--keep-project",
        action="store_true",
        help="don't rewrite the project field — register entries with whatever "
        "the JSONL already has (typically the plan slug). Use this if your "
        "plan deliberately spans multiple projects.",
    )
    sp.add_argument(
        "--reimport",
        action="store_true",
        help="re-ingest entries even if already tracked in the .ingested.json sidecar "
        "(default: skip previously-ingested task_ids to prevent duplicates).",
    )
    sp.set_defaults(func=cmd_ingest)

    sp = sub.add_parser(
        "fleet",
        help="cross-machine ledger sync via a shared git repo",
    )
    fls = sp.add_subparsers(dest="fleet_cmd", required=True)
    fls.add_parser(
        "status", help="list installed distributions per machine"
    ).set_defaults(func=cmd_fleet_status)
    sync = fls.add_parser(
        "sync",
        help="snapshot local events into the fleet repo and pull/push to remote",
    )
    sync.add_argument(
        "--remote",
        help="git URL for the shared fleet repo (sets/updates 'origin' on first run)",
    )
    sync.add_argument(
        "--no-push",
        action="store_true",
        help="skip pull/push (local commit only)",
    )
    sync.set_defaults(func=cmd_fleet_sync)

    sp = sub.add_parser("package", help="list and inspect installed spindle packages")
    pks = sp.add_subparsers(dest="package_cmd", required=True)
    pks.add_parser("list", help="list all installed spindle packages").set_defaults(
        func=cmd_package_list
    )
    show_pkg = pks.add_parser("show", help="show details for a single package")
    show_pkg.add_argument("name", help="package name (e.g. sample-planning)")
    show_pkg.set_defaults(func=cmd_package_show)
    snapshot_pkg = pks.add_parser(
        "snapshot", help="copy one exact installed package revision into the cache"
    )
    snapshot_pkg.add_argument("name", help="installed spindle package name")
    snapshot_pkg.add_argument(
        "--dry-run", action="store_true", help="show content identity and cache path"
    )
    snapshot_pkg.add_argument("--json", action="store_true")
    snapshot_pkg.set_defaults(func=cmd_package_snapshot)
    new_pkg = pks.add_parser(
        "new",
        help="scaffold a new pip-installable spindle package",
        description="Create a new spindle package skeleton with pyproject.toml and skill stubs.",
        epilog=(
            "Examples:\n"
            "  spindle package new my-tools --dest ./packages/my-tools\n"
            "  spindle package new my-tools --dest ./packages/my-tools \\\n"
            "      --skill search --skill summarise --capabilities web-search\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    new_pkg.add_argument(
        "name", help="package name (lowercase letters, digits, hyphens; e.g. my-tools)"
    )
    new_pkg.add_argument(
        "--dest",
        required=True,
        metavar="DIR",
        help="directory to write the scaffold into",
    )
    new_pkg.add_argument(
        "--skill",
        action="append",
        metavar="NAME",
        default=[],
        help="skill to include (repeatable)",
    )
    new_pkg.add_argument(
        "--capabilities",
        action="append",
        metavar="CAP",
        default=[],
        help="capability to declare (repeatable)",
    )
    new_pkg.set_defaults(func=cmd_package_new)

    sp = sub.add_parser("dist", help="list and inspect installed spindle distributions")
    dts = sp.add_subparsers(dest="dist_cmd", required=True)
    dts.add_parser(
        "list",
        help="list installed distributions with name, version, and package count",
    ).set_defaults(func=cmd_dist_list)
    show_dist = dts.add_parser(
        "show", help="show full metadata for a single distribution"
    )
    show_dist.add_argument("name", help="distribution name (e.g. spindle-sample)")
    show_dist.set_defaults(func=cmd_dist_show)
    inst_dist = dts.add_parser(
        "install", help="install a distribution package and link its skills"
    )
    inst_dist.add_argument(
        "source", help="pip source: local path, git URL, or PyPI name"
    )
    inst_dist.add_argument(
        "--dry-run", action="store_true", help="preview without making changes"
    )
    inst_dist.set_defaults(func=cmd_dist_install)
    uninst_dist = dts.add_parser("uninstall", help="unlink skills for a distribution")
    uninst_dist.add_argument("name", help="distribution name (e.g. spindle-sample)")
    uninst_dist.add_argument(
        "--dry-run", action="store_true", help="preview without making changes"
    )
    uninst_dist.add_argument(
        "--remove-packages",
        action="store_true",
        help="also uv pip uninstall the distribution's packages",
    )
    uninst_dist.set_defaults(func=cmd_dist_uninstall)
    act_dist = dts.add_parser("activate", help="set or show the active distribution")
    act_dist.add_argument(
        "name",
        nargs="?",
        default=None,
        help="distribution name (optional; if omitted, show current)",
    )
    act_dist.set_defaults(func=cmd_dist_activate)
    new_dist = dts.add_parser(
        "new",
        help="scaffold a new spindle distribution",
        description="Create a new spindle distribution skeleton with pyproject.toml and preempt.md.",
        epilog=(
            "Examples:\n"
            "  spindle dist new my-dist --dest ./distributions/my-dist\n"
            "  spindle dist new my-dist --dest ./distributions/my-dist \\\n"
            "      --source-dir ../../ \\\n"
            "      --package my-tools==0.1.0 --package sample-planning==0.1.0\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    new_dist.add_argument(
        "name",
        help="distribution name (lowercase letters, digits, hyphens; e.g. my-dist)",
    )
    new_dist.add_argument(
        "--dest",
        required=True,
        metavar="DIR",
        help="directory to write the scaffold into",
    )
    new_dist.add_argument(
        "--source-dir",
        metavar="PATH",
        default="../../",
        help="skills source_dir written into pyproject.toml (default: '../../')",
    )
    new_dist.add_argument(
        "--package",
        action="append",
        metavar="NAME=VERSION",
        default=[],
        help="dependency package spec (repeatable; e.g. sample-planning==0.1.0)",
    )
    new_dist.set_defaults(func=cmd_dist_new)

    sp = sub.add_parser("skill", help="list and inspect discovered spindle skills")
    sks = sp.add_subparsers(dest="skill_cmd", required=True)
    sks.add_parser("list", help="list all discovered spindle skills").set_defaults(
        func=cmd_skill_list
    )
    show_skill = sks.add_parser("show", help="show full metadata for a single skill")
    show_skill.add_argument("name", help="skill name (e.g. clarify)")
    show_skill.set_defaults(func=cmd_skill_show)

    sp = sub.add_parser("capability", help="list and inspect declared capabilities")
    caps = sp.add_subparsers(dest="capability_cmd", required=True)
    caps.add_parser(
        "list", help="list all declared capabilities and their providing packages"
    ).set_defaults(func=cmd_capability_list)
    show_cap = caps.add_parser("show", help="show full details for a single capability")
    show_cap.add_argument("name", help="capability name")
    show_cap.set_defaults(func=cmd_capability_show)

    sp = sub.add_parser(
        "eval", help="run paired or tuple-bound behavioral skill evaluations"
    )
    evs = sp.add_subparsers(dest="eval_cmd", required=True)
    validate_eval = evs.add_parser(
        "validate", help="validate an evaluation manifest and its inputs"
    )
    validate_eval.add_argument("manifest", help="path to eval.toml")
    validate_eval.set_defaults(func=cmd_eval_validate)
    run_eval = evs.add_parser(
        "run", help="run paired baseline/variant cases and write a receipt"
    )
    run_eval.add_argument("manifest", help="path to eval.toml")
    run_eval.add_argument(
        "--split",
        default="all",
        choices=["development", "held_out", "all"],
        help="case split to run (default all)",
    )
    run_eval.add_argument(
        "--receipt", help="output path (default manifest receipt_dir)"
    )
    run_eval.set_defaults(func=cmd_eval_run)
    show_eval = evs.add_parser("show", help="summarize a durable evaluation receipt")
    show_eval.add_argument("receipt", help="path to receipt JSON")
    show_eval.add_argument(
        "--json", action="store_true", help="print the complete receipt"
    )
    show_eval.set_defaults(func=cmd_eval_show)
    matrix_eval = evs.add_parser(
        "matrix",
        help="run tuple-bound named-arm ablations and non-inferiority gates",
    )
    matrix_commands = matrix_eval.add_subparsers(dest="matrix_action", required=True)
    matrix = matrix_commands.add_parser("validate", help="validate a named-arm manifest")
    matrix.add_argument("manifest")
    matrix.set_defaults(func=cmd_matrix_validate)
    matrix = matrix_commands.add_parser("run", help="run and retain every named arm")
    matrix.add_argument("manifest")
    matrix.add_argument(
        "--split", default="all", choices=["development", "held_out", "all"]
    )
    matrix.add_argument("--receipt")
    matrix.add_argument("--json", action="store_true")
    matrix.set_defaults(func=cmd_matrix_run)
    matrix = matrix_commands.add_parser(
        "freshness", help="compare a receipt with the complete current coordinate"
    )
    matrix.add_argument("receipt")
    matrix.add_argument(
        "--coordinate",
        action="append",
        required=True,
        help="current KEY=VALUE coordinate (repeat for all required dimensions)",
    )
    matrix.add_argument("--json", action="store_true")
    matrix.set_defaults(func=cmd_matrix_freshness)

    distill_eval = evs.add_parser(
        "distill", help="classify package material and stage bounded trial revisions"
    )
    distill_commands = distill_eval.add_subparsers(
        dest="distill_action", required=True
    )
    distill = distill_commands.add_parser(
        "classify", help="classify package material without executing it"
    )
    distill.add_argument("package")
    distill.add_argument("--json", action="store_true")
    distill.set_defaults(func=cmd_distillation)
    distill = distill_commands.add_parser(
        "plan", help="generate bounded deletion and extraction proposals"
    )
    distill.add_argument("package")
    distill.add_argument("--json", action="store_true")
    distill.set_defaults(func=cmd_distillation)
    distill = distill_commands.add_parser(
        "stage", help="copy one deletion proposal into a local trial revision"
    )
    distill.add_argument("package")
    distill.add_argument("--proposal", required=True)
    distill.add_argument("--destination", required=True)
    distill.add_argument("--dry-run", action="store_true")
    distill.add_argument("--json", action="store_true")
    distill.set_defaults(func=cmd_distillation)

    sp = sub.add_parser(
        "chippability",
        help="score skills for chip-shape (a refusing gate over durable cross-run state)",
        description=(
            "Statically score every skill under a package-dir or skill-dir for "
            "chip-shape. Regex/line scans only — no chip import, no chip host. "
            "Appends a chippability ledger record per skill; --emit-candidates "
            "appends chip candidates in the public candidates.jsonl convention."
        ),
    )
    sp.add_argument("target", help="a package directory or a single skill directory")
    sp.add_argument(
        "--emit-candidates",
        metavar="PATH",
        help="append chip-candidate skills to this candidates.jsonl file",
    )
    sp.add_argument("--json", action="store_true", help="print full reports as JSON")
    sp.set_defaults(func=cmd_chippability)

    sp = sub.add_parser(
        "rate", help="rate a skill (thumbs up/down) and log to feedback + ledger"
    )
    sp.add_argument("skill", help="skill name (e.g. clarify)")
    thumb = sp.add_mutually_exclusive_group(required=True)
    thumb.add_argument("--thumbs-up", action="store_true", help="positive rating")
    thumb.add_argument("--thumbs-down", action="store_true", help="negative rating")
    sp.add_argument("--note", default="", help="optional free-text note")
    sp.set_defaults(func=cmd_rate)

    sp = sub.add_parser(
        "state", help="show or rebuild spindle state from events ledger"
    )
    sts = sp.add_subparsers(dest="state_cmd", required=True)
    sts.add_parser(
        "show", help="show materialized state from events.jsonl"
    ).set_defaults(func=cmd_state_show)
    sts.add_parser(
        "rebuild", help="re-fold events.jsonl to regenerate state.json"
    ).set_defaults(func=cmd_state_rebuild)
    state_export = sts.add_parser(
        "export", help="write a reproducible diagnostic/custody bundle"
    )
    state_export.add_argument("output")
    state_export.add_argument(
        "--include-cache", action="store_true", help="include verified package bytes"
    )
    state_export.add_argument("--dry-run", action="store_true")
    state_export.add_argument("--json", action="store_true")
    state_export.set_defaults(func=cmd_state_export)
    state_import = sts.add_parser(
        "import", help="verify and merge only absent or byte-identical bundle files"
    )
    state_import.add_argument("bundle")
    state_import.add_argument("--destination", help="state root (default SPINDLE_HOME)")
    state_import.add_argument("--dry-run", action="store_true")
    state_import.add_argument("--json", action="store_true")
    state_import.set_defaults(func=cmd_state_import)
    state_gc = sts.add_parser(
        "gc", help="plan or apply exact unreferenced package-cache removal"
    )
    state_gc.add_argument("--apply", metavar="PLAN_ID")
    state_gc.add_argument("--dry-run", action="store_true")
    state_gc.add_argument("--json", action="store_true")
    state_gc.set_defaults(func=cmd_state_gc)
    state_recover = sts.add_parser(
        "recover", help="rebuild mutable indexes from immutable receipts"
    )
    state_recover.add_argument("--apply", metavar="PLAN_ID")
    state_recover.add_argument("--dry-run", action="store_true")
    state_recover.add_argument("--json", action="store_true")
    state_recover.set_defaults(func=cmd_state_recover)

    sp = sub.add_parser(
        "migrate", help="audit legacy installs and existing bindings without adoption"
    )
    migration_commands = sp.add_subparsers(dest="migration_action", required=True)
    migration_help = {
        "plan": "audit legacy and foreign state without mutation",
        "apply": "record the exact migration audit without adopting skills",
    }
    for action in ("plan", "apply"):
        migration = migration_commands.add_parser(action, help=migration_help[action])
        migration.add_argument("--repo", default=".")
        migration.add_argument(
            "--here", action="store_const", const=".", dest="repo"
        )
        migration.add_argument(
            "--harness", default="codex", choices=["claude", "codex"]
        )
        if action == "apply":
            migration.add_argument("plan_id")
        migration.add_argument("--json", action="store_true")
        migration.set_defaults(func=cmd_migrate)

    parse_argv = list(argv) if argv is not None else sys.argv[1:]
    launch_args: list[str] = []
    if parse_argv[:1] == ["launch"] and "--" in parse_argv:
        separator = parse_argv.index("--")
        launch_args = parse_argv[separator + 1 :]
        parse_argv = parse_argv[:separator]
    args = p.parse_args(parse_argv)
    if args.cmd == "launch":
        args.harness_args = launch_args
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
