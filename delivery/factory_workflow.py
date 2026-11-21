"""Run trusted, pinned local workflow steps with durable checkpoints."""
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import re
import signal
import sqlite3
import subprocess
from tempfile import NamedTemporaryFile

from .candidate import FULL_REVISION, git
from .factory_evidence import classify_check


def file_digest(path):
    return sha256(path.read_bytes()).hexdigest()


def record(path, value):
    with NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as file:
        tmp = Path(file.name)
        try:
            json.dump(value, file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


@contextmanager
def lock(folder):
    folder.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(folder / "workflow.lock", timeout=3)
    try:
        connection.execute("BEGIN EXCLUSIVE")
        yield
    finally:
        connection.close()


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
    return stages, {"revision": plan["revision"], "plan_sha256": file_digest(path),
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
            if git("status", "--porcelain", "--untracked-files=no", cwd=workspace):
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


def intake(issue):
    """Route repository facts supplied by an authenticated intake or the operator."""
    for key, reason in (("duplicate", "existing_fix"), ("assigned", "existing_claim"),
                        ("maintainer_only", "maintainer_owned"), ("locked", "locked")):
        if issue.get(key) is True:
            return {"route": "skip", "reason": reason}
    if issue.get("state") != "OPEN":
        return {"route": "skip", "reason": "issue_not_open"}
    if issue.get("policy_checked") is not True:
        return {"route": "wait", "reason": "contribution_policy_unchecked"}
    if issue.get("scope_agreed") is not True:
        return {"route": "plan", "reason": "scope_unconfirmed"}
    if not issue.get("reproduction"):
        return {"route": "investigate", "reason": "reproduction_missing"}
    cases = issue.get("acceptance", {})
    if not all(cases.get(kind) for kind in ("expected", "control", "boundary")):
        return {"route": "plan", "reason": "acceptance_examples_missing"}
    return {"route": "implement", "reason": "scoped_reproducible_issue", "acceptance": cases}


def review_handoff(record, findings):
    actionable = []
    for finding in findings:
        if finding["head"] != record["head"]:
            continue
        if finding["disposition"] not in {"confirmed", "resolved", "maintainer_decision", "unverified"}:
            raise ValueError("invalid review disposition")
        if finding["disposition"] == "confirmed" and not finding.get("reproduction"):
            raise ValueError("confirmed feedback needs a reproduction")
        actionable.append(finding)
    return {"pr": record["url"], "head": record["head"], "base": record["base"],
            "findings": actionable, "ci": record["action"],
            "review": record.get("review", {}).get("action")}


def check_issue(url, facts):
    """Refresh GitHub state, claim and linked fixes immediately before dispatch."""
    from .upstream_ci import gh_json

    match = re.fullmatch(r"https://github\.com/([\w.-]+)/([\w.-]+)/issues/([1-9][0-9]*)",
                         url, re.ASCII)
    if not match:
        raise ValueError("expected an exact GitHub issue URL")
    owner, repo, number = match.groups()
    query = """
    query($owner:String!, $repo:String!, $number:Int!) {
      repository(owner:$owner, name:$repo) {
        issue(number:$number) {
          state locked updatedAt assignees(first:1) { totalCount }
          closedByPullRequestsReferences(first:30, includeClosedPrs:true) {
            nodes { state }
            pageInfo { hasNextPage }
          }
        }
      }
    }
    """
    response = gh_json("api", "graphql", "-f", f"query={query}", "-f", f"owner={owner}",
                       "-f", f"repo={repo}", "-F", f"number={number}")
    issue = response["data"]["repository"]["issue"]
    linked = issue["closedByPullRequestsReferences"]
    if linked["pageInfo"]["hasNextPage"]:
        return {"route": "wait", "reason": "linked_fixes_incomplete"}
    if facts.get("updated_at") and facts["updated_at"] != issue["updatedAt"]:
        return {"route": "wait", "reason": "issue_changed_since_intake"}
    return {**intake({**facts, "state": issue["state"], "locked": issue["locked"],
                      "assigned": issue["assignees"]["totalCount"] > 0,
                      "duplicate": facts.get("duplicate") is True or
                      any(pr["state"] in {"OPEN", "MERGED"} for pr in linked["nodes"])}),
            "issue": url, "updated_at": issue["updatedAt"]}
