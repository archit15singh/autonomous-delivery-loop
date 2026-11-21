"""Dispatch one approved owned issue through the pilot delivery entry points."""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

from .codex_usage import read_rates, summarize
from .revisions import FULL_REVISION, checkout, git
from .local_codex import check_subagents
from .factory_definition import definition, running_definition
from .run_state import lock, record
from .work_intake import check_issue
from .run_index import run_record
from .upstream_actions import ActionLedger, digest
from .github import OWNER_REPO as REPOSITORY, gh_json
from .verify import Contract


ISSUE = re.compile(rf"https://github\.com/{REPOSITORY}/issues/([1-9][0-9]*)")
LABEL = "adl-candidate"


def issue_plan(url, spec_path, subagents=0):
    check_subagents(subagents)
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
    plan = {"issue": url, "number": int(number), "base": base,
            "snapshot_sha256": digest(snapshot), "spec_sha256": contract.digest}
    if subagents:
        plan["subagents"] = subagents
    return plan


def approve(url, spec, subagents=0):
    plan = issue_plan(url, spec, subagents)
    if not gh_json("api", f"repos/{REPOSITORY}")["permissions"]["push"]:
        raise ValueError("approval requires an authorized operator")
    return {"plan": plan, "operator": gh_json("api", "user")["login"],
            "approved_at": datetime.now(timezone.utc).isoformat()}


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
            subagents = plan.get("subagents", 0)
            delegation = ("--subagents", subagents) if subagents else ()
            delivery(workspace, "propose", "--contract", spec, "--output", patch,
                     "--events", paths / "codex.jsonl", "--recipe-output", paths / "recipe.json",
                     "--model", model, "--timeout", timeout, *delegation)
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


def index_publication(repo, output, result, index):
    spec = output / "run-spec.json"
    run_id = f"owned-issue-{result['approval'][:24]}"
    if spec.is_file():
        saved = json.loads(spec.read_text())
        # The index is immutable. Replaying a legacy indexed run must retain
        # its original metrics, and new runs retain the original pricing inputs.
        if "codex_usage" in saved or (index / f"{run_id}.json").is_file():
            return run_record(spec, index)

    trace = output / "codex.jsonl"
    # Operators can supply these alongside the parent log before indexing.
    children = sorted((output / "codex-children").glob("*.jsonl"))
    rates_path = output / "codex-rates.json"
    try:
        rates = read_rates(rates_path) if rates_path.exists() else None
    except (OSError, ValueError):
        rates = None
        invalid_rates = True
    else:
        invalid_rates = False
    recipe = output / "recipe.json"
    delegation = recipe.is_file() and json.loads(recipe.read_text()).get("subagents", 0) > 0
    usage = summarize([trace, *children], rates, require_parent_capture=delegation)
    if invalid_rates:
        usage["pricing_signal"] = "invalid_rates_file"

    metrics = {"wall_seconds": result["wall_seconds"], "human_interventions": result["human_approvals"]}
    if usage["complete"]:
        metrics["tokens"] = usage["totals"]["tokens"]
    record(output / "definition.json", definition(repo, result["base"]))
    request = {"id": run_id, "head": result["head"], "base": result["base"],
               "pr": result["pr"], "factory_revision": result["base"],
               "finished_at": result["finished_at"], "metrics": metrics,
               "codex_usage": usage,
               "receipts": {"runtime": "candidate.json", "recipe": "recipe.json",
                            "definition": "definition.json"},
               "patch": "candidate.patch"}
    if trace.is_file():
        request["trace"] = trace.name
    record(spec, request)
    return run_record(spec, index)


@dataclass(frozen=True)
class IssueAttempt:
    """Work authorized under the issue lock, including its immutable receipt location."""
    number: int
    output: Path
    candidate: str | None = None


def attempt_dir(root, key, attempt):
    folder = root / key
    return folder if attempt == 1 else folder / f"attempt-{attempt}"


def record_publication(repo, output, result, index):
    record(output / "publication.json", result)
    if index is not None:
        index_publication(repo, output, result, index)


def resume_attempt(repo, root, plan, key, prior, retry_generation, index):
    """Return a verified attempt or terminal reply. None allows a new generation."""
    if prior is None:
        if retry_generation is not None:
            raise ValueError("no interrupted generation matches this retry")
        return None

    attempt = prior["attempt"] or 1
    previous = attempt_dir(root, prior["identity"], attempt)
    if prior["result"]:
        result = prior["result"]
        if key == prior["identity"] and result["state"] == "published":
            record_publication(repo, previous, result, index)
        return {"state": "already_dispatched", "reservation": prior}

    candidate = prior["candidate"]
    legacy = prior["attempt"] is None
    checkpoint = previous / "verified-head.json"
    if legacy and checkpoint.exists():
        candidate = json.loads(checkpoint.read_text())["candidate"]
        if not FULL_REVISION.fullmatch(candidate):
            raise ValueError("invalid legacy verified candidate")
    if candidate:
        if prior["identity"] != key:
            return {"state": "reconciliation_required", "reason": "verified_plan_changed",
                    "candidate": candidate}
        return IssueAttempt(attempt, previous, candidate)
    if retry_generation != attempt:
        return {"state": "generation_interrupted", "attempt": attempt,
                "plan": prior["identity"], "receipts": str(previous)}

    # Old reservations did not bind a receipt path or record publication intent.
    if legacy:
        frozen = previous / "approval.json"
        if not frozen.exists() or digest(json.loads(frozen.read_text())["plan"]) != prior["identity"]:
            return {"state": "reconciliation_required", "reason": "legacy_approval_missing"}
        remote = f"git@github.com:{REPOSITORY}.git"
        if git("ls-remote", remote, f"refs/heads/factory/issue-{plan['number']}", cwd=repo).strip():
            return {"state": "reconciliation_required", "reason": "existing_issue_branch"}
    return None


@contextmanager
def locked_attempt(repo, ledger, root, plan, key, retry_generation, index):
    """Keep the issue and legacy receipt locks through generation and publication."""
    url = plan["issue"]
    with lock(ledger.path.resolve().parent / (ledger.path.name + ".issue-locks") / digest(url)):
        prior = ledger.issue_attempt(url)
        if prior and prior["receipts"] and prior["receipts"] != str(root):
            raise ValueError(f"use the original receipts directory: {prior['receipts']}")
        old_dir = root / (prior["identity"] if prior else key)
        if prior and prior["attempt"] is None and not prior["result"] and not (old_dir / "workflow.lock").is_file():
            yield {"state": "reconciliation_required", "reason": "original_receipts_missing"}
            return
        # Older dispatchers used this lock before creating the ledger-backed attempt.
        with lock(old_dir):
            decision = resume_attempt(repo, root, plan, key, prior, retry_generation, index)
            if decision is None:
                number = ledger.begin_issue_attempt(url, key, root, prior)
                output = attempt_dir(root, key, number)
                output.mkdir(parents=True, exist_ok=(number == 1))
                decision = IssueAttempt(number, output)
            yield decision


def run_issue(repo, url, spec, approval, ledger_path, output, model, timeout, index=None, *,
              retry_generation=None, subagents=0):
    started = time.monotonic()
    plan = issue_plan(url, spec, subagents)
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
    with locked_attempt(repo, ledger, output.resolve(), plan, key, retry_generation, index) as attempt:
        if not isinstance(attempt, IssueAttempt):
            return attempt
        output = attempt.output
        candidate = attempt.candidate
        if candidate is None:
            frozen_spec = output / "contract.json"
            frozen_spec.write_bytes(spec.read_bytes())
            if Contract.read(frozen_spec).digest != plan["spec_sha256"]:
                raise ValueError("specification changed during dispatch")
            record(output / "approval.json", grant)
            candidate = generate(repo, output, plan, frozen_spec, model, timeout, key)
            ledger.verify_issue_attempt(url, attempt.number, candidate)
        record(output / "verified-head.json", {"candidate": candidate})
        if issue_plan(url, spec, subagents) != plan:
            return {"state": "stale_before_publication", "candidate": candidate}
        pr = publish(repo, output, plan, candidate)
        result = {"state": "published", "issue": url, "pr": pr, "head": candidate,
                  "base": plan["base"], "approval": key, "generation_attempt": attempt.number,
                  "wall_seconds": round(time.monotonic() - started, 3),
                  "human_approvals": 1, "finished_at": datetime.now(timezone.utc).isoformat()}
        ledger.finish_once("owned_issue", url, key, result)
        record_publication(repo, output, result, index)
        return result
