"""Freeze an independent GitHub review and the exact Git diff it labels."""
from contextlib import closing
import sqlite3
import json
from pathlib import Path
import re

from .github import PR_URL, gh_json
from .review_artifact import publish_new
from .revisions import FULL_REVISION, git
from .upstream_ci import REPO_AFFILIATION, review_participant


VERDICTS = {"APPROVED": "ship", "CHANGES_REQUESTED": "changes"}
SPLITS = {"development", "holdout"}
AUTOMATED_HEADER = re.compile(
    r"^[\s#>*_🤖\ufe0f-]*(?:automated|bot-generated|ai-generated|machine-generated)"
    r"\s+(?:code\s+)?review\b|^PR Desk \([^)]*\bbot\):", re.IGNORECASE,
)
GITHUB_REMOTE = re.compile(r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([\w.-]+/[\w.-]+?)(?:\.git)?/?$", re.I)


def _subject(url):
    match = PR_URL.fullmatch(url)
    if not match or len(match[1].split("/")) != 2:
        raise ValueError("expected a GitHub pull request URL")
    return match[1], match[2]


def check_remote(repo, repository):
    for remote in git("remote", cwd=repo).decode().splitlines():
        url = git("remote", "get-url", "--", remote, cwd=repo).decode().strip()
        match = GITHUB_REMOTE.fullmatch(url)
        if match and match[1].casefold() == repository.casefold():
            return
    raise ValueError("the local checkout needs a GitHub remote for the reviewed repository")


def _eligible(review, author):
    user = review.get("user") or {}
    return (user.get("type") == "User" and review.get("author_association") in REPO_AFFILIATION
            and review_participant({"author": {"login": user.get("login")}}, author) == "human"
            and user["login"].casefold() != author.casefold())


def _validate(case):
    repo, number = _subject(case["pr"])
    if (case["version"] != 1 or case["split"] not in SPLITS or case["expected"] not in VERDICTS.values()
            or not all(FULL_REVISION.fullmatch(case[k]) for k in ("base", "head", "target_base"))
            or case["can_push"] is not True or case["base"] == case["head"] or case["association"] not in REPO_AFFILIATION
            or not case["author"] or not case["reviewer"] or case["author"].casefold() == case["reviewer"].casefold()
            or type(case["review_id"]) is not int or case["review_id"] <= 0
            or case["evidence"] != f"{case['pr']}#pullrequestreview-{case['review_id']}"
            or not isinstance(case["rationale"], str) or not case["submitted_at"]
            or not isinstance(case["finding_paths"], list)
            or not all(isinstance(p, str) and p.strip() for p in case["finding_paths"])
            or sorted(set(case["finding_paths"])) != case["finding_paths"]
            or (case["expected"] == "ship" and case["finding_paths"])):
        raise ValueError("invalid frozen review case")
    return repo, number


def load_cases(directory):
    cases = []
    heads = set()
    repos = set()
    for path in sorted(Path(directory).glob("pr-*.json")):
        case = json.loads(path.read_text())
        repo, number = _validate(case)
        repos.add(repo.casefold())
        if path.name != f"pr-{number}.json" or case["head"] in heads or len(repos) > 1:
            raise ValueError("each cohort requires one repository and unique PRs and heads")
        heads.add(case["head"])
        cases.append(case)
    return cases


def harvest(repo, pr_url, review_id, split, directory):
    repository, number = _subject(pr_url)
    if split not in SPLITS or not re.fullmatch(r"[1-9][0-9]*", str(review_id)):
        raise ValueError("a review ID and development or holdout split are required")
    check_remote(repo, repository)
    route = f"repos/{repository}/pulls/{number}"
    pr = gh_json("api", route)
    author = pr["user"]["login"]
    tip, target = pr["head"]["sha"], pr["base"]["sha"]
    pages = gh_json("api", "--paginate", "--slurp", f"{route}/reviews?per_page=100")
    selected = next((r for page in pages for r in page if r["id"] == int(review_id)), None)
    if not selected:
        raise ValueError("review does not belong to the selected PR")
    head = selected.get("commit_id") or ""
    if not all(FULL_REVISION.fullmatch(sha) for sha in (head, target, tip)):
        raise ValueError("GitHub must identify the reviewed revisions")
    # Older reviews remain valid after repairs on this branch; the current tip
    # must still descend from the reviewed commit. Force-pushed evidence is ambiguous.
    if git("merge-base", tip, head, cwd=repo).decode().strip() != head:
        raise ValueError("reviewed commit is outside the current PR history")
    bases = git("merge-base", "--all", target, head, cwd=repo).decode().splitlines()
    if len(bases) != 1 or bases[0] == head:
        raise ValueError("cannot recover a unique nonempty reviewed diff")
    latest = {}
    for page in pages:
        for review in page:
            if (review.get("commit_id") == head and _eligible(review, author)
                    and review["state"] in (*VERDICTS, "DISMISSED")):
                login = review["user"]["login"].casefold()
                if login not in latest or latest[login]["id"] < review["id"]:
                    latest[login] = review
    effective = [r for r in latest.values() if r["state"] in VERDICTS
                 and not AUTOMATED_HEADER.match(r.get("body") or "")]
    chosen = next((r for r in effective if r["id"] == int(review_id)), None)
    if not chosen or any(r["state"] != chosen["state"] for r in effective):
        raise ValueError("review must be an independent, current, unambiguous decision on this exact head")
    node = gh_json("api", "graphql", "-f",
                   "query=query($id:ID!){node(id:$id){... on PullRequestReview{authorCanPushToRepository}}}",
                   "-f", f"id={chosen['node_id']}")["data"]["node"]
    if not node or node["authorCanPushToRepository"] is not True:
        raise ValueError("reviewer must have push access to the reviewed repository")
    # Retargeting can change the diff even with the same head. Reject evidence
    # predating a base-branch switch.
    events = gh_json("api", "--paginate", "--slurp", f"repos/{repository}/issues/{number}/timeline?per_page=100")
    if any(e.get("event") == "base_ref_changed" and e["created_at"] >= chosen["submitted_at"]
           for page in events for e in page):
        raise ValueError("PR was retargeted after the selected review")
    inline = []
    if chosen["state"] == "CHANGES_REQUESTED":
        comments = gh_json("api", "--paginate", "--slurp",
                           f"{route}/reviews/{chosen['id']}/comments?per_page=100")
        inline = [c for page in comments for c in page if not c.get("in_reply_to_id") and c.get("path")
                  and ((c.get("user") or {}).get("login") or "").casefold() == chosen["user"]["login"].casefold()]
    rationale = (chosen.get("body") or "").strip() or "\n".join(
        f"{c['path']}: {c['body']}" for c in inline if c.get("body"))
    current = gh_json("api", route)
    if any(current[k]["sha"] != pr[k]["sha"] for k in ("head", "base")) or current["base"]["ref"] != pr["base"]["ref"]:
        raise ValueError("PR revisions moved during harvest")
    case = {"version": 1, "pr": pr["html_url"], "base": bases[0], "target_base": target, "head": head,
            "expected": VERDICTS[chosen["state"]], "split": split, "rationale": rationale[:8000],
            "finding_paths": sorted({c["path"] for c in inline}),
            "reviewer": chosen["user"]["login"], "association": chosen["author_association"], "author": author,
            "can_push": True, "submitted_at": chosen["submitted_at"], "review_id": chosen["id"], "evidence": chosen["html_url"]}
    _validate(case)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # Serialize cross-PR identity checks as well as immutable publication.
    with closing(sqlite3.connect(directory / ".harvest.sqlite3")) as lock:
        lock.execute("BEGIN IMMEDIATE")
        for existing in load_cases(directory):
            if existing == case:
                return existing
            if (_subject(existing["pr"])[0].casefold() != repository.casefold() or existing["pr"] == case["pr"]
                    or existing["head"] == head):
                raise ValueError("cohort repository, split and recorded subjects are immutable")
        publish_new(directory / f"pr-{number}.json", json.dumps(case, indent=2) + "\n")
    return case
