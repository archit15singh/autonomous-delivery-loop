"""Compare observed upstream merge paths with the current gates on tracked PRs."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import re
import statistics
from urllib.parse import quote

from .github import LOOKUP_ERRORS, PR_URL, gh_json
from .upstream_ci import REPO_AFFILIATION, review_participant


MERGE_QUERY = """
query($search: String!, $limit: Int!) {
  search(query: $search, type: ISSUE, first: $limit) {
    issueCount
    pageInfo { hasNextPage }
    nodes {
      ... on PullRequest {
        url title state createdAt mergedAt headRefOid isCrossRepository authorAssociation
        author { login __typename }
        mergedBy { login __typename }
        mergeCommit { oid }
        closingIssuesReferences(first: 20) { nodes { url } pageInfo { hasNextPage } }
        reviews(last: 30) {
          nodes { state submittedAt url authorAssociation commit { oid } author { login __typename } }
          pageInfo { hasPreviousPage }
        }
        timelineItems(first: 20, itemTypes: [
          READY_FOR_REVIEW_EVENT, REVIEW_REQUESTED_EVENT, AUTO_MERGE_ENABLED_EVENT,
          ADDED_TO_MERGE_QUEUE_EVENT
        ]) {
          nodes {
            __typename
            ... on ReadyForReviewEvent { createdAt actor { login } }
            ... on ReviewRequestedEvent { createdAt actor { login } }
            ... on AutoMergeEnabledEvent { createdAt actor { login } }
            ... on AddedToMergeQueueEvent { createdAt actor { login } }
          }
          pageInfo { hasNextPage }
        }
      }
    }
  }
}
"""
ISSUE_URL = re.compile(r"https://github\.com/([\w.-]+)/([\w.-]+)/issues/([1-9][0-9]*)", re.ASCII)


def merge_example(pr):
    author = pr["author"] or {}
    reviewed = []
    for review in pr["reviews"]["nodes"]:
        if not review["submittedAt"] or review["submittedAt"] > pr["mergedAt"]:
            continue
        reviewed.append({
            "state": review["state"], "at": review["submittedAt"], "url": review["url"],
            "participant": review_participant(review, author.get("login")),
            "association": review["authorAssociation"], "head": (review["commit"] or {}).get("oid"),
        })
    if review_participant(pr, None) == "bot":
        source = "bot"
    elif not author.get("login"):
        source = "unknown"
    elif pr["isCrossRepository"]:
        source = "affiliated_fork" if pr["authorAssociation"] in REPO_AFFILIATION else "external_fork"
    else:
        source = "same_repository"
    elapsed = datetime.fromisoformat(pr["mergedAt"]) - datetime.fromisoformat(pr["createdAt"])
    return {
        "url": pr["url"], "title": pr["title"], "source": source,
        "author": author.get("login"), "author_association": pr["authorAssociation"],
        "opened_at": pr["createdAt"], "merged_at": pr["mergedAt"],
        "days_to_merge": round(elapsed.total_seconds() / 86400, 3),
        "merged_by": pr["mergedBy"], "merge_commit": (pr["mergeCommit"] or {}).get("oid"),
        "head": pr["headRefOid"], "reviews_before_merge": reviewed,
        "reviews_truncated": pr["reviews"]["pageInfo"]["hasPreviousPage"],
        "events_before_merge": [
            {"type": event["__typename"], "at": event["createdAt"], "actor": event["actor"]}
            for event in pr["timelineItems"]["nodes"]
            if event["createdAt"] <= pr["mergedAt"]
        ],
        "events_truncated": pr["timelineItems"]["pageInfo"]["hasNextPage"],
        "linked_issues": [issue["url"] for issue in pr["closingIssuesReferences"]["nodes"]],
        "linked_issues_truncated": pr["closingIssuesReferences"]["pageInfo"]["hasNextPage"],
    }


def observed_path(examples):
    forks = [example for example in examples if example["source"] == "external_fork"]
    approved = [
        example for example in forks
        if any(review["participant"] == "human" and review["state"] == "APPROVED"
               for review in example["reviews_before_merge"])
    ]
    return {
        "external_forks": len(forks),
        "with_observed_human_approval": len(approved),
        "with_truncated_review_history": sum(example["reviews_truncated"] for example in forks),
        "median_days_to_merge": statistics.median(e["days_to_merge"] for e in forks) if forks else None,
    }


def inspect_branch(repo, branch, since, limit, own_urls):
    search = f"repo:{repo} base:{json.dumps(branch)} is:pr is:merged merged:>={since} sort:updated-desc"
    response = gh_json("api", "graphql", "-f", f"query={MERGE_QUERY}",
                       "-f", f"search={search}", "-F", f"limit={limit}")
    data = response["data"]["search"]
    examples = [merge_example(pr) for pr in data["nodes"]
                if pr and pr.get("state") == "MERGED" and pr["url"].lower() not in own_urls]
    endpoint = f"repos/{repo}/rules/branches/{quote(branch, safe='')}?per_page=100"
    rules = {"source": f"https://api.github.com/{endpoint}"}
    try:
        pages = gh_json("api", "--paginate", "--slurp", endpoint)
        active_rules = [rule for page in pages for rule in page]
        review_rules = [rule["parameters"] for rule in active_rules if rule["type"] == "pull_request"]
        check_rules = [rule["parameters"] for rule in active_rules if rule["type"] == "required_status_checks"]
        methods = [set(rule["allowed_merge_methods"]) for rule in review_rules
                   if "allowed_merge_methods" in rule]
        rules.update(
            strict_status_checks=any(rule["strict_required_status_checks_policy"] for rule in check_rules),
            required_checks=sorted({check["context"] for rule in check_rules
                                    for check in rule["required_status_checks"]}),
            required_approvals=max((rule["required_approving_review_count"]
                                    for rule in review_rules), default=0),
            require_code_owner_review=any(rule["require_code_owner_review"] for rule in review_rules),
            require_thread_resolution=any(rule["required_review_thread_resolution"] for rule in review_rules),
            allowed_merge_methods=sorted(set.intersection(*methods)) if methods else None,
            merge_queue=any(rule["type"] == "merge_queue" for rule in active_rules),
        )
    except LOOKUP_ERRORS as exc:
        rules["error"] = str(exc)
    return {
        "repo": repo, "branch": branch, "search": search,
        "matching_merged_count": data["issueCount"], "sample_truncated": data["pageInfo"]["hasNextPage"],
        "sample": examples, "external_path": observed_path(examples), "active_rulesets": rules,
    }


def inspect_issue_merges(issues):
    """Read issue-specific closing PRs even when the merge fell outside the sample."""
    result = {}
    for start in range(0, len(issues), 20):
        batch = issues[start:start + 20]
        fields = []
        for index, url in enumerate(batch):
            match = ISSUE_URL.fullmatch(url)
            if not match:
                raise ValueError(f"expected a GitHub issue URL, got {url!r}")
            owner, name, number = match.groups()
            fields.append(f"""i{index}: repository(owner: "{owner}", name: "{name}") {{
              issue(number: {number}) {{
                closedByPullRequestsReferences(first: 50, includeClosedPrs: true) {{
                  nodes {{ url state mergeCommit {{ oid }} }}
                  pageInfo {{ hasNextPage }}
                }}
              }}
            }}""")
        response = gh_json("api", "graphql", "-f", "query={ " + "\n".join(fields) + " }")
        for index, url in enumerate(batch):
            refs = response["data"][f"i{index}"]["issue"]["closedByPullRequestsReferences"]
            result[url] = {
                "truncated": refs["pageInfo"]["hasNextPage"],
                "merged": [{"url": pr["url"], "merge_commit": (pr["mergeCommit"] or {}).get("oid")}
                           for pr in refs["nodes"] if pr["state"] == "MERGED"],
            }
    return result


def advise(record, cohort):
    review = record.get("review", {})
    ci_action = record["action"]
    review_action = review.get("action")
    rules = cohort.get("active_rulesets", {})
    actions = []
    if record.get("state") == "OPEN":
        if review_action == "check_branch_update" and rules.get("strict_status_checks"):
            actions.append("update_branch_and_reverify")
        elif review_action and review_action != ci_action:
            actions.append(review_action)
        if ci_action != "checks_passed":
            actions.append(ci_action)
    elif ci_action == "lookup_failed":
        actions.append(ci_action)

    overlaps = [
        {**match, "issue": issue}
        for issue in record.get("linked_issues", [])
        for match in cohort.get("linked_issue_results", {}).get(issue, {}).get("merged", [])
        if match["url"].lower() != record["url"].lower()
    ] if record.get("state") == "OPEN" else []
    if overlaps:
        actions.insert(0, "verify_possible_upstream_resolution")
    return {"url": record["url"], "head": record.get("head"), "state": record.get("state"),
            "ci_action": ci_action, "review_action": review_action, "actions": actions,
            "possible_alternative_merges": overlaps}


def merge_precedents(records, *, days, limit):
    groups = {}
    own_urls = set()
    missing = []
    if not isinstance(records, list) or not records:
        raise ValueError("provide a nonempty upstream-ci --review receipt")
    for record in records:
        match = PR_URL.fullmatch(record["url"])
        if not match:
            raise ValueError(f"expected a GitHub pull request URL, got {record['url']!r}")
        own_urls.add(record["url"].lower())
        if not record.get("base_branch"):
            if record["action"] != "lookup_failed":
                raise ValueError("receipt has no base branch; rerun upstream-ci --review")
            missing.append(advise(record, {}))
            continue
        groups.setdefault((match[1].lower(), record["base_branch"]), []).append(record)
    now = datetime.now(timezone.utc)
    since = (now.date() - timedelta(days=days)).isoformat()

    def inspect(item):
        (repo, branch), prs = item
        try:
            cohort = inspect_branch(repo, branch, since, limit, own_urls)
        except LOOKUP_ERRORS as exc:
            cohort = {"repo": repo, "branch": branch, "error": str(exc)}
        issues = sorted({issue for pr in prs if pr.get("state") == "OPEN"
                         for issue in pr.get("linked_issues", [])})
        try:
            cohort["linked_issue_results"] = inspect_issue_merges(issues)
        except LOOKUP_ERRORS as exc:
            cohort["linked_issue_error"] = str(exc)
        return {**cohort, "tracked_prs": [advise(pr, cohort) for pr in prs]}

    with ThreadPoolExecutor(max_workers=3) as workers:
        branches = list(workers.map(inspect, sorted(groups.items())))
    return {"collected_at": now.isoformat(), "since": since, "limit_per_branch": limit,
            "branches": branches, "missing_prs": missing}
