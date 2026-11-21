"""Run the same regression against pinned upstream and candidate checkouts."""
from hashlib import sha256
import json
import platform
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from .revisions import check_candidate, checkout, git, paths_between


def validate_command(command):
    if not isinstance(command, list) or not command or any(not isinstance(arg, str) for arg in command):
        raise ValueError("command must be a nonempty argument list")


def run_check(folder, command, timeout, expected, log):
    with log.open("wb") as output:
        try:
            result = subprocess.run(
                command, cwd=folder, stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT, timeout=timeout,
            )
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            exit_code = None
    data = log.read_bytes()
    signal = expected["contains"]
    matched = signal.encode() in data
    return {
        "exit": exit_code,
        "expected_exit": expected["exit"],
        "signal": signal,
        "signal_observed": matched,
        "log": log.name,
        "log_sha256": sha256(data).hexdigest(),
        "passed": exit_code == expected["exit"] and matched,
    }


def readiness_checks(profile):
    def named_check(item):
        if not isinstance(item.get("name"), str) or not item["name"].strip():
            raise ValueError("each readiness check needs a reviewer-facing name")
        validate_command(item["command"])
        if not isinstance(item.get("contains"), str) or not item["contains"].strip():
            raise ValueError("each readiness check needs an expected output signal")
        return item

    setup = named_check(profile["setup"])
    controls = profile["controls"]
    if not isinstance(controls, list):
        raise ValueError("controls must be a list")
    for control in controls:
        named_check(control)
    exclusions = profile["exclusions"]
    kinds = [control["kind"] for control in controls]
    optional = {"boundary", "failure"}
    if (not isinstance(exclusions, dict) or set(exclusions) - optional
        or any(not isinstance(reason, str) or not reason.strip() for reason in exclusions.values())
        or kinds.count("normal") < 1 or not optional.intersection(kinds)
        or set(kinds) & set(exclusions)
        or set(kinds) | set(exclusions) != {"normal", "boundary", "failure"}):
        raise ValueError("run a normal control and a boundary or failure control, and explain any omitted class")
    if not isinstance(profile["live_entrypoint"], str) or not profile["live_entrypoint"].strip():
        raise ValueError("describe the live entry point exercised by the replay")
    return setup, controls, named_check(profile["suite"])


def run_named(folder, check, timeout, log):
    result = run_check(folder, check["command"], timeout,
                       {"exit": 0, "contains": check["contains"]}, log)
    return {**result, "name": check["name"], "command": check["command"]}


def replay(repo, contract_file, output, *, require_readiness=False):
    raw_contract = contract_file.read_bytes()
    contract = json.loads(raw_contract)
    base, candidate = contract["base"], contract["candidate"]
    allowed = contract["allowed_paths"]
    regression = contract["regression_paths"]
    command = contract["command"]
    before, after = contract["before"], contract["after"]
    timeout = contract.get("timeout_seconds", 180)

    validate_command(command)
    if require_readiness and "readiness" not in contract:
        raise ValueError("submission needs a local readiness profile")
    profile = contract.get("readiness")
    checks = readiness_checks(profile) if "readiness" in contract else None
    if type(timeout) is not int or timeout < 1:
        raise ValueError("timeout_seconds must be positive")
    if (
        type(before["exit"]) is not int or before["exit"] < 1
        or type(after["exit"]) is not int or after["exit"] != 0
        or any(not isinstance(item["contains"], str) or not item["contains"] for item in (before, after))
    ):
        raise ValueError("supply a failing base exit, a successful candidate exit, and both output signals")

    repo = repo.resolve()
    check_candidate(candidate, base, allowed, cwd=repo)
    changed = paths_between(base, candidate, cwd=repo)
    if (not regression and not checks) or not set(regression).issubset(changed):
        raise ValueError("regression_paths must name changed files in the candidate")
    if set(regression) == set(changed):
        raise ValueError("the baseline must exclude at least one candidate file")

    # Apply only the regression fixture. All implementation files stay at the base.
    patch = None
    if regression:
        patch = git("--literal-pathspecs", "diff", "--binary", "--no-ext-diff",
                    base, candidate, "--", *regression, cwd=repo)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with TemporaryDirectory(prefix="adl-replay-") as temporary:
        root = Path(temporary)
        base_folder, candidate_folder = root / "base", root / "candidate"
        setup_results, controlled = {}, {"baseline": [], "candidate": []}
        suite_result = None
        reproduction = {}
        for label, folder, revision, expected, log in (
            ("baseline", base_folder, base, before, "before.log"),
            ("candidate", candidate_folder, candidate, after, "after.log"),
        ):
            with checkout(repo, folder, revision):
                if label == "baseline" and patch:
                    apply = ["git", "apply", "--index"] if checks else ["git", "apply"]
                    subprocess.run(apply, input=patch, cwd=folder, check=True)
                expected_tree = git("write-tree", cwd=folder) if checks else None
                if checks:
                    setup, controls, suite = checks
                    result = run_named(folder, setup, timeout, output / f"{label}-setup.log")
                    setup_results[label] = result
                    if not result["passed"]:
                        reproduction[label] = {"passed": False, "skipped": "setup failed"}
                        continue
                reproduction[label] = run_check(folder, command, timeout, expected, output / log)
                if checks:
                    controlled[label] = [
                        run_named(folder, control, timeout, output / f"{label}-control-{index}.log")
                        for index, control in enumerate(controls, 1)
                    ]
                    if label == "candidate":
                        suite_result = run_named(folder, suite, timeout, output / "suite.log")
                    # Logs and build caches may be untracked. Preserve the tested tracked sources.
                    if (git("rev-parse", "HEAD", cwd=folder).decode().strip() != revision
                        or git("diff", "--name-only", cwd=folder)
                        or git("write-tree", cwd=folder) != expected_tree):
                        raise ValueError(f"{label} commands changed the tracked checkout")
    before_result, after_result = reproduction["baseline"], reproduction["candidate"]
    passed = before_result["passed"] and after_result["passed"]
    readiness = {}
    if checks:
        passed = (passed and all(item["passed"] for item in setup_results.values())
                  and all(item["passed"] for results in controlled.values() for item in results)
                  and bool(suite_result and suite_result["passed"]))
        readiness = {"readiness": {
            "platform": platform.platform(),
            "live_entrypoint": profile["live_entrypoint"],
            "setup": setup_results,
            "controls": controlled,
            "suite": suite_result,
            "exclusions": profile["exclusions"],
        }}
    return {
        "base": base,
        "candidate": candidate,
        "contract_sha256": sha256(raw_contract).hexdigest(),
        "regression_paths": regression,
        "command": command,
        "before": before_result,
        "after": after_result,
        **readiness,
        "verdict": "verified" if passed else "unverified",
    }
