"""Command-line entry point for the delivery harness."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from datetime import datetime, timezone
import sqlite3
import subprocess
import sys
import time

from . import factory_cli
from .candidate import check_candidate, git, propose
from .factory_definition import running_definition
from .factory_learning import run_record
from .stage import stage
from .upstream import replay
from .upstream_actions import ActionLedger
from .upstream_ci import PR_URL, inspect_prs
from .upstream_merge import merge_precedents
from .upstream_pr import prepare
from .verify import Contract


def write(path, value):
    if path == Path("-"):
        print(json.dumps(value, indent=2))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("contract", type=Path)
    build = commands.add_parser("build")
    build.add_argument("--revision", required=True)
    build.add_argument("--deployment", required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--contract", type=Path)
    build.add_argument("--trusted-base")
    run = commands.add_parser("stage")
    run.add_argument("--contract", type=Path, required=True)
    run.add_argument("--bundle", type=Path, required=True)
    run.add_argument("--revision", required=True)
    run.add_argument("--deployment", required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--repairs-used", type=int, choices=range(6), default=0)
    run.add_argument("--isolate-candidate", action="store_true")
    run.add_argument("--impact-evidence", type=Path)
    run.add_argument("--sandbox-local", action="store_true")
    agent = commands.add_parser("propose")
    agent.add_argument("--contract", type=Path, required=True)
    agent.add_argument("--output", type=Path, required=True)
    agent.add_argument("--events", type=Path, required=True)
    agent.add_argument("--recipe-output", type=Path, help="record the reviewed Codex execution recipe")
    agent.add_argument("--evidence", type=Path)
    agent.add_argument("--model", default="gpt-6.2-sol")
    agent.add_argument("--timeout", type=int, default=180)
    upstream = commands.add_parser("upstream-replay")
    upstream.add_argument("--repo", type=Path, required=True)
    upstream.add_argument("--contract", type=Path, required=True)
    upstream.add_argument("--output", type=Path, required=True)
    ready = commands.add_parser("upstream-prepare", help="verify a local upstream candidate and prepare its PR body")
    ready.add_argument("--repo", type=Path, required=True)
    ready.add_argument("--contract", type=Path, required=True)
    ready.add_argument("--template", type=Path, required=True)
    ready.add_argument("--evidence-url", required=True)
    ready.add_argument("--output", type=Path, required=True)
    ready.add_argument("--browser-proof", type=Path, help="exact-base and exact-head browser receipt")
    ready.add_argument("--runs", type=Path, help="index the verification in the factory run directory")
    ready.add_argument("--pr", help="GitHub PR URL for an indexed verification run")
    ci = commands.add_parser("upstream-ci", help="inspect each PR's current head and Actions runs")
    ci.add_argument("urls", metavar="PR_URL", nargs="*")
    ci.add_argument("--file", type=Path, help="one GitHub PR URL per line")
    ci.add_argument("--output", type=Path, default=Path("-"))
    ci.add_argument("--review", action="store_true", help="include reviews, unresolved threads, and merge state")
    ci.add_argument("--ledger", type=Path, help="record proposed follow-up actions in a local SQLite ledger")
    actions = commands.add_parser("upstream-actions", help="inspect or record exact-head follow-up claims")
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
    precedents.add_argument("current", type=Path, help="fresh upstream-ci --review receipt")
    precedents.add_argument("--days", type=int, default=60)
    precedents.add_argument("--limit", type=int, default=30, help="maximum examples per target branch")
    precedents.add_argument("--output", type=Path, default=Path("-"))
    factory_cli.register(commands)
    args = parser.parse_args()
    if args.command == "factory":
        try:
            result, code = factory_cli.dispatch(args)
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, subprocess.SubprocessError) as exc:
            parser.error(str(exc))
        write(args.output, result)
        return code
    if args.command == "upstream-actions":
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
            else:
                result = ledger.reconcile(args.id, confirmed_not_sent=args.confirmed_not_sent)
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, subprocess.SubprocessError) as exc:
            parser.error(str(exc))
        write(Path("-"), result)
        return 0
    if args.command == "upstream-merges":
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
    if args.command == "upstream-prepare":
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
    if args.command == "upstream-ci":
        if args.ledger and not args.review:
            parser.error("--ledger requires --review")
        urls = args.urls
        try:
            if args.file:
                urls += [line.strip() for line in args.file.read_text().splitlines() if line.strip()]
            scan = time.time_ns()
            records = inspect_prs(urls, review=args.review)
            if args.ledger:
                report = ActionLedger(args.ledger).observe(records, scan)
                print(json.dumps(report), file=sys.stderr)
        except (OSError, ValueError, sqlite3.Error) as exc:
            parser.error(str(exc))
        write(args.output, records)
        return int(any(item["action"] == "lookup_failed"
                       or item.get("review", {}).get("action") == "lookup_failed"
                       for item in records))
    if args.command == "upstream-replay":
        receipt = replay(args.repo, args.contract, args.output)
        write(args.output / "receipt.json", receipt)
        print(receipt["verdict"], file=sys.stderr)
        return 0 if receipt["verdict"] == "verified" else 1
    if args.command == "validate":
        print(Contract.read(args.contract).digest)
        return 0
    if args.command == "propose":
        contract = Contract.read(args.contract)
        receipt = json.loads(args.evidence.read_text()) if args.evidence else None
        revision, repairs_used = propose(contract, args.output, args.events, args.model,
                                         args.timeout, receipt, recipe_output=args.recipe_output)
        print(json.dumps({"revision": revision, "repairs_used": repairs_used,
                          "patch": str(args.output)}))
        return 0
    if args.command == "build":
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        tracked_changes = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"], text=True)
        if tracked_changes or head != (args.trusted_base or args.revision):
            parser.error("build requires a clean checkout of the requested policy revision")
        contract = Contract.read(args.contract) if args.contract else None
        if args.trusted_base:
            if not contract:
                parser.error("a trusted candidate build requires a contract")
            check_candidate(args.revision, args.trusted_base, contract.allowed_changes)
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], check=True)
        args.output.mkdir(parents=True, exist_ok=True)
        artifact = args.output / "pilot.tar"
        subprocess.run(["git", "archive", "--format=tar", "-o", str(artifact),
                        args.revision, "pilot/"], check=True)
        evidence = {
            "revision": args.revision, "deployment": args.deployment, "status": "passed",
            "artifact_sha256": sha256(artifact.read_bytes()).hexdigest(),
            "policy_revision": head,
            "check": "trusted policy tests and candidate scope" if args.trusted_base else "unit tests",
        }
        if contract:
            evidence["contract_sha256"] = contract.digest
        write(args.output / "ci.json", evidence)
        return 0
    impact = json.loads(args.impact_evidence.read_text()) if args.impact_evidence else None
    report = stage(args.contract, args.bundle / "pilot.tar", args.bundle / "ci.json",
                   args.revision, args.deployment, args.repairs_used, args.isolate_candidate,
                   impact_evidence=impact, sandbox_local=args.sandbox_local)
    write(args.output, report)
    print(f"{report['verdict']} ({report['reason']})", file=sys.stderr)
    return 0 if report["verdict"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
