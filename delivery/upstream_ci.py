"""Read current upstream CI and identify the next action for each pull request."""
from concurrent.futures import ThreadPoolExecutor
import json
import re
import subprocess


PR_URL = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/([1-9][0-9]*)", re.ASCII)
PASS = {"success", "neutral", "skipped"}
APPROVAL = {"action_required", "waiting"}
FAILED = {"failure", "timed_out", "startup_failure"}
PENDING = {"queued", "in_progress", "pending", "requested", "expected", "waiting_for_status"}


def gh_json(*args):
    return json.loads(subprocess.check_output(
        ["gh", *args], text=True, stdin=subprocess.DEVNULL, timeout=30,
    ))


def signal(name, state, url):
    return {"name": name, "state": (state or "unknown").lower(), "url": url}


def collect_runs(pages, pr, number):
    latest = {}
    for page in pages:
        for run in page["workflow_runs"]:
            if (run["head_sha"] != pr["headRefOid"]
                or run["head_branch"] != pr["headRefName"]
                or (run.get("head_repository") or {}).get("full_name") !=
                    (pr.get("headRepository") or {}).get("nameWithOwner")):
                continue
            linked = run.get("pull_requests", [])
            if linked and not any(item["number"] == number for item in linked):
                continue
            key = run["workflow_id"]
            if key not in latest or run["run_number"] > latest[key]["run_number"]:
                latest[key] = run
    return [
        signal(run["name"], run["conclusion"] or run["status"], run["html_url"])
        for run in latest.values()
    ]


def next_action(signals):
    states = {item["state"] for item in signals}
    # A failure can be investigated while separate workflows await approval.
    if states & FAILED:
        return "investigate_failure"
    if states & APPROVAL:
        return "await_approval"
    if states & PENDING:
        return "wait_for_ci"
    if states and states <= PASS and "success" in states:
        return "checks_passed"
    return "inspect_missing_evidence"


def inspect_pr(url, repo, number):
    pr = gh_json("pr", "view", str(number), "--repo", repo, "--json",
                 "headRefOid,headRefName,headRepository,baseRefOid,state,isDraft,statusCheckRollup")
    record = {"url": url, "head": pr["headRefOid"], "base": pr["baseRefOid"],
              "state": pr["state"], "draft": pr["isDraft"]}
    if pr["state"] != "OPEN":
        return {**record, "action": "closed", "signals": []}
    if not re.fullmatch(r"[a-f0-9]{40}", record["head"]):
        raise ValueError("GitHub did not return a full PR head")
    rollup = [
        signal(item.get("name") or item["context"],
               item.get("conclusion") or item.get("state") or item.get("status"),
               item.get("detailsUrl") or item.get("targetUrl"))
        for item in pr["statusCheckRollup"]
    ]
    # Actions awaiting first-contributor approval may never appear in the check rollup.
    pages = gh_json("api", "--paginate", "--slurp",
                    f"repos/{repo}/actions/runs?head_sha={record['head']}&event=pull_request&per_page=100")
    signals = rollup + collect_runs(pages, pr, number)
    return {**record, "action": next_action(signals), "signals": signals}


def inspect_prs(urls):
    targets = []
    for url in dict.fromkeys(urls):
        match = PR_URL.fullmatch(url)
        if not match:
            raise ValueError(f"expected a GitHub pull request URL, got {url!r}")
        repo, number = match.groups()
        targets.append((url, repo, int(number)))
    if not targets:
        raise ValueError("provide at least one GitHub pull request URL")

    def inspect(target):
        try:
            return inspect_pr(*target)
        except (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError) as exc:
            return {"url": target[0], "action": "lookup_failed", "error": str(exc)}

    with ThreadPoolExecutor(max_workers=6) as workers:
        return list(workers.map(inspect, targets))
