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
