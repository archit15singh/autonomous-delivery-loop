"""Command-line entry point for the delivery harness."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from .candidate import check_candidate, propose
from .stage import stage
from .upstream import replay
from .upstream_ci import inspect_prs
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
    agent = commands.add_parser("propose")
    agent.add_argument("--contract", type=Path, required=True)
    agent.add_argument("--output", type=Path, required=True)
    agent.add_argument("--events", type=Path, required=True)
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
    ci = commands.add_parser("upstream-ci", help="inspect each PR's current head and Actions runs")
    ci.add_argument("urls", metavar="PR_URL", nargs="*")
    ci.add_argument("--file", type=Path, help="one GitHub PR URL per line")
    ci.add_argument("--output", type=Path, default=Path("-"))
    ci.add_argument("--review", action="store_true", help="include reviews, unresolved threads, and merge state")
    precedents = commands.add_parser("upstream-merges", help="compare recent merges with tracked PR gates")
    precedents.add_argument("current", type=Path, help="fresh upstream-ci --review receipt")
    precedents.add_argument("--days", type=int, default=60)
    precedents.add_argument("--limit", type=int, default=30, help="maximum examples per target branch")
    precedents.add_argument("--output", type=Path, default=Path("-"))
    args = parser.parse_args()
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
            receipt = prepare(args.repo, args.contract, args.template, args.evidence_url, args.output)
        except (OSError, ValueError, TypeError, KeyError, subprocess.CalledProcessError) as exc:
            parser.error(str(exc))
        print(receipt["verdict"], file=sys.stderr)
        return int(receipt["verdict"] != "verified")
    if args.command == "upstream-ci":
        urls = args.urls
        try:
            if args.file:
                urls += [line.strip() for line in args.file.read_text().splitlines() if line.strip()]
            records = inspect_prs(urls, review=args.review)
        except (OSError, ValueError) as exc:
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
                                         args.timeout, receipt)
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
                   impact_evidence=impact)
    write(args.output, report)
    print(f"{report['verdict']} ({report['reason']})", file=sys.stderr)
    return 0 if report["verdict"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
