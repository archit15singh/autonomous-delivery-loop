"""Read current upstream CI and identify the next action for each pull request."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
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


REVIEW_QUERY = """
query($owner: String!, $repo: String!, $number: Int!, $endCursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      headRefOid
      author { login }
      latestReviews(first: 100) {
        nodes {
          state url authorAssociation
          commit { oid }
          author { login __typename }
        }
        pageInfo { hasNextPage }
      }
      comments(last: 30) {
        nodes { url isMinimized authorAssociation author { login __typename } }
      }
      reviewThreads(first: 100, after: $endCursor) {
        nodes {
          isResolved isOutdated
          comments(first: 1) {
            nodes { url authorAssociation author { login __typename } }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""

REPO_AFFILIATION = {"OWNER", "MEMBER", "COLLABORATOR"}
# The OpenHands automation uses a GitHub User account for SDK reviews.
SERVICE_REVIEWERS = {"all-hands-bot"}


def review_participant(item, pr_author):
    author = item.get("author") or {}
    login = author.get("login")
    if not login:
        return "unknown"
    if (author.get("__typename") == "Bot" or login.lower().endswith("[bot]")
        or login.lower() in SERVICE_REVIEWERS):
        return "bot"
    return "author" if login == pr_author else "human"


def review_action(record, pr, unresolved):
    decision, merge_state = pr["reviewDecision"], pr["mergeStateStatus"]
    if record["draft"]:
        return "complete_draft_requirements"
    if decision == "CHANGES_REQUESTED" or any(
        t["participant"] == "human" and not t["outdated"] for t in unresolved
    ):
        return "inspect_review_feedback"
    if pr["mergeable"] == "CONFLICTING" or merge_state == "DIRTY":
        return "resolve_conflicts"
    if merge_state == "BEHIND":
        return "check_branch_update"
    if record["action"] != "checks_passed":
        return record["action"]
    if decision == "REVIEW_REQUIRED":
        return "await_maintainer_review"
    if merge_state == "CLEAN" and pr["mergeable"] == "MERGEABLE":
        return "await_maintainer_merge"
    return "inspect_merge_gate"


def inspect_reviews(repo, number, pr, record):
    owner, name = repo.split("/")
    pages = gh_json("api", "graphql", "--paginate", "--slurp",
                    "-f", f"query={REVIEW_QUERY}", "-f", f"owner={owner}",
                    "-f", f"repo={name}", "-F", f"number={number}")
    snapshots = [page["data"]["repository"]["pullRequest"] for page in pages]
    if not snapshots or any(page["headRefOid"] != record["head"] for page in snapshots):
        raise ValueError("PR head changed during review lookup; scan again")
    first = snapshots[0]
    pr_author = (first["author"] or {}).get("login")
    if first["latestReviews"]["pageInfo"]["hasNextPage"]:
        raise ValueError("too many reviewers for a complete review snapshot")
    reviews = [
        {"url": item["url"], "state": item["state"],
         "login": (item.get("author") or {}).get("login"),
         "participant": review_participant(item, pr_author),
         "association": item["authorAssociation"],
         "head": (item["commit"] or {}).get("oid")}
        for item in first["latestReviews"]["nodes"]
        if item["state"] != "PENDING"
    ]
    threads = []
    for snapshot in snapshots:
        for thread in snapshot["reviewThreads"]["nodes"]:
            if thread["isResolved"]:
                continue
            nodes = thread["comments"]["nodes"]
            comment = nodes[0] if nodes else {}
            threads.append({"url": comment.get("url"), "outdated": thread["isOutdated"],
                            "participant": review_participant(comment, pr_author),
                            "association": comment.get("authorAssociation")})
    discussion = [
        {"url": item["url"], "login": item["author"]["login"],
         "association": item["authorAssociation"]}
        for item in first["comments"]["nodes"]
        if (not item["isMinimized"] and item["authorAssociation"] in REPO_AFFILIATION
            and review_participant(item, pr_author) == "human")
    ]
    return {"decision": pr["reviewDecision"], "merge_state": pr["mergeStateStatus"],
            "mergeable": pr["mergeable"], "reviews": reviews, "unresolved_threads": threads,
            "recent_affiliated_comments": discussion,
            "action": review_action(record, pr, threads)}


def inspect_pr(url, repo, number, *, review=False):
    fields = "headRefOid,headRefName,headRepository,baseRefOid,state,isDraft,statusCheckRollup"
    if review:
        fields += ",reviewDecision,mergeStateStatus,mergeable,mergedAt,baseRefName,closingIssuesReferences"
        fields += ",mergedBy,mergeCommit"
    pr = gh_json("pr", "view", str(number), "--repo", repo, "--json", fields)
    record = {"url": url, "head": pr["headRefOid"], "base": pr["baseRefOid"],
              "state": pr["state"], "draft": pr["isDraft"]}
    if review:
        record.update(base_branch=pr["baseRefName"], linked_issues=[
            issue["url"] for issue in pr["closingIssuesReferences"]
        ])
    if pr["state"] != "OPEN":
        if review:
            record["merged_at"] = pr["mergedAt"]
            if pr["state"] == "MERGED":
                record.update(merged_by=(pr["mergedBy"] or {}).get("login"),
                              merge_commit=(pr["mergeCommit"] or {}).get("oid"))
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
    record.update(action=next_action(signals), signals=signals)
    if review:
        try:
            record["review"] = inspect_reviews(repo, number, pr, record)
        except (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError) as exc:
            record["review"] = {"action": "lookup_failed", "error": str(exc)}
    return record


def inspect_prs(urls, *, review=False):
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
            return inspect_pr(*target, review=review)
        except (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError) as exc:
            return {"url": target[0], "action": "lookup_failed", "error": str(exc)}

    with ThreadPoolExecutor(max_workers=6) as workers:
        return list(workers.map(inspect, targets))


def attach_local_replay(records, runs):
    """Compare GitHub's current revisions with operator-owned indexed replays."""
    indexed = defaultdict(list)
    for run in runs:
        if run["pr"] and "readiness" in run["outcome"]:
            indexed[run["pr"].lower()].append(run)

    for record in records:
        if record.get("state") != "OPEN":
            continue
        attempts = indexed[record["url"].lower()]
        same_head = [run for run in attempts if run["head"] == record["head"]]
        exact = [run for run in same_head if run.get("base") == record["base"]]
        latest = max(exact or same_head or attempts, key=lambda run: datetime.fromisoformat(
            run["finished_at"]), default=None)
        evidence = {"status": "unindexed"}
        if latest:
            if exact:
                verified = (latest["outcome"]["readiness"] == "verified"
                            and latest["outcome"].get("browser") != "failed")
                status = "verified" if verified else "unverified"
            else:
                status = "baseline_needs_replay" if same_head else "head_needs_replay"
            evidence = {"status": status, "run_id": latest["id"], "head": latest["head"],
                        "base": latest.get("base"), "finished_at": latest["finished_at"]}
        record["local_replay"] = evidence
