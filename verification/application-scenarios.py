"""Replay exact application revisions and check their isolated runtime receipts."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--socket", required=True, type=Path)
    args = parser.parse_args()
    args.state.mkdir(parents=True)
    repo = args.state / "product"
    shutil.copytree(Path(__file__).resolve().parents[1] / "examples/order-service", repo)

    def git(*command):
        return subprocess.check_output(["git", *command], cwd=repo, text=True).strip()

    def commit(label):
        git("add", ".")
        git("-c", "user.name=ADL verifier", "-c", "user.email=fixture@localhost",
            "-c", "commit.gpgsign=false", "commit", "-qm", label)
        return git("rev-parse", "HEAD")

    git("init", "-q")
    base = commit("Reviewed application and outcome")
    cli = [sys.executable, "-B", "-m", "delivery", "factory", "runtime"]
    common = ["--repo", str(repo), "--base", base, "--spec", "runtime.json", "--backend", "compose"]
    cases = (
        ("passing", None, "verified", None),
        ("wrong-value", ('accepted", quantity', 'accepted", quantity + 1'), "failed", "adl:order:accepted"),
        ("lost-job", ('processed", quantity', 'processed", quantity + 1'), "failed", "adl:order:processed"),
        ("invalid-write", ("            return False", '            self.store.set("adl:order:invalid", "unexpected")\n            return False'),
         "failed", "adl:order:invalid"),
    )
    for label, edit, verdict, wrong_key in cases:
        git("checkout", "--detach", "-q", base)
        revision = base
        if edit:
            path = repo / "orders.py"
            source = path.read_text()
            assert source.count(edit[0]) == 1
            path.write_text(source.replace(*edit))
            revision = commit(label)
        state = args.state / label
        result = subprocess.run([*cli, "run", *common, "--revision", revision,
                                 "--state", str(state), "--socket", str(args.socket)], capture_output=True, text=True)
        path = state / "runtime.json"
        if not path.exists():
            raise RuntimeError(result.stderr)
        receipt = json.loads(path.read_text())
        assert result.returncode == int(verdict != "verified"), receipt
        assert receipt["verdict"] == verdict and receipt["cleanup"]["status"] == "confirmed", receipt
        assert receipt["revision"] == revision and receipt["product"]["source_bundle_sha256"]
        assert receipt["oci_config_digest"] == receipt["image_id"]
        assert receipt["observation"]["ci"]["artifact_sha256"] == receipt["oci_config_digest"].removeprefix("sha256:")
        if wrong_key:
            step = receipt["observation"]["steps"][-1]
            assert receipt["reason"] == "scenario_step_failed" and step["key"] == wrong_key, receipt
            assert any(check["kind"] == "http" and check["passed"] for check in receipt["observation"]["steps"])
        subprocess.run([*cli, "cleanup", "--state", str(state), "--socket", str(args.socket)],
                       check=True, stdout=subprocess.DEVNULL)
        assert json.loads(path.read_text()) == receipt
        print(label, verdict, receipt["reason"], flush=True)

    git("checkout", "--detach", "-q", base)
    contract = repo / "outcome.json"
    contract.write_text(contract.read_text().replace('"expect": "3"', '"expect": "4"'))
    revision = commit("Candidate attempts to replace its own acceptance contract")
    state = args.state / "tampered"
    result = subprocess.run([*cli, "run", *common, "--revision", revision,
                             "--state", str(state), "--socket", str(args.socket)], capture_output=True, text=True)
    assert result.returncode and "protected paths" in result.stderr and not state.exists()
    print("tampered acceptance rejected before runtime allocation")


if __name__ == "__main__":
    main()
