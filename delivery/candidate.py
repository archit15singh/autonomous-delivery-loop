"""Run Codex in a disposable checkout and export a scope-checked patch."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
from tempfile import TemporaryDirectory

from .verify import advice

FULL_REVISION = re.compile(r"[0-9a-f]{40}")


def git(*args, cwd=None):
    return subprocess.check_output(["git", *args], cwd=cwd)


def check_scope(changed, allowed):
    outside = sorted(set(changed) - set(allowed))
    if outside:
        raise ValueError("Candidate changed protected paths: " + ", ".join(outside))


def paths_between(base, candidate):
    return git("diff", "--no-renames", "--name-only", "-z", base, candidate, "--").decode().split("\0")[:-1]


def check_candidate(head, base, allowed):
    if not FULL_REVISION.fullmatch(head) or not FULL_REVISION.fullmatch(base):
        raise ValueError("trusted and candidate revisions must be full Git SHAs")
    git("merge-base", "--is-ancestor", base, head)
    check_scope(paths_between(base, head), allowed)


def repair_context(contract, revision, receipt):
    if receipt is None:
        return "", 0
    repairs = receipt.get("repairs_used")
    if (receipt.get("revision") != revision or receipt.get("contract_sha256") != contract.digest
            or type(repairs) is not int or repairs < 0
            or advice(receipt.get("verdict"), receipt.get("reason"), repairs,
                      contract.max_repairs) != "repair"):
        raise ValueError("evidence does not authorize a repair for this revision and contract")
    failed = [
        {"path": p["path"], "expected": p["expect"], "observed": p["observed"]}
        for p in receipt["probes"] if not p["passed"]
    ]
    return "\nTrusted verification result:\n" + json.dumps(failed, indent=2), repairs + 1


def propose(contract, output, events, model, timeout, receipt=None):
    root = Path(git("rev-parse", "--show-toplevel").decode().strip())
    base = git("rev-parse", "HEAD", cwd=root).decode().strip()
    context, attempt = repair_context(contract, base, receipt)
    output.parent.mkdir(parents=True, exist_ok=True)
    events.parent.mkdir(parents=True, exist_ok=True)
    prompt = (
        "Use $deliver-outcome. Implement the approved outcome in this clean Git checkout.\n"
        "The harness already confirmed the checkout and state. Use python3 -m unittest discover -s tests.\n"
        f"Approved outcome: {contract.outcome}\n"
        f"Files you may modify: {', '.join(contract.allowed_changes)}\n"
        f"Required HTTP behavior: {json.dumps([p.__dict__ for p in contract.probes])}\n"
        "Leave changes in the working tree and report your local checks. "
        "The release operator owns GitHub and the independent verdict."
        + context
    )
    args = [
        "codex", "-a", "never", "exec", "--ignore-user-config", "--ephemeral",
        "--sandbox", "workspace-write", "-c", 'web_search="disabled"',
        "-c", "sandbox_workspace_write.network_access=false",
        "-c", 'model_reasoning_effort="medium"', "--model", model, "--json", prompt,
    ]
    with TemporaryDirectory(prefix="adl-codex-") as folder:
        checkout = Path(folder) / "checkout"
        git("clone", "--quiet", "--no-local", str(root), str(checkout))
        git("checkout", "--quiet", "--detach", base, cwd=checkout)
        git("remote", "remove", "origin", cwd=checkout)
        with events.open("wb") as log, events.with_suffix(".stderr").open("wb") as stderr:
            proc = subprocess.Popen(args, cwd=checkout, stdout=log, stderr=stderr,
                                    start_new_session=True)
            try:
                result = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                raise RuntimeError(f"Codex exceeded the {timeout}s attempt budget")
        if result:
            raise RuntimeError(f"Codex exited with status {result}; see {events}")
        git("add", "-A", cwd=checkout)
        paths = git("diff", "--no-renames", "--name-only", "-z", base, "--", cwd=checkout)
        check_scope(paths.decode().split("\0")[:-1], contract.allowed_changes)
        patch = git("diff", "--binary", base, "--", cwd=checkout)
        if not patch:
            raise ValueError("Codex produced no change")
        output.write_bytes(patch)
    return base, attempt
