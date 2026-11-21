"""Command-line entry point for the delivery harness."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from . import factory_cli, upstream_cli
from .cli_output import write
from .candidate import propose
from .revisions import check_candidate
from .stage import stage
from .verify import Contract


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
    upstream_cli.register(commands)
    factory_cli.register(commands)
    args = parser.parse_args()
    if args.command == "factory":
        try:
            result, code = factory_cli.dispatch(args)
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, subprocess.SubprocessError) as exc:
            parser.error(str(exc))
        write(args.output, result)
        return code
    if hasattr(args, "upstream_handler"):
        return args.upstream_handler(args, parser)
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
    if args.command != "stage":
        parser.error(f"unsupported delivery command: {args.command}")
    impact = json.loads(args.impact_evidence.read_text()) if args.impact_evidence else None
    report = stage(args.contract, args.bundle / "pilot.tar", args.bundle / "ci.json",
                   args.revision, args.deployment, args.repairs_used, args.isolate_candidate,
                   impact_evidence=impact, sandbox_local=args.sandbox_local)
    write(args.output, report)
    print(f"{report['verdict']} ({report['reason']})", file=sys.stderr)
    return 0 if report["verdict"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
