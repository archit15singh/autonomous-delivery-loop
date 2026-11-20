"""Run the same regression against pinned upstream and candidate checkouts."""
from contextlib import ExitStack, contextmanager
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from .candidate import check_candidate, git, paths_between


@contextmanager
def checkout(repo, folder, revision):
    git("worktree", "add", "--detach", str(folder), revision, cwd=repo)
    try:
        yield
    finally:
        git("worktree", "remove", "--force", str(folder), cwd=repo)


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


def replay(repo, contract_file, output):
    raw_contract = contract_file.read_bytes()
    contract = json.loads(raw_contract)
    base, candidate = contract["base"], contract["candidate"]
    allowed = contract["allowed_paths"]
    regression = contract["regression_paths"]
    command = contract["command"]
    before, after = contract["before"], contract["after"]
    timeout = contract.get("timeout_seconds", 180)

    if not isinstance(command, list) or not command or any(not isinstance(arg, str) for arg in command):
        raise ValueError("command must be a nonempty argument list")
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
    if not regression or not set(regression).issubset(changed):
        raise ValueError("regression_paths must name changed files in the candidate")
    if set(regression) == set(changed):
        raise ValueError("the baseline must exclude at least one candidate file")

    # Apply only the regression fixture. All implementation files stay at the base.
    patch = git("--literal-pathspecs", "diff", "--binary", "--no-ext-diff", base, candidate, "--", *regression, cwd=repo)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with TemporaryDirectory(prefix="adl-replay-") as temporary, ExitStack() as stack:
        root = Path(temporary)
        base_folder, candidate_folder = root / "base", root / "candidate"
        stack.enter_context(checkout(repo, base_folder, base))
        stack.enter_context(checkout(repo, candidate_folder, candidate))
        subprocess.run(["git", "apply"], input=patch, cwd=base_folder, check=True)
        before_result = run_check(base_folder, command, timeout, before, output / "before.log")
        after_result = run_check(candidate_folder, command, timeout, after, output / "after.log")

    return {
        "base": base,
        "candidate": candidate,
        "contract_sha256": sha256(raw_contract).hexdigest(),
        "regression_paths": regression,
        "command": command,
        "before": before_result,
        "after": after_result,
        "verdict": "verified" if before_result["passed"] and after_result["passed"] else "unverified",
    }
