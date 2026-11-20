#!/usr/bin/env python3
"""Stage exact candidate patches in fresh checkouts and run local runtime probes."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from run import ROOT, checkout, command, git, regression_nodes, test_env, tests

FLASK = """
from flask import Blueprint, Flask

try:
    Blueprint("", __name__)
except ValueError:
    pass
else:
    raise AssertionError("An empty blueprint name must raise ValueError")

app = Flask(__name__)
example = Blueprint("example", __name__)
example.route("/ready")(lambda: "ready")
app.register_blueprint(example)
response = app.test_client().get("/ready")
assert response.status_code == 200 and response.data == b"ready"
"""

REQUESTS = """
from requests import Request
from requests.exceptions import InvalidURL

try:
    Request("GET", "https://.example.com").prepare()
except InvalidURL:
    pass
else:
    raise AssertionError("Leading dot must raise InvalidURL")

assert Request("GET", "https://example.org/path").prepare().url == "https://example.org/path"
"""

PYTEST = """
import logging

def test_delivery_smoke(caplog):
    logger = logging.getLogger("delivery-smoke")
    logger.warning("before")
    assert [record.message for record in caplog.get_records("call")] == ["before"]
    caplog.clear()
    assert caplog.get_records("call") == []
    logger.warning("after")
    assert [record.message for record in caplog.get_records("call")] == ["after"]
"""


def runtime_args(repo, python, scratch):
    if repo == "pallets/flask":
        return [python, "-c", FLASK]
    if repo == "psf/requests":
        return [python, "-c", REQUESTS]
    smoke = scratch / "test_delivery_smoke.py"
    smoke.write_text(PYTEST)
    return [python, "-m", "pytest", "-q", str(smoke)]


def check_probes(cases, state, python):
    report = state / "runtime-controls.json"
    rows = json.loads(report.read_text()) if report.exists() else []
    done = {(row["case"], row["revision"]) for row in rows}
    for case in cases.values():
        base = state / "snapshots" / case["instance_id"]
        if not base.exists():
            continue
        for revision in ("broken", "upstream"):
            if (case["instance_id"], revision) in done:
                continue
            with TemporaryDirectory(prefix="delivery-probe-control-") as folder:
                scratch = Path(folder)
                tree = checkout(base, scratch / "stage")
                if revision == "upstream":
                    git(tree, "apply", "-", input_text=case["patch"])
                probe = command(runtime_args(case["repo"], python, scratch), tree,
                                env=test_env(case, tree), check=False)
                if (probe.returncode == 0) != (revision == "upstream"):
                    raise RuntimeError(f"Unexpected runtime control for {case['instance_id']}: "
                                       f"{revision}\n{probe.stdout}")
                rows.append({"case": case["instance_id"], "revision": revision,
                             "probe_exit": probe.returncode})
    report.write_text(json.dumps(rows, indent=2) + "\n")


def replay(case, path, cache, python):
    patch = (path.parent / "candidate.patch").read_bytes()
    evidence = {"artifact_sha256": sha256(patch).hexdigest(), "patch_applies": False}
    if not patch or not json.loads(path.read_text())["scope_pass"]:
        return evidence
    with TemporaryDirectory(prefix="delivery-replay-") as folder:
        scratch = Path(folder)
        tree = checkout(cache / case["instance_id"], scratch / "stage")
        apply = command(["git", "apply", "-"], tree, input_text=patch.decode(), check=False)
        evidence["patch_applies"] = apply.returncode == 0
        if not evidence["patch_applies"]:
            (path.parent / "replay.txt").write_text(apply.stdout)
            return evidence
        git(tree, "add", "-A")
        lint = command(["git", "diff", "--cached", "--check"], tree, check=False)
        smoke = command(runtime_args(case["repo"], python, scratch), tree,
                        env=test_env(case, tree), check=False)
        candidate_tests = tests(case, python, tree, regression_nodes(case),
                                path.parent / "candidate-tests.txt")
        (path.parent / "replay.txt").write_text(lint.stdout + smoke.stdout)
        evidence.update(diff_clean=lint.returncode == 0, runtime_probe=smoke.returncode == 0,
                        candidate_tests=candidate_tests)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("--python", required=True)
    parser.add_argument("rounds", nargs="+")
    args = parser.parse_args()
    state = args.state.resolve()
    cases = {case["instance_id"]: case for case in json.loads((ROOT / "cases.json").read_text())}
    check_probes(cases, state, args.python)
    for run_round in args.rounds:
        for path in sorted((state / run_round).glob("*/*/result.json")):
            case = cases[path.parent.parent.name]
            result = replay(case, path, state / "snapshots", args.python)
            path.with_name("replay.json").write_text(json.dumps(result, indent=2) + "\n")
            print(case["instance_id"], run_round, path.parent.name, result, flush=True)


if __name__ == "__main__":
    main()
