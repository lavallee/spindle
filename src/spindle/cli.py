"""spindle CLI."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import scaffold as scaffold_mod
from . import active as active_mod
from . import capabilities as capabilities_mod
from . import advance as advance_mod
from . import appclass as appclass_mod
from . import binder as binder_mod
from . import broker as broker_mod
from . import channels as channels_mod
from . import liaison as liaison_mod
from . import roster as roster_mod
from . import llm as llm_mod
from . import profiles as profiles_mod
from . import render as render_mod
from . import distributions as distributions_mod
from . import doctrine as doctrine_mod
from . import fleet as fleet_mod
from . import gates as gates_mod
from . import ingest as ingest_mod
from . import ledger as ledger_mod
from . import optimize as optimize_mod
from . import packages as packages_mod
from . import preempt as preempt_mod
from . import rate as rate_mod
from . import resolver as resolver_mod
from . import scout as scout_mod
from . import scout_results as scout_results_mod
from . import skills as skills_mod
from .paths import claude_md_path, claude_skills_dir, events_file, ledger_path, state_file
from . import peers as peers_mod
from . import verdicts as verdicts_mod


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _append_dist_event(kind: str, distribution: str, version: str) -> None:
    event = {"kind": kind, "distribution": distribution, "version": version, "ts": _now_iso()}
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
    print(f"preempted:      {'yes' if preempt_mod.is_preempted() else 'no'} ({claude_md_path()})")
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
    print(f"{len(rows)} candidate verdict(s) awaiting review "
          f"(spindle verdict show <slug> after promoting):")
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
    )
    print(f"wrote {p}")
    return 0


# ---- ingest -------------------------------------------------------------

def _derive_project(row: ingest_mod.IngestRow, explicit_project: str | None) -> str | None:
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
        rows = [r for r in rows if r.task_id not in ingested or r.task_id.startswith("_anon_")]
        n_skipped = orig_count - len(rows)
        if n_skipped:
            print(f"skipped {n_skipped} already-ingested entries (use --reimport to force)")
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
            print(f"rewrote project on {rewritten} entries "
                  f"(original plan slug stashed in context.plan_slug)")
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

    summary = (
        f"posted={result.posted} skipped={result.skipped} "
        f"failed={result.failed}"
    )
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
        print(f"doctrine {doc.coordinate()} OK "
              f"({len(doc.preferences)} preferences, {len(doc.absolutes)} absolutes, "
              f"{len(doc.meta_principles)} meta-principles)")
        return 0
    print(f"doctrine {doc.coordinate()} has {len(problems)} problem(s):", file=sys.stderr)
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
    print(f"filed doctrine gate → {result.get('id', '?')} ({result.get('path', 'configured sink')})")
    return 0


def cmd_unbind(args) -> int:
    """Remove a surface's materialized skills."""
    repo = Path(args.repo).resolve()
    name = args.name or repo.name
    actions = binder_mod.unbind(name, repo, args.harness, dry_run=args.dry_run)
    removed = [n for n, a in actions if a == "removed"]
    if not removed:
        print(f"nothing bound for {name!r} [{args.harness}]")
        return 0
    for n in removed:
        print(f"  removed {n}")
    print(f"unbound {len(removed)} skill(s) from {name!r}"
          + (" (dry-run)" if args.dry_run else ""))
    return 0


# ---- bind ---------------------------------------------------------------

def _bind_context(doc, *, no_render: bool):
    """Build the (provider, render_fn) the binder needs from the active dist."""
    specs = skills_mod.discover_skills()
    index = {s.name: s.skill_dir for s in specs}
    provider = channels_mod.fs_provider(index)
    render_fn = binder_mod.identity_render
    if not no_render:
        client = llm_mod.from_env()
        profiles = profiles_mod.load_profiles(llm_client=client)
        model_profiles = profiles_mod.load_model_profiles(llm_client=client)
        if profiles or model_profiles:
            render_fn = render_mod.make_render_fn(
                profiles, doc.coordinate(), model_profiles=model_profiles)
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

    provider, render_fn = _bind_context(doc, no_render=args.no_render)
    result = binder_mod.bind(surface, repo, provider, doc, render=render_fn,
                             force=args.force, dry_run=args.dry_run)

    model_tag = f" · model:{surface.model}" if surface.model else ""
    print(f"surface {surface.name!r} [{surface.harness} · {surface.autonomy_mode}{model_tag}]  "
          f"app-class: {cls.cluster_key()}")
    if not result.ok:
        print(f"BLOCKED — {len(result.problems)} coherence problem(s):", file=sys.stderr)
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
            print("  P10 tiers: " + ", ".join(f"{t}={n}" for t, n in sorted(tiers.items())))
    if args.dry_run:
        print("(dry-run — nothing written)")
    else:
        print(f"bound at coordinate {result.coordinate}")
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
            print("no surfaces from registry (set SPINDLE_PROJECTS_DIR or pass a path; "
                  "needs local checkouts under the repo root)")
            return 0
    else:
        targets = advance_mod.load_targets()
        if not targets:
            print("no surfaces configured (see <source_dir>/advance/surfaces.toml, "
                  "or use --from-registry)")
            return 0
    provider, render_fn = _bind_context(doc, no_render=args.no_render)
    results = advance_mod.precompute(targets, provider, doc, render=render_fn,
                                     force=args.force, dry_run=args.dry_run)
    ok = sum(1 for _, r in results if r.ok)
    for name, r in results:
        status = "ok" if r.ok else f"BLOCKED ({len(r.problems)})"
        coord = f" {r.coordinate}" if r.coordinate else ""
        print(f"  {status:<14} {name}{coord}")
    print(f"precomputed {ok}/{len(results)} surface(s)"
          + (" (dry-run)" if args.dry_run else ""))
    return 0 if ok == len(results) else 1


# ---- liaison ------------------------------------------------------------

def cmd_liaison_request(args) -> int:
    """Articulate a surface's ad-hoc need as a what-request and log it (demand stream)."""
    repo = Path(args.repo).resolve()
    if not repo.exists():
        print(f"no such repo path: {repo}", file=sys.stderr)
        return 1
    req = liaison_mod.gather_request(
        repo, args.intent,
        harness=args.harness, autonomy_mode=args.autonomy,
        name=args.name, registry_kind=args.kind,
        desired_outcomes=args.outcome or [], acceptance=args.accept or [],
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
            print("(--bind: no doctrine in active distribution; skipped)", file=sys.stderr)
            return 0
        provider, render_fn = _bind_context(doc, no_render=False)
        result = liaison_mod.answer(req, repo, provider, doc, render=render_fn)
        if result.ok:
            print(f"  → bound the surface's current best set (coordinate {result.coordinate})")
        else:
            print(f"  → bind blocked: {len(result.problems)} problem(s)", file=sys.stderr)
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
        print(f"  [{flag}] {s.get('slug',''):<14} {s.get('kind',''):<12} {s.get('notes','')}")
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
            args.agent, args.intent,
            harness=args.harness, autonomy_mode=args.autonomy,
            desired_outcomes=args.outcome or [],
        )
    else:
        repo = Path(args.repo or ".").resolve()
        req = liaison_mod.gather_request(
            repo, args.intent, harness=args.harness, autonomy_mode=args.autonomy,
            desired_outcomes=args.outcome or [], registry_kind=args.kind,
        )
    providers = roster_mod.live_providers()
    proposals = broker_mod.broker(req, providers=providers, limit=args.limit,
                                  min_fit=args.min_fit)
    print(f"what-request {req.surface!r}: {req.intent!r}")
    if not proposals:
        print("  (no external candidates — enable a roster source and install its tool, "
              "or widen the query)")
        return 0
    for i, a in enumerate(proposals):
        print(f"  [{i}] fit={a.fit:<6} {a.candidate.source}:{a.candidate.id}  "
              f"{a.candidate.title}")
    if args.acquire is not None:
        if not (0 <= args.acquire < len(proposals)):
            print(f"no proposal [{args.acquire}]", file=sys.stderr)
            return 1
        acq = broker_mod.acquire(proposals[args.acquire])
        print(f"acquired {acq.candidate.source}:{acq.candidate.id} "
              f"(transposed={acq.provenance.get('transposed')}) — recorded to ledger")
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
        print(f"  {r.get('ts','')}  {r.get('status',''):<9} "
              f"{c.get('source','')}:{c.get('id','')}  fit={r.get('fit')}{mark}")
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
        print("optimize needs a held-out scorer: --score-cmd '<cmd printing a score>' "
              "(the candidate skill is written to $SPINDLE_SKILL_FILE).")
        print("  the loop: baseline → propose bounded edit → guardrail-check → score "
              "held-out → accept iff it improves (else reject + buffer).")
        return 0
    client = llm_mod.from_env()
    if client is None:
        print("optimize needs a proposer: set ANTHROPIC_API_KEY (an LLM proposes one "
              "bounded edit per epoch). The scorer + gate + guardrail floor are ready.")
        return 0

    score = optimize_mod.command_scorer(args.score_cmd)
    propose = optimize_mod.llm_proposer(client)
    result = optimize_mod.optimize(
        text, score=score, propose=propose, skill=path.stem,
        epochs=args.epochs, min_improvement=args.min_improvement,
    )
    print(f"skillopt {result.skill!r}: baseline {result.baseline:.4f} → "
          f"{result.best:.4f} (Δ{result.delta:+.4f}, {result.accepted_count}/"
          f"{len(result.epochs)} edits accepted)")
    for e in result.epochs:
        mark = "✓ accept" if e.accepted else "✗ reject"
        print(f"  epoch {e.epoch}: {mark}  score={e.score:.4f}  [{e.reason}]  {e.rationale}")
    if result.improved and not args.dry_run:
        if args.out:
            outp = Path(args.out)
        else:
            outp = path.with_suffix(path.suffix + ".optimized")
        outp.write_text(result.best_text, encoding="utf-8")
        print(f"wrote optimized skill → {outp}  (review before replacing the original)")
    elif not result.improved:
        print("no edit cleared the gate — the skill is unchanged (a real, honest result).")
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
        dists = ", ".join(f"{n}@{v}" for n, v in sorted(m.distributions.items())) or "(none)"
        last = m.last_event_ts or "—"
        print(f"{marker} {m.machine:<{width}}  events={m.event_count:<4}  last={last}  dists=[{dists}]")
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
                pkg_str = ", ".join(f"{k}={v}" for k, v in sorted(dist.packages.items()))
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
    print(f"  {'capabilities':<14} {', '.join(meta.capabilities) if meta.capabilities else '(none)'}")
    print(f"  {'package_dir':<14} {meta.package_dir}")
    if meta.sources:
        for src in meta.sources:
            print(f"  {'source':<14} {src.peer}  {src.url}  (transposed {src.transposed_at})")
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
        print(f"  {d.name:<{name_width}}  {d.version:<8}  {pkg_count} package{'s' if pkg_count != 1 else ''}")
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
        skills_linked = [name for name, action in results if "installed" in action or "linked" in action]
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
        ledger_mod.log_event("dist_uninstall", distribution=args.name, version=meta.version)

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
            if key not in ('name',):
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
            print(f"  {'source':<16} {peer}  {url}  (transposed {transposed}){notes_str}")
    return 0


# ---- main ---------------------------------------------------------------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="spindle", description="Spindle — vertically integrated planning skills + peer scout")
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
    add.add_argument("--kind", default="github", choices=["github", "blog", "rss", "other"])
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
    add.add_argument("--verdict", default="tracking",
                     choices=["tracking", "borrow", "graft", "ignore", "try"])
    add.add_argument("--status", default="candidate",
                     choices=["candidate", "in-use", "rejected", "superseded"])
    add.add_argument("--body")
    add.add_argument("--body-file")
    add.set_defaults(func=cmd_verdict_add)

    sp = sub.add_parser("doctrine", help="show/validate the active distribution's doctrine")
    dcs = sp.add_subparsers(dest="doctrine_cmd", required=True)
    dcs.add_parser("show", help="print preferences, absolutes, meta-principles").set_defaults(
        func=cmd_doctrine_show
    )
    dcs.add_parser("validate", help="check the doctrine is well-formed").set_defaults(
        func=cmd_doctrine_validate
    )

    sp = sub.add_parser("appclass", help="classify a repo's app-type (Path B)")
    sp.add_argument("path", help="path to a local repo checkout")
    sp.add_argument("--kind", help="project registry kind, if known (library/service/...)")
    sp.set_defaults(func=cmd_appclass)

    sp = sub.add_parser("bind", help="compose + materialize a surface's skills (channel binder)")
    sp.add_argument("repo", help="path to the target repo/surface checkout")
    sp.add_argument("--name", help="surface name (defaults to repo dir name)")
    sp.add_argument("--harness", default="claude", help="claude | codex | pi (default claude)")
    sp.add_argument("--model", default=None,
                    help="model/tier to tune render density for (e.g. frontier); "
                         "None = no model tuning")
    sp.add_argument("--autonomy", default="deterministic",
                    choices=["deterministic", "self_evolving"])
    sp.add_argument("--kind", help="project registry kind, if known")
    sp.add_argument("--force", action="store_true", help="materialize despite lint problems")
    sp.add_argument("--no-render", action="store_true", help="skip dialect rendering (verbatim skills)")
    sp.add_argument("--dry-run", action="store_true", help="show the plan, write nothing")
    sp.set_defaults(func=cmd_bind)

    sp = sub.add_parser("unbind", help="remove a surface's materialized skills")
    sp.add_argument("repo", help="path to the target repo/surface checkout")
    sp.add_argument("--name", help="surface name (defaults to repo dir name)")
    sp.add_argument("--harness", default="claude")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_unbind)

    sp = sub.add_parser("advance", help="advance team: precompute compositions for all surfaces")
    avs = sp.add_subparsers(dest="advance_cmd", required=True)
    ar = avs.add_parser("run", help="bind every configured surface ahead of time")
    ar.add_argument("--from-registry", nargs="?", const=True, default=False,
                    metavar="PROJECTS_DIR",
                    help="enumerate surfaces from a TOML project registry (default $SPINDLE_PROJECTS_DIR)")
    ar.add_argument("--force", action="store_true")
    ar.add_argument("--no-render", action="store_true")
    ar.add_argument("--dry-run", action="store_true")
    ar.set_defaults(func=cmd_advance_run)

    sp = sub.add_parser("liaison", help="the in-repo edge: articulate + log a surface's needs")
    lns = sp.add_subparsers(dest="liaison_cmd", required=True)
    lr = lns.add_parser("request", help="articulate an ad-hoc need as a what-request")
    lr.add_argument("repo", help="path to the surface's repo")
    lr.add_argument("--intent", required=True, help="the ask, in your words")
    lr.add_argument("--outcome", action="append", help="a desired outcome (repeatable)")
    lr.add_argument("--accept", action="append", help="an acceptance criterion (repeatable)")
    lr.add_argument("--name", help="surface name (defaults to repo dir name)")
    lr.add_argument("--harness", default="claude")
    lr.add_argument("--autonomy", default="deterministic", choices=["deterministic", "self_evolving"])
    lr.add_argument("--kind", help="project registry kind, if known")
    lr.add_argument("--bind", action="store_true",
                    help="also answer it: bind the surface's current best skills")
    lr.set_defaults(func=cmd_liaison_request)
    ll = lns.add_parser("log", help="show a surface's logged what-requests (demand stream)")
    ll.add_argument("surface")
    ll.set_defaults(func=cmd_liaison_log)

    sp = sub.add_parser("roster", help="upstream skill sources Spindle can broker from")
    rss = sp.add_subparsers(dest="roster_cmd", required=True)
    rl = rss.add_parser("list", help="list roster sources")
    rl.set_defaults(func=cmd_roster_list)

    sp = sub.add_parser("broker",
                        help="broker a what-request against external rosters (search → rank → propose)")
    sp.add_argument("intent", help="the ask, in your words")
    sp.add_argument("--repo", help="repo path for app-class self-knowledge (default .)")
    sp.add_argument("--agent", help="agent id — articulate the request for an agent, not a repo")
    sp.add_argument("--harness", default="claude")
    sp.add_argument("--autonomy", default="self_evolving",
                    choices=["deterministic", "self_evolving"])
    sp.add_argument("--kind", help="project registry kind, if known")
    sp.add_argument("--outcome", action="append", help="a desired outcome (repeatable)")
    sp.add_argument("--limit", type=int, default=3, help="max proposals (default 3)")
    sp.add_argument("--min-fit", type=float, default=0.0, help="drop proposals below this fit")
    sp.add_argument("--acquire", type=int, metavar="N",
                    help="acquire proposal N (transpose stub + record outcome)")
    sp.set_defaults(func=cmd_broker)

    sp = sub.add_parser("acquisitions", help="show the acquisitions ledger (what was brokered)")
    sp.set_defaults(func=cmd_acquisitions)

    sp = sub.add_parser("optimize",
                        help="validation-gated skill optimization (SkillOpt): accept edits only if a held-out score improves")
    sp.add_argument("skill", help="path to the SKILL.md to optimize")
    sp.add_argument("--score-cmd", help="command that prints a held-out score; candidate at $SPINDLE_SKILL_FILE")
    sp.add_argument("--epochs", type=int, default=5, help="max optimization epochs (default 5)")
    sp.add_argument("--min-improvement", type=float, default=0.0,
                    help="required held-out gain to accept an edit (default any improvement)")
    sp.add_argument("--out", help="where to write the optimized skill (default <skill>.optimized)")
    sp.add_argument("--dry-run", action="store_true", help="run the loop, write nothing")
    sp.set_defaults(func=cmd_optimize)

    sp = sub.add_parser("gate", help="file doctrine gates into the decision queue")
    gts = sp.add_subparsers(dest="gate_cmd", required=True)
    gf = gts.add_parser("file", help="file an spindle:doctrine gate")
    gf.add_argument("--crux", required=True, help="the decision in one or two sentences")
    gf.add_argument("--diff", help="proposed doctrine diff (this-over-that)")
    gf.add_argument("--pilot", help="experiment that would settle it, or 'values call'")
    gf.add_argument("--source", help="peer slug the challenge came from")
    gf.add_argument("--dry-run", action="store_true", help="print the body, don't write")
    gf.set_defaults(func=cmd_gate_file)
    gfr = gts.add_parser("from-result", help="file a gate from an adjudicate-pass result file")
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
        "--dry-run", action="store_true",
        help="parse and topo-sort but don't write to the task sink",
    )
    sp.add_argument(
        "--strict", action="store_true",
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
    fls.add_parser("status", help="list installed distributions per machine").set_defaults(
        func=cmd_fleet_status
    )
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
    pks.add_parser("list", help="list all installed spindle packages").set_defaults(func=cmd_package_list)
    show_pkg = pks.add_parser("show", help="show details for a single package")
    show_pkg.add_argument("name", help="package name (e.g. sample-planning)")
    show_pkg.set_defaults(func=cmd_package_show)
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
    new_pkg.add_argument("name", help="package name (lowercase letters, digits, hyphens; e.g. my-tools)")
    new_pkg.add_argument("--dest", required=True, metavar="DIR", help="directory to write the scaffold into")
    new_pkg.add_argument("--skill", action="append", metavar="NAME", default=[], help="skill to include (repeatable)")
    new_pkg.add_argument("--capabilities", action="append", metavar="CAP", default=[], help="capability to declare (repeatable)")
    new_pkg.set_defaults(func=cmd_package_new)

    sp = sub.add_parser("dist", help="list and inspect installed spindle distributions")
    dts = sp.add_subparsers(dest="dist_cmd", required=True)
    dts.add_parser("list", help="list installed distributions with name, version, and package count").set_defaults(func=cmd_dist_list)
    show_dist = dts.add_parser("show", help="show full metadata for a single distribution")
    show_dist.add_argument("name", help="distribution name (e.g. spindle-sample)")
    show_dist.set_defaults(func=cmd_dist_show)
    inst_dist = dts.add_parser("install", help="install a distribution package and link its skills")
    inst_dist.add_argument("source", help="pip source: local path, git URL, or PyPI name")
    inst_dist.add_argument("--dry-run", action="store_true", help="preview without making changes")
    inst_dist.set_defaults(func=cmd_dist_install)
    uninst_dist = dts.add_parser("uninstall", help="unlink skills for a distribution")
    uninst_dist.add_argument("name", help="distribution name (e.g. spindle-sample)")
    uninst_dist.add_argument("--dry-run", action="store_true", help="preview without making changes")
    uninst_dist.add_argument(
        "--remove-packages",
        action="store_true",
        help="also uv pip uninstall the distribution's packages",
    )
    uninst_dist.set_defaults(func=cmd_dist_uninstall)
    act_dist = dts.add_parser("activate", help="set or show the active distribution")
    act_dist.add_argument("name", nargs="?", default=None, help="distribution name (optional; if omitted, show current)")
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
    new_dist.add_argument("name", help="distribution name (lowercase letters, digits, hyphens; e.g. my-dist)")
    new_dist.add_argument("--dest", required=True, metavar="DIR", help="directory to write the scaffold into")
    new_dist.add_argument("--source-dir", metavar="PATH", default="../../", help="skills source_dir written into pyproject.toml (default: '../../')")
    new_dist.add_argument("--package", action="append", metavar="NAME=VERSION", default=[], help="dependency package spec (repeatable; e.g. sample-planning==0.1.0)")
    new_dist.set_defaults(func=cmd_dist_new)

    sp = sub.add_parser("skill", help="list and inspect discovered spindle skills")
    sks = sp.add_subparsers(dest="skill_cmd", required=True)
    sks.add_parser("list", help="list all discovered spindle skills").set_defaults(func=cmd_skill_list)
    show_skill = sks.add_parser("show", help="show full metadata for a single skill")
    show_skill.add_argument("name", help="skill name (e.g. clarify)")
    show_skill.set_defaults(func=cmd_skill_show)

    sp = sub.add_parser("capability", help="list and inspect declared capabilities")
    caps = sp.add_subparsers(dest="capability_cmd", required=True)
    caps.add_parser("list", help="list all declared capabilities and their providing packages").set_defaults(func=cmd_capability_list)
    show_cap = caps.add_parser("show", help="show full details for a single capability")
    show_cap.add_argument("name", help="capability name")
    show_cap.set_defaults(func=cmd_capability_show)

    sp = sub.add_parser("rate", help="rate a skill (thumbs up/down) and log to feedback + ledger")
    sp.add_argument("skill", help="skill name (e.g. clarify)")
    thumb = sp.add_mutually_exclusive_group(required=True)
    thumb.add_argument("--thumbs-up", action="store_true", help="positive rating")
    thumb.add_argument("--thumbs-down", action="store_true", help="negative rating")
    sp.add_argument("--note", default="", help="optional free-text note")
    sp.set_defaults(func=cmd_rate)

    sp = sub.add_parser("state", help="show or rebuild spindle state from events ledger")
    sts = sp.add_subparsers(dest="state_cmd", required=True)
    sts.add_parser("show", help="show materialized state from events.jsonl").set_defaults(func=cmd_state_show)
    sts.add_parser("rebuild", help="re-fold events.jsonl to regenerate state.json").set_defaults(func=cmd_state_rebuild)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
