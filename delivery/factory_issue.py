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
from .factory_workflow import check_issue, record
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
            if baseline["verdict"] != "failed" or baseline["reason"] != "probe_failed":
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
    git("push", f"--force-with-lease={ref}:", remote, f"{candidate}:{ref}", cwd=repo)
    url = subprocess.check_output(
        ["gh", "pr", "create", "--repo", REPOSITORY, "--base", "main", "--head", branch,
         "--title", f"Resolve owned issue #{plan['number']}", "--draft", "--body-file", str(body)],
        text=True).strip()
    pr = gh_json("pr", "view", url, "--json", "url,headRefOid,isDraft")
    if pr != {"url": url, "headRefOid": candidate, "isDraft": True}:
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
    ledger = ActionLedger(ledger_path)
    key = digest(plan)
    prior = ledger.reserve_once("owned_issue", url, key)
    if prior is not None:
        return {"state": "already_dispatched", "reservation": prior}
    output = output.resolve() / key
    output.mkdir(parents=True, exist_ok=False)
    frozen_spec = output / "contract.json"
    frozen_spec.write_bytes(spec.read_bytes())
    if Contract.read(frozen_spec).digest != plan["spec_sha256"]:
        raise ValueError("specification changed during dispatch")
    record(output / "approval.json", grant)
    candidate = generate(repo, output, plan, frozen_spec, model, timeout, key)
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
