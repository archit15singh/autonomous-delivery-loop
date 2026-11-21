"""Replay a passing product and a source-only regression through the public CLI."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", choices=("compose", "kubernetes", "lima"))
    parser.add_argument("directory", type=Path)
    args, connection = parser.parse_known_args()
    root = args.directory.resolve()
    root.mkdir(parents=True, exist_ok=False)
    repo = root / "catalog"
    shutil.copytree(Path(__file__).resolve().parents[1] / "examples/catalog", repo)

    def git(*argv):
        return subprocess.check_output(["git", *argv], cwd=repo, text=True).strip()

    def commit(message):
        git("add", ".")
        git("-c", "user.name=ADL fixture", "-c", "user.email=fixture@localhost",
            "-c", "commit.gpgsign=false", "commit", "-qm", message)
        return git("rev-parse", "HEAD")

    git("init", "-q")
    base = commit("Reviewed catalog policy and product")
    cli = [sys.executable, "-B", "-m", "delivery", "factory", "runtime"]
    common = ["--repo", str(repo), "--base", base, "--spec", "runtime.json", "--backend", args.backend]
    for label, expected in (("passing", "verified"), ("regression", "failed")):
        revision = base
        if label == "regression":
            app = repo / "app.py"
            app.write_text(app.read_text().replace('["notebook"]', '[]'))
            revision = commit("Return the wrong catalog")
        state = str(root / label)
        subprocess.run([*cli, "plan", *common, "--revision", revision], check=True, stdout=subprocess.DEVNULL)
        result = subprocess.run([*cli, "run", *common, "--revision", revision, "--state", state, *connection],
                                stdout=subprocess.PIPE, text=True)
        receipt = json.loads(subprocess.check_output([*cli, "inspect", "--state", state]))
        if (result.returncode != int(expected == "failed") or receipt != json.loads(result.stdout)
                or receipt["verdict"] != expected or receipt["cleanup"]["status"] != "confirmed"
                or receipt["product"]["revision"] != revision
                or (label == "regression" and receipt["reason"] != "probe_failed")):
            raise RuntimeError(f"unexpected {label} result: {receipt}")
        subprocess.run([*cli, "cleanup", "--state", state, *connection], check=True, stdout=subprocess.DEVNULL)
        print(label, revision, receipt["verdict"], receipt["reason"], flush=True)


if __name__ == "__main__":
    main()
