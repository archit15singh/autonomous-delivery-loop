"""Dispatch one approved owned issue through the pilot delivery entry points."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

from .candidate import FULL_REVISION, git
from .factory_definition import running_definition
from .factory_workflow import check_issue, lock, record
from .upstream_actions import ActionLedger, digest
from .upstream_ci import gh_json
from .verify import Contract

REPOSITORY = "archit15singh/autonomous-delivery-loop"
ISSUE = re.compile(rf"https://github\.com/{REPOSITORY}/issues/([1-9][0-9]*)")
LABEL = "adl-candidate"


def issue_plan(url, spec_path):
    match = ISSUE.fullmatch(url)
    if not match:
        raise ValueError("choose an issue in the owned factory repository")
    spec = json.loads(spec_path.read_text())
    contract = Contract.read(spec_path)
    if set(contract.allowed_changes) != {"pilot/service.py"} or contract.impact:
        raise ValueError("the owned issue pilot supports changes to the HTTP service only")
    if not isinstance(spec.get("reproduction"), str) or not spec["reproduction"].strip():
        raise ValueError("provide the issue reproduction in the spec")
    reproduction_path = spec.get("reproduction_path")
    if sum(probe.path == reproduction_path for probe in contract.probes) != 1:
        raise ValueError("reproduction_path must identify exactly one contract probe")
    number = match[1]
    issue = gh_json("api", f"repos/{REPOSITORY}/issues/{number}")
    if "pull_request" in issue or LABEL not in {label["name"] for label in issue["labels"]}:
        raise ValueError("apply the ADL opt-in label to an owned issue")
    route = check_issue(url, {"updated_at": issue["updated_at"], "policy_checked": True,
                              "scope_agreed": True, "reproduction": spec["reproduction"],
                              "acceptance": contract.acceptance or {}})
    if route["route"] != "implement":
        raise ValueError(f"issue is not eligible: {route['reason']}")
    base = gh_json("api", f"repos/{REPOSITORY}/git/ref/heads/main")["object"]["sha"]
    if not FULL_REVISION.fullmatch(base):
        raise ValueError("GitHub did not return a full main revision")
    snapshot = {name: issue[name] for name in ("id", "title", "body", "updated_at")}
    return {"issue": url, "number": int(number), "base": base,
            "snapshot_sha256": digest(snapshot), "spec_sha256": contract.digest}


def approve(url, spec):
    plan = issue_plan(url, spec)
    if not gh_json("api", f"repos/{REPOSITORY}")["permissions"]["push"]:
        raise ValueError("approval requires an authorized operator")
    return {"plan": plan, "operator": gh_json("api", "user")["login"],
            "approved_at": datetime.now(timezone.utc).isoformat()}


@contextmanager
def checkout(repo, folder, base):
    git("worktree", "add", "--detach", str(folder), base, cwd=repo)
    try:
        yield folder
    finally:
        git("worktree", "remove", "--force", str(folder), cwd=repo)


def delivery(workspace, *arguments, check=True):
    return subprocess.run([sys.executable, "-m", "delivery", *map(str, arguments)],
                          cwd=workspace, check=check, stdout=sys.stderr)


def stage_candidate(workspace, spec, bundle, output, base, revision, deployment):
    delivery(workspace, "build", "--contract", spec, "--trusted-base", base,
             "--revision", revision, "--deployment", deployment, "--output", bundle)
    delivery(workspace, "stage", "--contract", spec, "--bundle", bundle, "--output", output,
             "--revision", revision, "--deployment", deployment, "--sandbox-local", check=False)
    return json.loads(output.read_text())


def generate(repo, paths, plan, spec, model, timeout, key):
    base = plan["base"]
    with TemporaryDirectory(prefix="adl-issue-") as directory:
        folder = Path(directory)
        with checkout(repo, folder / "work", base) as workspace:
            baseline = stage_candidate(workspace, spec, paths / "baseline-bundle",
                                       paths / "baseline.json", base, base, f"{key[:16]}-base")
            reproduction = json.loads(spec.read_text())["reproduction_path"]
            if (baseline["reason"] != "probe_failed"
                    or [probe["path"] for probe in baseline["probes"] if not probe["passed"]] != [reproduction]):
                raise ValueError("approved probe did not reproduce the issue on main")
            patch = paths / "candidate.patch"
            delivery(workspace, "propose", "--contract", spec, "--output", patch,
                     "--events", paths / "codex.jsonl", "--recipe-output", paths / "recipe.json",
                     "--model", model, "--timeout", timeout)
            git("apply", "--index", str(patch), cwd=workspace)
            git("commit", "-m", f"fix: resolve owned issue #{plan['number']}", cwd=workspace)
            candidate = git("rev-parse", "HEAD", cwd=workspace).decode().strip()
        with checkout(repo, folder / "judge", base) as workspace:
            report = stage_candidate(workspace, spec, paths / "candidate-bundle",
                                     paths / "candidate.json", base, candidate, key[:16])
            if report["verdict"] != "verified":
                raise ValueError(f"independent candidate verification returned {report['reason']}")
    return candidate


def publish(repo, paths, plan, candidate):
    branch = f"factory/issue-{plan['number']}"
    ref = f"refs/heads/{branch}"
    remote = f"git@github.com:{REPOSITORY}.git"
    base = plan["base"]
    before = json.loads((paths / "baseline.json").read_text())
    after = json.loads((paths / "candidate.json").read_text())
    def counts(receipt):
        return f"{sum(p['passed'] for p in receipt['probes'])}/{len(receipt['probes'])}"
    body = paths / "draft.md"
    body.write_text(
        f"""Refs #{plan['number']}

Approved issue → sandboxed Codex patch → trusted HTTP verifier → draft PR.

| Live HTTP probes | Main {base[:12]} | Candidate {candidate[:12]} |
| --- | --- | --- |
| Passing | {counts(before)} | {counts(after)} |

Full candidate {candidate}. Approved contract SHA-256 {plan['spec_sha256']}.
The HTTP service ran in an isolated local staging process. The trusted policy tests
ran on the approved base and GitHub runs the candidate checks after publication.
"""
    )
    refs = git("ls-remote", remote, ref, cwd=repo).decode().split()
    if not refs:
        git("push", f"--force-with-lease={ref}:", remote, f"{candidate}:{ref}", cwd=repo)
    elif refs != [candidate, ref]:
        raise ValueError("existing draft branch differs from verified candidate")
    existing = gh_json("pr", "list", "--repo", REPOSITORY, "--head", branch,
                       "--base", "main", "--state", "all", "--json", "url")
    if len(existing) > 1:
        raise ValueError("found multiple drafts for the issue branch")
    url = existing[0]["url"] if existing else subprocess.check_output(
        ["gh", "pr", "create", "--repo", REPOSITORY, "--base", "main", "--head", branch,
         "--title", f"Resolve owned issue #{plan['number']}", "--draft", "--body-file", str(body)],
        text=True).strip()
    pr = gh_json("pr", "view", url, "--json", "url,headRefOid,baseRefOid,isDraft")
    if pr != {"url": url, "headRefOid": candidate, "baseRefOid": base, "isDraft": True}:
        raise ValueError("draft PR identity does not match the verified candidate")
    return url


def run_issue(repo, url, spec, approval, ledger_path, output, model, timeout):
    started = time.monotonic()
    plan = issue_plan(url, spec)
    if approval is None:
        return {"state": "waiting_for_approval", "plan": plan}
    grant = json.loads(approval.read_text())
    if grant.get("plan") != plan:
        return {"state": "stale_approval", "plan": plan}
    operator = gh_json("api", "user")["login"]
    if grant.get("operator") != operator or not gh_json("api", f"repos/{REPOSITORY}")["permissions"]["push"]:
        raise ValueError("the approved operator must dispatch the issue")
    if running_definition(repo)["revision"] != plan["base"]:
        raise ValueError("dispatch from the exact reviewed main checkout")
    if (sys.platform != "darwin" or Path(sys.executable).resolve().is_relative_to(Path.home().resolve())):
        raise ValueError("use a macOS runner with Python installed outside the home directory")
    ledger = ActionLedger(ledger_path)
    key = digest(plan)
    output = output.resolve() / key
    with lock(output):
        return dispatch(repo, url, spec, grant, ledger, output, plan, model, timeout, key, started)


def dispatch(repo, url, spec, grant, ledger, output, plan, model, timeout, key, started):
    checkpoint = output / "verified-head.json"
    prior = ledger.reserve_once("owned_issue", url, key)
    if prior is not None and (prior["identity"] != key or prior["result"] or not checkpoint.exists()):
        return {"state": "already_dispatched", "reservation": prior}
    if prior is None:
        frozen_spec = output / "contract.json"
        frozen_spec.write_bytes(spec.read_bytes())
        if Contract.read(frozen_spec).digest != plan["spec_sha256"]:
            raise ValueError("specification changed during dispatch")
        record(output / "approval.json", grant)
        candidate = generate(repo, output, plan, frozen_spec, model, timeout, key)
        record(checkpoint, {"candidate": candidate})
    else:
        candidate = json.loads(checkpoint.read_text())["candidate"]
    if issue_plan(url, spec) != plan:
        return {"state": "stale_before_publication", "candidate": candidate}
    pr = publish(repo, output, plan, candidate)
    result = {"state": "published", "issue": url, "pr": pr, "head": candidate,
              "base": plan["base"], "approval": key,
              "wall_seconds": round(time.monotonic() - started, 3),
              "human_approvals": 1}
    ledger.finish_once("owned_issue", url, key, result)
    record(output / "publication.json", result)
    return result
