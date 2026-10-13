"""CLI for the house, the catalog, and on-demand skill sourcing."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import catalog as catalog_mod
from . import expand as expand_mod
from . import house as house_mod
from . import sourcing as sourcing_mod
from .lifecycle import LifecycleError


def _fail(exc: Exception) -> int:
    print(f"spindle: {exc}", file=sys.stderr)
    return 1


def _emit(payload, as_json: bool, text: str) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True) if as_json else text)


def _rows_text(rows: list[dict[str, str]]) -> str:
    quiet = [row for row in rows if row["action"] != "current"]
    lines = [
        f"  {row['harness']:<7} {row['kind']:<6} {row['action']:<9} "
        f"{row['name']}" + (f"  ({row['detail']})" if row["detail"] else "")
        for row in quiet
    ]
    lines.append(f"{len(rows) - len(quiet)} already current, {len(quiet)} changed")
    return "\n".join(lines)


def _task(args) -> str:
    if args.task_file:
        source = sys.stdin if args.task_file == "-" else None
        text = source.read() if source else Path(args.task_file).read_text("utf-8")
    else:
        text = " ".join(args.task)
    if not text.strip():
        raise house_mod.HouseError("give a task: words, or --task-file PATH (or -)")
    return text


# ---------------------------------------------------------------------- house


def cmd_house_init(args) -> int:
    try:
        config = house_mod.init(args.path)
        house = house_mod.load()
    except house_mod.HouseError as exc:
        return _fail(exc)
    print(f"house v{house.version} at {house.root} (recorded in {config})")
    return 0


def cmd_house_setup(args) -> int:
    try:
        house = house_mod.load()
        if args.repo:
            rows = house_mod.setup_repo(
                house,
                Path(args.repo),
                tuple(args.pattern or ()),
                with_house_rules=args.with_house_rules,
                force=args.force,
                dry_run=args.dry_run,
            )
        else:
            harnesses = tuple(args.harness or house_mod.detect_harnesses())
            rows = house_mod.setup_machine(
                house, harnesses, dry_run=args.dry_run,
                prune_dangling=args.prune_dangling,
            )
    except (house_mod.HouseError, LifecycleError, OSError) as exc:
        return _fail(exc)
    prefix = "dry run; nothing changed\n" if args.dry_run else ""
    _emit(rows, args.json, prefix + _rows_text(rows))
    return 1 if any(row["action"] == "conflict" for row in rows) else 0


def cmd_house_remove(args) -> int:
    try:
        rows = house_mod.remove_machine(
            tuple(args.harness or house_mod.HARNESSES), dry_run=args.dry_run
        )
    except (house_mod.HouseError, OSError) as exc:
        return _fail(exc)
    prefix = "dry run; nothing changed\n" if args.dry_run else ""
    _emit(rows, args.json, prefix + _rows_text(rows))
    return 0


def cmd_house_status(args) -> int:
    try:
        house = house_mod.load()
        if args.repo:
            report = house_mod.repo_status(house, Path(args.repo))
        else:
            report = house_mod.machine_status(house, house_mod.detect_harnesses())
    except (house_mod.HouseError, LifecycleError, OSError) as exc:
        return _fail(exc)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    if args.repo:
        print(f"{report['repo']}: {report['state']}")
        if report["state"] == "set up":
            print(f"  patterns: {', '.join(report['patterns']) or 'none'}  "
                  f"(locked v{report['locked_version']}, house v{report['house_version']})")
            for name, state in sorted(report["skills"].items()):
                print(f"  {state:<12} {name}")
        return 0
    print(f"house v{report['house']['version']} at {report['house']['dir']}")
    for harness, state in report["harnesses"].items():
        kernel = state["kernel"]
        good = sum(1 for value in kernel.values() if value == "current")
        rules = state["rules"]
        version = f" v{rules['installed_version']}" if rules["installed_version"] else ""
        print(f"  {harness:<7} rules {rules['state']}{version}; kernel {good}/"
              f"{len(kernel)} linked; {state['always_on']} skills always on; "
              f"{len(state['dangling'])} dead links")
        for name, value in sorted(kernel.items()):
            if value != "current":
                print(f"          {value:<9} {name}")
    return 0


def cmd_house_rules(args) -> int:
    try:
        house = house_mod.load()
        parts = [house.rules_text().strip()]
        for name in args.pattern or ():
            rules = house.pattern(name).rules
            if rules is not None:
                parts.append(rules.read_text(encoding="utf-8").strip())
    except (house_mod.HouseError, OSError) as exc:
        return _fail(exc)
    text = "\n\n".join(parts) + "\n"
    _emit({"version": house.version, "rules": text}, args.json, text.rstrip("\n"))
    return 0


def cmd_house_patterns(args) -> int:
    try:
        house = house_mod.load()
    except house_mod.HouseError as exc:
        return _fail(exc)
    payload = {
        name: {"description": p.description, "skills": list(p.skills),
               "rules": str(p.rules) if p.rules else None}
        for name, p in sorted(house.patterns.items())
    }
    text = "\n".join(
        f"{name:<22} {body['description']}\n{'':<22} skills: "
        f"{', '.join(body['skills']) or 'none'}"
        for name, body in payload.items()
    )
    _emit(payload, args.json, text or "no patterns defined")
    return 0


# -------------------------------------------------------------------- catalog


def cmd_catalog_sync(args) -> int:
    try:
        index = catalog_mod.sync(house_mod.load(), offline=args.offline, only=args.slug)
    except (house_mod.HouseError, LifecycleError, OSError) as exc:
        return _fail(exc)
    lines = []
    for source in index["sources"]:
        where = (source.get("commit") or "")[:12] or "local"
        tail = f"ERROR {source['error']}" if source.get("error") else ""
        lines.append(f"  {source['slug']:<20} {source['skills']:>4} skills  {where} {tail}")
    lines.append(f"{len(index['skills'])} skills indexed")
    _emit(index["sources"], args.json, "\n".join(lines))
    return 1 if any(source.get("error") for source in index["sources"]) else 0


def cmd_catalog_list(args) -> int:
    try:
        index = catalog_mod.load_index()
    except house_mod.HouseError as exc:
        return _fail(exc)
    skills = [
        entry for entry in index["skills"]
        if not args.source or entry["source"] == args.source
    ]
    if args.json:
        print(json.dumps([{k: v for k, v in e.items() if k != "excerpt"}
                          for e in skills], indent=2, sort_keys=True))
        return 0
    for entry in skills:
        flags = "".join((
            "K" if entry["kernel"] else "-",
            "I" if entry["requires_install"] else "-",
        ))
        description = " ".join(entry["description"].split())[:90]
        print(f"{flags} {entry['ref']:<40} {description}")
    print(f"{len(skills)} skills (K = in the kernel, I = needs its own install)")
    return 0


def cmd_catalog_update(args) -> int:
    try:
        house = house_mod.load()
        reports = catalog_mod.check_updates(house, args.slug)
        applied = []
        if args.apply:
            for report in reports:
                if report["state"] == "behind":
                    catalog_mod.apply_update(house, report["slug"], report["head"])
                    applied.append(report["slug"])
            if applied:
                catalog_mod.sync(house_mod.load())
    except (house_mod.HouseError, LifecycleError, OSError) as exc:
        return _fail(exc)
    if args.json:
        print(json.dumps({"reports": reports, "applied": applied}, indent=2,
                         sort_keys=True))
        return 0
    for report in reports:
        if report["state"] == "error":
            print(f"{report['slug']}: ERROR {report['error']}")
            continue
        if report["state"] == "current":
            print(f"{report['slug']}: current at {report['head'][:12]}")
            continue
        print(f"{report['slug']}: {(report['pinned'] or 'unpinned')[:12]} -> "
              f"{report['head'][:12]}  +{len(report['added'])} "
              f"~{len(report['changed'])} -{len(report['removed'])}")
        for label in ("added", "changed", "removed"):
            if report[label]:
                print(f"  {label}: {', '.join(report[label])}")
        for name, risks in report["new_risks"].items():
            print(f"  new static risk indicators in {name}: {', '.join(risks)}")
    if applied:
        print(f"pinned and re-indexed: {', '.join(applied)}")
    elif any(report["state"] == "behind" for report in reports):
        print("rerun with --apply to move the pins")
    return 0


# ------------------------------------------------------------------- sourcing


def _select(args):
    index = catalog_mod.load_index()
    repo = Path(args.repo) if args.repo else None
    task = _task(args)
    phrases: list[str] = []
    note = ""
    if args.expand == "auto":
        try:
            command = house_mod.load().expand_command
        except house_mod.HouseError:
            command = None
        phrases, note = expand_mod.expand(task, command)
    return sourcing_mod.select(
        index, task, k=args.k, repo=repo, job=args.job, use_judge=args.judge,
        phrases=phrases, expand_note=note,
    )


def cmd_find(args) -> int:
    try:
        selection = _select(args)
    except (house_mod.HouseError, OSError) as exc:
        return _fail(exc)
    if args.json:
        print(json.dumps(selection, indent=2, sort_keys=True))
        return 0
    candidates = selection["candidates"]
    if not candidates:
        print("no catalog skill matches this task")
        return 0
    if selection["judge_note"]:
        print(f"({selection['judge_note']}; ranked by text match only)")
    if selection["expanded_queries"]:
        print("also searched: " + "; ".join(selection["expanded_queries"]))
    elif selection["expand_note"]:
        print(f"({selection['expand_note']})")
    for candidate in candidates[:8]:
        mark = "*" if candidate["selected"] else " "
        judged = (f"{candidate['judged']:.2f}" if candidate["judged"] is not None
                  else " -- ")
        description = " ".join(candidate["description"].split())[:100]
        print(f"{mark} {judged} {candidate['lexical']:.2f}  {candidate['ref']:<34} "
              f"{description}")
    chosen = [c["ref"] for c in candidates if c["selected"]]
    if selection["confidence"] == "lexical":
        tail = ("shortlist by text match only; judge the descriptions yourself, "
                "then `spindle use <ref>`")
    elif chosen:
        tail = f"selected {', '.join(chosen)}; read one with `spindle use <ref>`"
    else:
        tail = "nothing selected; no skill is expected to help"
    print(f"\n{selection['id']}: {tail}")
    return 0


def cmd_brief(args) -> int:
    try:
        selection = _select(args)
        delivery = "inline" if args.inline else "path"
        if args.inline:
            # Inline text is paid for whether or not it is used, so embed fewer
            # skills than a path listing would name.
            kept = 0
            for candidate in selection["candidates"]:
                if candidate["selected"]:
                    kept += 1
                    candidate["selected"] = kept <= sourcing_mod.INLINE_MAX_SKILLS
        if selection["confidence"] == "lexical" and args.unjudged != "shortlist":
            # Unjudged text matches are not offered; see sourcing.pointer_block.
            for candidate in selection["candidates"]:
                candidate["selected"] = False
            delivery = args.unjudged
            block = (
                sourcing_mod.pointer_block(selection)
                if args.unjudged == "pointer" else ""
            )
        else:
            block = sourcing_mod.prompt_block(selection, inline=args.inline)
        payload = {
            "selection": selection["id"],
            "skills": sourcing_mod.skills_record(selection, delivery),
            "prompt_block": block,
        }
        if args.inline and delivery == "inline":
            for candidate in selection["candidates"]:
                if candidate["selected"]:
                    sourcing_mod.note_loaded(
                        candidate, selection=selection["id"], job=args.job
                    )
        if args.rules:
            house = house_mod.load()
            payload["rules"] = {"version": house.version, "text": house.rules_text()}
    except (house_mod.HouseError, OSError) as exc:
        return _fail(exc)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        if args.rules:
            print(payload["rules"]["text"])
        print(block, end="")
    return 0


def cmd_use(args) -> int:
    try:
        entry = catalog_mod.find_entry(catalog_mod.load_index(), args.ref)
        text = sourcing_mod.read_skill(entry)
        sourcing_mod.note_loaded(entry, selection=args.selection, job=args.job)
    except (house_mod.HouseError, OSError) as exc:
        return _fail(exc)
    path = Path(entry["path"]) / "SKILL.md"
    if args.json:
        print(json.dumps({"ref": entry["ref"], "path": str(path),
                          "root": entry["path"], "digest": entry["digest"],
                          "requires_install": entry["requires_install"]}, indent=2))
    elif args.print:
        print(text, end="" if text.endswith("\n") else "\n")
    else:
        print(path)
        if entry["requires_install"]:
            print("note: this skill refers to its own install path; treat it as "
                  "reference unless that package is installed", file=sys.stderr)
    return 0


def cmd_report(args) -> int:
    try:
        event = sourcing_mod.report(
            outcome=args.outcome, selection_id=args.selection, job=args.job,
            loaded=args.loaded, helped=args.helped, hurt=args.hurt, note=args.note,
        )
    except house_mod.HouseError as exc:
        return _fail(exc)
    _emit(event, args.json, f"recorded {event['outcome']} for "
          f"{event['selection'] or event['job'] or 'named skills'}")
    return 0


def cmd_usage(args) -> int:
    stats = sourcing_mod.usage_summary()
    if args.json:
        print(json.dumps(stats, indent=2, sort_keys=True))
        return 0
    if not stats:
        print("no usage recorded yet")
        return 0
    print(f"{'skill':<36} offer  sel load  acc  rej help hurt prior")
    for ref, row in sorted(stats.items(), key=lambda kv: (-kv[1]["loaded"], kv[0])):
        print(f"{ref:<36} {row['offered']:>5} {row['selected']:>4} {row['loaded']:>4} "
              f"{row['accepted']:>4} {row['rejected']:>4} {row['helped']:>4} "
              f"{row['hurt']:>4} {sourcing_mod.prior(row):>5.2f}")
    return 0


def _task_arguments(parser) -> None:
    parser.add_argument("task", nargs="*", help="the task, in plain words")
    parser.add_argument("--task-file", metavar="PATH", help="read the task (- = stdin)")
    parser.add_argument("--repo", help="repository the task runs in")
    parser.add_argument("--here", action="store_const", const=".", dest="repo")
    parser.add_argument("--job", default=os.environ.get("SPINDLE_JOB"),
                        help="runtime job id to join later reports to "
                             "(default: $SPINDLE_JOB)")
    parser.add_argument("-k", type=int, default=3, help="most skills to select")
    parser.add_argument("--judge", choices=["auto", "jev", "none"], default="auto")
    parser.add_argument("--expand", choices=["auto", "none"], default="auto",
                        help="rewrite the task into search phrases with the "
                             "house's expander, when it names one")
    parser.add_argument("--json", action="store_true")


def register(sub) -> None:
    sp = sub.add_parser("house", help="house rules, kernel skills, project patterns")
    hs = sp.add_subparsers(dest="house_cmd", required=True)
    h = hs.add_parser("init", help="point this machine at a house directory")
    h.add_argument("path")
    h.set_defaults(func=cmd_house_init)
    h = hs.add_parser("setup", help="install rules and skills (machine, or --repo)")
    h.add_argument("--harness", action="append", choices=house_mod.HARNESSES)
    h.add_argument("--repo", help="set up a repository instead of this machine")
    h.add_argument("--here", action="store_const", const=".", dest="repo")
    h.add_argument("--pattern", action="append", help="project pattern (with --repo)")
    h.add_argument("--with-house-rules", action="store_true",
                   help="embed the full house rules in the repo, not a pointer")
    h.add_argument("--prune-dangling", action="store_true",
                   help="remove dead symlinks from harness skill directories")
    h.add_argument("--force", action="store_true",
                   help="overwrite vendored skills that were edited in the repo")
    h.add_argument("--dry-run", action="store_true")
    h.add_argument("--json", action="store_true")
    h.set_defaults(func=cmd_house_setup)
    h = hs.add_parser("remove", help="undo the machine setup for a harness")
    h.add_argument("--harness", action="append", choices=house_mod.HARNESSES)
    h.add_argument("--dry-run", action="store_true")
    h.add_argument("--json", action="store_true")
    h.set_defaults(func=cmd_house_remove)
    h = hs.add_parser("status", help="what is installed and whether it is current")
    h.add_argument("--repo")
    h.add_argument("--here", action="store_const", const=".", dest="repo")
    h.add_argument("--json", action="store_true")
    h.set_defaults(func=cmd_house_status)
    h = hs.add_parser("rules", help="print the house rules")
    h.add_argument("--pattern", action="append")
    h.add_argument("--json", action="store_true")
    h.set_defaults(func=cmd_house_rules)
    h = hs.add_parser("patterns", help="list project patterns")
    h.add_argument("--json", action="store_true")
    h.set_defaults(func=cmd_house_patterns)

    sp = sub.add_parser("catalog", help="pinned sources of on-demand skills")
    cs = sp.add_subparsers(dest="catalog_cmd", required=True)
    c = cs.add_parser("sync", help="fetch pinned sources and rebuild the index")
    c.add_argument("slug", nargs="?")
    c.add_argument("--offline", action="store_true")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_catalog_sync)
    c = cs.add_parser("list", help="list indexed skills")
    c.add_argument("--source")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_catalog_list)
    c = cs.add_parser("update", help="compare pins with upstream; --apply moves them")
    c.add_argument("slug", nargs="?")
    c.add_argument("--apply", action="store_true")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_catalog_update)

    sp = sub.add_parser("find", help="rank catalog skills for a task")
    _task_arguments(sp)
    sp.set_defaults(func=cmd_find)

    sp = sub.add_parser(
        "brief", help="select skills for a task and print a prompt section for them"
    )
    _task_arguments(sp)
    sp.add_argument("--inline", action="store_true",
                    help="embed skill text for runtimes that cannot read the paths")
    sp.add_argument("--rules", action="store_true", help="include the house rules")
    sp.add_argument(
        "--unjudged", choices=["pointer", "shortlist", "none"], default="pointer",
        help="without a judge: tell the agent how to search (default), offer the "
             "text-match shortlist anyway, or offer nothing",
    )
    sp.set_defaults(func=cmd_brief)

    sp = sub.add_parser("use", help="hand one catalog skill to the agent")
    sp.add_argument("ref", help="source/name, or a bare name when unambiguous")
    sp.add_argument("--selection")
    sp.add_argument("--job", default=os.environ.get("SPINDLE_JOB"))
    sp.add_argument("--print", action="store_true", help="print the skill text")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_use)

    sp = sub.add_parser("report", help="record how work that used skills turned out")
    sp.add_argument("--outcome", required=True, choices=sourcing_mod.OUTCOMES)
    sp.add_argument("--selection")
    sp.add_argument("--job", default=os.environ.get("SPINDLE_JOB"))
    sp.add_argument("--loaded", action="append", metavar="REF")
    sp.add_argument("--helped", action="append", metavar="REF")
    sp.add_argument("--hurt", action="append", metavar="REF")
    sp.add_argument("--note", default="")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("usage", help="per-skill selection and outcome counts")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_usage)
