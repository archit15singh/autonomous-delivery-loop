"""Replay exact good and bad products through the public CLI and compare runtime receipts."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def compare(root):
    baseline = json.loads((root / "compose/results.json").read_text())
    candidate = json.loads((root / "firecracker/results.json").read_text())
    arms = {"compose": baseline, "firecracker": candidate}
    if (set(baseline) != set(candidate) or set(baseline) != {
            "passing", "regression", "stale-identity", "tampered-acceptance"}):
        raise RuntimeError("expected all four independent runtime controls in both arms")
    identity = ("revision", "verdict", "reason", "cleanup", "source_sha256", "contract_sha256")
    for label, baseline_row in baseline.items():
        candidate_row = candidate[label]
        if any(candidate_row[key] != baseline_row[key] for key in identity):
            raise RuntimeError(f"runtime backends disagreed on {label}")
        if label == "tampered-acceptance":
            continue
        guest = candidate_row["guest"]
        if guest != {"network_interfaces": ["lo"], "read_only_drives": True, "app_uid": 65534,
                     "memory_mb": 64, "cpu_quota": "50000 100000"}:
            raise RuntimeError(f"Firecracker guest policy did not hold on {label}")
    report = {"matched_controls": len(baseline), "arms": arms,
              "elapsed_includes_startup_and_cleanup": True, "trials_per_control": 1}
    write(root / "comparison.json", report)
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", choices=("compose", "kubernetes", "lima", "firecracker", "compare"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--extended", action="store_true")
    args, connection = parser.parse_known_args()
    root = args.directory.resolve()
    if args.backend == "compare":
        compare(root)
        return
    root.mkdir(parents=True, exist_ok=False)
    repo = root / "catalog"
    shutil.copytree(Path(__file__).resolve().parents[1] / "examples/catalog", repo)

    def git(*argv):
        identity = {"GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z"}
        return subprocess.check_output(["git", *argv], cwd=repo, text=True, env={**os.environ, **identity}).strip()

    def commit(message):
        git("add", ".")
        git("-c", "user.name=ADL fixture", "-c", "user.email=fixture@localhost",
            "-c", "commit.gpgsign=false", "commit", "-qm", message)
        return git("rev-parse", "HEAD")

    git("init", "-q")
    base = commit("Reviewed catalog policy and product")
    cli = [sys.executable, "-B", "-m", "delivery", "factory", "runtime"]
    common = ["--repo", str(repo), "--base", base, "--spec", "runtime.json", "--backend", args.backend]
    cases = [("passing", "verified", "all_required_evidence_passed"), ("regression", "failed", "probe_failed")]
    if args.extended:
        cases.append(("stale-identity", "inconclusive", "wrong_deployment"))
    rows = {}
    app = repo / "app.py"
    original = app.read_text()
    for label, expected, reason in cases:
        git("checkout", "--detach", "-q", base)
        revision = base
        if label == "regression":
            app.write_text(original.replace('["notebook"]', '[]'))
            revision = commit("Return the wrong catalog")
        elif label == "stale-identity":
            app.write_text(original.replace('os.environ["ADL_REVISION"]', '"0" * 40'))
            revision = commit("Return a stale deployment identity")
        state = str(root / label)
        subprocess.run([*cli, "plan", *common, "--revision", revision], check=True, stdout=subprocess.DEVNULL)
        started = time.monotonic()
        result = subprocess.run([*cli, "run", *common, "--revision", revision, "--state", state, *connection],
                                stdout=subprocess.PIPE, text=True)
        elapsed_ms = round(1000 * (time.monotonic() - started))
        receipt = json.loads(subprocess.check_output([*cli, "inspect", "--state", state]))
        if (result.returncode != int(expected != "verified") or receipt != json.loads(result.stdout)
                or receipt["verdict"] != expected or receipt["cleanup"]["status"] != "confirmed"
                or receipt["product"]["revision"] != revision or receipt["reason"] != reason):
            raise RuntimeError(f"unexpected {label} result: {receipt}")
        cleanup_options = [] if args.backend == "firecracker" else connection
        repeated = subprocess.check_output([*cli, "cleanup", "--state", state, *cleanup_options])
        if json.loads(repeated) != receipt:
            raise RuntimeError(f"{label}: repeated cleanup changed the verified receipt")
        rows[label] = {"revision": revision, "verdict": expected, "reason": reason,
                       "cleanup": receipt["cleanup"]["status"], "elapsed_ms": elapsed_ms,
                       "source_sha256": receipt["product"]["source_sha256"],
                       "contract_sha256": receipt["product"]["contract_sha256"],
                       "guest": receipt.get("observation", {}).get("guest"),
                       "timing_ms": receipt.get("timing_ms")}
        write(root / "results.json", rows)
        print(label, revision, receipt["verdict"], receipt["reason"], f"{elapsed_ms} ms", flush=True)

    if args.extended:
        git("checkout", "--detach", "-q", base)
        contract = repo / "outcome.json"
        original_contract = sha256(contract.read_bytes()).hexdigest()
        contract.write_text(contract.read_text().replace("notebook", "wrong"))
        revision = commit("Attempt to change protected acceptance")
        state = root / "tampered-acceptance"
        rejected = subprocess.run([*cli, "run", *common, "--revision", revision,
                                   "--state", str(state), *connection], capture_output=True, text=True)
        if rejected.returncode == 0 or "protected paths" not in rejected.stderr or state.exists():
            raise RuntimeError("candidate could change acceptance or created runtime state before rejection")
        rows["tampered-acceptance"] = {"revision": revision, "verdict": "rejected", "reason": "protected_paths",
                                      "cleanup": "no_resources", "source_sha256": sha256(app.read_bytes()).hexdigest(),
                                      "contract_sha256": original_contract}
        write(root / "results.json", rows)


if __name__ == "__main__":
    main()
