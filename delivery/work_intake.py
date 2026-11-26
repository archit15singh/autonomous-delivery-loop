"""Route candidate issues and prepare review findings for the next worker."""
import re

from .github import gh_json


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


def rank_issues(candidates):
    """Order eligible issues using reviewed facts; keep skipped issues visible."""
    if not isinstance(candidates, list):
        raise ValueError("expected a list of issue facts")
    rows = []
    seen = set()
    for item in candidates:
        url = item.get("issue", "") if isinstance(item, dict) else ""
        if not isinstance(url, str) or not re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+/issues/[1-9][0-9]*", url, re.ASCII):
            raise ValueError("each item requires an exact GitHub issue URL")
        if url.lower() in seen:
            raise ValueError("each issue must appear once")
        seen.add(url.lower())
        requested = item.get("maintainer_requested", False)
        impact, fit = item.get("impact"), item.get("repository_fit")
        effort = item.get("effort")
        if (type(requested) is not bool or type(impact) is not int or not 1 <= impact <= 5
                or type(fit) is not int or not 0 <= fit <= 100
                or type(effort) is not int or not 1 <= effort <= 5):
            raise ValueError("rank using impact 1–5, repository fit 0–100, and effort 1–5")
        row = {"issue": url, **intake(item), "maintainer_requested": requested,
               "impact": impact, "repository_fit": fit, "effort": effort}
        rows.append(row)
    eligible = sorted((row for row in rows if row["route"] == "implement"),
                      key=lambda row: (-row["maintainer_requested"], -row["impact"],
                                       -row["repository_fit"], row["effort"], row["issue"]))
    return {"next_issue": eligible[0]["issue"] if eligible else None, "eligible": eligible,
            "waiting_or_skipped": [row for row in rows if row["route"] != "implement"]}

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
