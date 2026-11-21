"""Run trusted, pinned local workflow steps with durable checkpoints."""
import json
import os
import platform
import re
import signal
import subprocess

from .revisions import FULL_REVISION, git
from .factory_evidence import classify_check
from .run_state import file_digest, lock, record
from .work_intake import check_issue, intake, review_handoff


def inside(root, filename):
    path = (root / filename).resolve()
    if not path.is_relative_to(root):
        raise ValueError("workflow path escapes its checkout")
    return path


def load_plan(path, workspace, tier):
    plan = json.loads(path.read_text())
    if plan["version"] != 1 or not FULL_REVISION.fullmatch(plan["revision"]):
        raise ValueError("workflow needs version 1 and an exact Git revision")
    if git("rev-parse", "HEAD", cwd=workspace).decode().strip() != plan["revision"]:
        raise ValueError("workspace is not at the reviewed revision")
    if git("status", "--porcelain", "--untracked-files=no", cwd=workspace):
        raise ValueError("workflow requires clean tracked sources")
    if tier not in ("fast", "full", "deep"):
        raise ValueError("choose fast, full, or deep checks")
    levels = {"fast": 0, "full": 1, "deep": 2}
    stages = []
    seen = set()
    for step in plan["steps"]:
        name = step["id"]
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,50}", name) or name in seen:
            raise ValueError("workflow step IDs must be distinct")
        seen.add(name)
        kind = step["kind"]
        if kind == "command":
            if not isinstance(step["argv"], list) or not step["argv"] or not all(
                isinstance(arg, str) and arg for arg in step["argv"]
            ):
                raise ValueError("trusted commands require argv")
            seconds = step.get("timeout", 120)
            if type(seconds) is not int or not 1 <= seconds <= 3600:
                raise ValueError("invalid step timeout")
            if "test_count_pattern" in step:
                if re.compile(step["test_count_pattern"]).groups != 1:
                    raise ValueError("test count pattern must contain one capture")
        elif kind != "approval":
            raise ValueError("step kind must be command or approval")
        if levels[step.get("tier", "fast")] <= levels[tier]:
            stages.append(step)
    if not stages:
        raise ValueError("no workflow steps selected")
    pinned = {name: file_digest(inside(workspace, name)) for name in plan.get("pin", [])}
    return stages, {"runner_schema": 2, "revision": plan["revision"], "plan_sha256": file_digest(path),
                    "tier": tier, "pinned_files": pinned, "recipes": plan.get("recipes", {}),
                    "environment": {"platform": platform.platform(), "python": platform.python_version(),
                                    "git": git("--version", cwd=workspace).decode().strip()}}


def execute(step, workspace, log):
    with log.open("wb") as output:
        with subprocess.Popen(step["argv"], cwd=workspace, stdin=subprocess.DEVNULL,
                              stdout=output, stderr=subprocess.STDOUT, start_new_session=True) as proc:
            try:
                code = proc.wait(timeout=step.get("timeout", 120))
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                code = None
    count = None
    if code == 0 and "test_count_pattern" in step:
        matches = re.findall(step["test_count_pattern"], log.read_text(errors="replace"))
        count = int(matches[-1]) if matches else 0
    return {**classify_check(code, count), "exit_code": code, "tests": count}


def artifacts_valid(previous, folder, workspace):
    if previous.get("log"):
        if file_digest(folder / previous["log"]) != previous["log_sha256"]:
            return False
    return all(file_digest(inside(workspace, artifact["path"])) == artifact["sha256"]
               for artifact in previous.get("artifacts", []))


def workflow(plan, workspace, folder, tier, approval=None):
    workspace = workspace.resolve()
    folder = folder.resolve()
    with lock(folder):
        steps, identity = load_plan(plan, workspace, tier)
        path = folder / "workflow.json"
        state = json.loads(path.read_text()) if path.exists() else {"identity": identity, "steps": {}}
        if state["identity"] != identity:
            raise ValueError("checkpoint inputs changed; start a new run")
        state["status"] = "verified"
        for step in steps:
            name, kind = step["id"], step["kind"]
            previous = state["steps"].get(name, {})
            if previous.get("state") == "verified":
                if not artifacts_valid(previous, folder, workspace):
                    raise ValueError("completed step artifacts changed; start a new run")
                continue
            if kind == "approval":
                expected = {**identity, "step": name}
                if "decision" in step:
                    expected["decision"] = step["decision"]
                if approval != expected:
                    state.update(status="waiting_for_approval", approval_request=expected)
                    break
                state["steps"][name] = {"state": "verified", "approval": expected}
                state.pop("approval_request", None)
                record(path, state)
                continue
            if previous.get("state") == "running" and step.get("retry_safe") is not True:
                state["status"] = "uncertain_effect"
                break
            attempts = previous.get("attempts", {"product": 0, "infrastructure": 0}).copy()
            if previous.get("state") == "running":
                attempts["infrastructure"] += 1
            limit = 2 if step.get("retry_safe") is True else 1
            if max(attempts.values()) >= limit:
                state["status"] = "budget_exhausted"
                break
            attempt = previous.get("attempt", 0) + 1
            log = folder / f"{name}.{attempt}.log"
            state["steps"][name] = {"state": "running", "attempt": attempt, "attempts": attempts}
            state["status"] = "running"
            record(path, state)
            try:
                verdict = execute(step, workspace, log)
            except FileNotFoundError:
                verdict = {"verdict": "inconclusive", "reason": "runner_unavailable"}
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=workspace, capture_output=True, text=True)
            if head.returncode or head.stdout.strip() != identity["revision"]:
                verdict = {**verdict, "verdict": "failed", "reason": "revision_changed"}
            elif git("status", "--porcelain", "--untracked-files=no", cwd=workspace):
                verdict = {**verdict, "verdict": "failed", "reason": "tracked_source_changed"}
            attachments = []
            if verdict["verdict"] == "verified":
                for artifact in step.get("artifacts", []):
                    path_to_artifact = inside(workspace, artifact)
                    if not path_to_artifact.is_file():
                        verdict = {"verdict": "inconclusive", "reason": "missing_artifact"}
                        break
                    attachments.append({"path": artifact, "sha256": file_digest(path_to_artifact)})
            if verdict["verdict"] == "failed":
                attempts["product"] += 1
            if verdict["verdict"] == "inconclusive":
                attempts["infrastructure"] += 1
            state["steps"][name] = {**verdict, "state": verdict["verdict"], "attempt": attempt, "attempts": attempts,
                                    "log": log.name, "log_sha256": file_digest(log), "artifacts": attachments}
            state["status"] = verdict["verdict"]
            record(path, state)
            if verdict["verdict"] != "verified":
                break
        record(path, state)
        return state
