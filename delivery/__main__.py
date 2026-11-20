"""Command-line entry point for the delivery harness."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from .stage import stage
from .verify import Contract


def write(path, value):
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
    run = commands.add_parser("stage")
    run.add_argument("--contract", type=Path, required=True)
    run.add_argument("--bundle", type=Path, required=True)
    run.add_argument("--revision", required=True)
    run.add_argument("--deployment", required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "validate":
        print(Contract.read(args.contract).digest)
        return 0
    if args.command == "build":
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        tracked_changes = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"], text=True)
        if args.revision != head or tracked_changes:
            parser.error("build requires a clean checkout of the requested full revision")
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], check=True)
        args.output.mkdir(parents=True, exist_ok=True)
        artifact = args.output / "pilot.tar"
        subprocess.run(["git", "archive", "--format=tar", "-o", str(artifact),
                        args.revision, "pilot/"], check=True)
        write(args.output / "ci.json", {
            "revision": args.revision, "deployment": args.deployment, "status": "passed",
            "artifact_sha256": sha256(artifact.read_bytes()).hexdigest(),
        })
        return 0
    report = stage(args.contract, args.bundle / "pilot.tar", args.bundle / "ci.json",
                   args.revision, args.deployment)
    write(args.output, report)
    print(f"{report['verdict']} ({report['reason']})")
    return 0 if report["verdict"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
