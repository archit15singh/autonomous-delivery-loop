"""CLI for replaying, preparing and monitoring upstream contributions."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from .revisions import FULL_REVISION, git
from .local_codex import MAX_SUBAGENTS
from .patch_checkout import write_patch
from .cli_output import write
from .factory_definition import running_definition
from .run_index import indexed_runs, run_record
from .upstream import replay
from .upstream_actions import ActionLedger
from .github import PR_URL
from .upstream_ci import attach_local_replay, inspect_prs
from .upstream_merge import merge_precedents
from .upstream_pr import prepare


def register(commands):
    propose = commands.add_parser("upstream-propose", help="generate a scoped patch in a local Codex checkout")
    propose.set_defaults(upstream_handler=propose_command)
    propose.add_argument("--repo", type=Path, required=True)
    propose.add_argument("--base", required=True, help="full upstream commit SHA")
    propose.add_argument("--brief", type=Path, required=True, help="operator-authored task file")
    propose.add_argument("--allow", action="append", required=True, metavar="PATH")
    propose.add_argument("--output", type=Path, required=True, help="new attempt directory")
    propose.add_argument("--model")
    propose.add_argument("--timeout", type=int, choices=range(1, 601), default=180, metavar="SECONDS")
    propose.add_argument("--subagents", type=int, choices=range(MAX_SUBAGENTS + 1), default=0)
    upstream = commands.add_parser("upstream-replay")
    upstream.set_defaults(upstream_handler=replay_command)
    upstream.add_argument("--repo", type=Path, required=True)
    upstream.add_argument("--contract", type=Path, required=True)
    upstream.add_argument("--output", type=Path, required=True)
    ready = commands.add_parser("upstream-prepare", help="verify a local upstream candidate and prepare its PR body")
    ready.set_defaults(upstream_handler=prepare_command)
    ready.add_argument("--repo", type=Path, required=True)
    ready.add_argument("--contract", type=Path, required=True)
    ready.add_argument("--template", type=Path, required=True)
    ready.add_argument("--evidence-url", required=True)
    ready.add_argument("--output", type=Path, required=True)
    ready.add_argument("--browser-proof", type=Path, help="exact-base and exact-head browser receipt")
    ready.add_argument("--runs", type=Path, help="index the verification in the factory run directory")
    ready.add_argument("--pr", help="GitHub PR URL for an indexed verification run")
    ci = commands.add_parser("upstream-ci", help="inspect each PR's current head and Actions runs")
    ci.set_defaults(upstream_handler=ci_command)
    ci.add_argument("urls", metavar="PR_URL", nargs="*")
    ci.add_argument("--file", type=Path, help="one GitHub PR URL per line")
    ci.add_argument("--output", type=Path, default=Path("-"))
    ci.add_argument("--review", action="store_true", help="include reviews, unresolved threads, and merge state")
    ci.add_argument("--runs", type=Path, help="compare current revisions with the local factory run index")
    ci.add_argument("--ledger", type=Path, help="record proposed follow-up actions in a local SQLite ledger")
    actions = commands.add_parser("upstream-actions", help="inspect or record exact-head follow-up claims")
    actions.set_defaults(upstream_handler=actions_command)
    actions.add_argument("--ledger", type=Path, required=True)
    operations = actions.add_subparsers(dest="operation", required=True)
    operations.add_parser("status")
    claim = operations.add_parser("claim")
    claim.add_argument("id")
    claim.add_argument("--seconds", type=int, default=900)
    finish = operations.add_parser("finish")
    finish.add_argument("id")
    finish.add_argument("--lease", required=True)
    reserve = operations.add_parser("reserve-push")
    reserve.add_argument("id")
    reserve.add_argument("--lease", required=True)
    reserve.add_argument("--failure-key", required=True)
    reserve.add_argument("--receipt", type=Path, required=True)
    reconcile = operations.add_parser("reconcile")
    reconcile.add_argument("id")
    reconcile.add_argument("--confirmed-not-sent", action="store_true",
                           help="release an uncertain push after independently confirming it was never sent")
    precedents = commands.add_parser("upstream-merges", help="compare recent merges with tracked PR gates")
    precedents.set_defaults(upstream_handler=merges_command)
    precedents.add_argument("current", type=Path, help="fresh upstream-ci --review receipt")
    precedents.add_argument("--days", type=int, default=60)
    precedents.add_argument("--limit", type=int, default=30, help="maximum examples per target branch")
    precedents.add_argument("--output", type=Path, default=Path("-"))


def actions_command(args, parser):
    try:
        ledger = ActionLedger(args.ledger)
        if args.operation == "status":
            result = ledger.status()
        elif args.operation == "claim":
            result = ledger.claim(args.id, seconds=args.seconds)
        elif args.operation == "finish":
            result = ledger.finish(args.id, args.lease)
        elif args.operation == "reserve-push":
            result = ledger.reserve_push(args.id, args.lease, args.failure_key,
                                         json.loads(args.receipt.read_text()))
        elif args.operation == "reconcile":
            result = ledger.reconcile(args.id, confirmed_not_sent=args.confirmed_not_sent)
        else:
            raise ValueError(f"unsupported upstream action: {args.operation}")
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, subprocess.SubprocessError) as exc:
        parser.error(str(exc))
    write(Path("-"), result)
    return 0


def merges_command(args, parser):
    if not (1 <= args.days <= 365 and 1 <= args.limit <= 100):
        parser.error("--days must be 1–365 and --limit must be 1–100")
    try:
        report = merge_precedents(json.loads(args.current.read_text()),
                                   days=args.days, limit=args.limit)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    write(args.output, report)
    return int(bool(report["missing_prs"]) or any(
        "error" in branch or "linked_issue_error" in branch
        or "error" in branch.get("active_rulesets", {})
        for branch in report["branches"]
    ))


def prepare_command(args, parser):
    try:
        if args.pr and (not args.runs or not PR_URL.fullmatch(args.pr)):
            raise ValueError("--pr needs an exact GitHub PR URL and --runs")
        factory_repo = Path(__file__).resolve().parents[1]
        factory = running_definition(factory_repo)["revision"] if args.runs else None
        started = time.monotonic()
        receipt = prepare(args.repo, args.contract, args.template, args.evidence_url,
                          args.output, browser=args.browser_proof)
        if args.runs:
            verified_files = {"readiness": "receipt.json"}
            if args.browser_proof and receipt["verdict"] == "verified":
                verified_files["browser"] = "browser-evidence/" + args.browser_proof.name
            spec = args.output / "run-spec.json"
            write(args.output / "factory-definition.json", running_definition(factory_repo, factory))
            (args.output / "candidate.patch").write_bytes(git(
                "diff", "--binary", receipt["base"], receipt["candidate"], "--", cwd=args.repo))
            verified_files["definition"] = "factory-definition.json"
            write(spec, {"id": f"upstream-{receipt['candidate'][:12]}-{time.time_ns()}",
                         "head": receipt["candidate"], "base": receipt["base"], "pr": args.pr,
                         "factory_revision": factory, "finished_at": datetime.now(timezone.utc).isoformat(),
                         "metrics": {"wall_seconds": round(time.monotonic() - started, 3)},
                         "receipts": verified_files, "patch": "candidate.patch"})
            run_record(spec, args.runs)
    except (OSError, ValueError, TypeError, KeyError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    print(receipt["verdict"], file=sys.stderr)
    return int(receipt["verdict"] != "verified")


def ci_command(args, parser):
    if args.ledger and not args.review:
        parser.error("--ledger requires --review")
    urls = args.urls
    try:
        if args.file:
            urls += [line.strip() for line in args.file.read_text().splitlines() if line.strip()]
        scan = time.time_ns()
        records = inspect_prs(urls, review=args.review)
        if args.runs:
            attach_local_replay(records, indexed_runs(args.runs))
        if args.ledger:
            report = ActionLedger(args.ledger).observe(records, scan)
            print(json.dumps(report), file=sys.stderr)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        parser.error(str(exc))
    write(args.output, records)
    return int(any(item["action"] == "lookup_failed"
                   or item.get("review", {}).get("action") == "lookup_failed"
                   for item in records))


def propose_command(args, parser):
    try:
        if not FULL_REVISION.fullmatch(args.base) or git("cat-file", "-t", args.base, cwd=args.repo).strip() != b"commit":
            raise ValueError("upstream proposal requires an exact base commit")
        brief = args.brief.read_text().strip()
        if not brief:
            raise ValueError("upstream proposal needs a task brief")
        for name in args.allow:
            path = Path(name)
            if path.is_absolute() or path.as_posix() != name or name == "." or ".." in path.parts or ".git" in path.parts:
                raise ValueError(f"expected a repository-relative file path: {name}")
        task = (f"{brief}\nLimit changes to these repository paths: {json.dumps(args.allow)}. "
                "Leave the edits in the checkout for independent factory replay.")
        args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
        events = args.output / "events.jsonl"
        patch = write_patch(args.repo, args.base, task, args.allow, events=events,
                            model=args.model, timeout=args.timeout, subagents=args.subagents)
        (args.output / "candidate.patch").write_bytes(patch)
        write(args.output / "proposal.json", {"base": args.base, "allowed_paths": args.allow,
              "model": args.model, "subagents": args.subagents, "patch": "candidate.patch",
              "events": "events.jsonl", "status": "proposed"})
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        parser.error(str(exc))
    return 0


def replay_command(args, parser):
    receipt = replay(args.repo, args.contract, args.output)
    write(args.output / "receipt.json", receipt)
    print(receipt["verdict"], file=sys.stderr)
    return 0 if receipt["verdict"] == "verified" else 1
