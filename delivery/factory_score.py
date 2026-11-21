"""Score current delivery outcomes from operator-owned replays and GitHub observations."""
from hashlib import sha256
import json
import re
from collections import Counter
from pathlib import Path

from .github import PR_URL
from .revisions import FULL_REVISION
from .upstream_ci import REPO_AFFILIATION, next_action

# A merge settles the work at full value. Intermediate credit is provisional.
WEIGHTS = {"reproduced": 10, "verified_fix": 20, "verified_submission": 5, "green_ci": 10,
           "approved": 15, "merged": 100}
ISSUE_URL = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/issues/[1-9][0-9]*", re.ASCII)
WORK = {"inspect_review_feedback", "resolve_conflicts", "check_branch_update",
        "investigate_failure", "inspect_missing_evidence"}


def passed_log(directory, check):
    name = check["log"]
    if Path(name).name != name:
        raise ValueError("expected a replay log filename")
    data = (directory / name).read_bytes()
    if sha256(data).hexdigest() != check["log_sha256"]:
        raise ValueError(f"replay log changed: {name}")
    return (check["passed"] is True and check["exit"] == check["expected_exit"]
            and bool(check["signal"]) and check["signal"].encode() in data)


def candidate_row(issue, path):
    if not ISSUE_URL.fullmatch(issue):
        raise ValueError("candidate needs a GitHub issue URL")
    receipt = json.loads(Path(path).read_text())
    if not all(FULL_REVISION.fullmatch(receipt[k]) for k in ("base", "candidate")):
        raise ValueError("candidate receipt needs exact revisions")
    before = receipt["before"]
    directory = Path(path).parent
    reproduced = passed_log(directory, before) and before["exit"] > 0
    verified = False
    if reproduced and receipt["verdict"] == "verified":
        readiness = receipt["readiness"]
        controls = readiness["controls"]
        checks = [receipt["after"], readiness["suite"]]
        for phase in ("baseline", "candidate"):
            if not controls[phase]:
                raise ValueError("verified replay is missing controls")
            checks.extend([readiness["setup"][phase], *controls[phase]])
        verified = all(passed_log(directory, c) and c["exit"] == 0 for c in checks)
    earned = {}
    if reproduced:
        earned["reproduced"] = WEIGHTS["reproduced"]
    if verified:
        earned["verified_fix"] = WEIGHTS["verified_fix"]
    return {"subject": issue, "head": receipt["candidate"], "state": "LOCAL",
            "points": earned, "evidence": str(path),
            "next": "check_submission_requirements" if verified else "verify_fix"}


def pr_row(record):
    url, state = record["url"], record.get("state", "UNKNOWN")
    if not PR_URL.fullmatch(url):
        raise ValueError("expected an upstream PR URL")
    head = record.get("head")
    earned = {}
    review = record.get("review", {})
    action = review.get("action", record["action"])
    if state == "MERGED" and record.get("merged_at") and FULL_REVISION.fullmatch(record.get("merge_commit") or ""):
        earned["merged"] = WEIGHTS["merged"]
        action = "complete"
    elif state == "OPEN" and FULL_REVISION.fullmatch(head or ""):
        replay = record.get("local_replay") or {}
        if (replay.get("status") == "verified" and replay.get("head") == head
                and FULL_REVISION.fullmatch(record.get("base") or "") and replay.get("base") == record["base"]):
            earned.update(reproduced=WEIGHTS["reproduced"], verified_fix=WEIGHTS["verified_fix"])
            if record.get("draft") is False:
                earned["verified_submission"] = WEIGHTS["verified_submission"]
        if next_action(record["signals"]) == "checks_passed":
            earned["green_ci"] = WEIGHTS["green_ci"]
        if review.get("decision") == "APPROVED" and any(
            r["state"] == "APPROVED" and r["head"] == head and r["participant"] == "human"
            and r["association"] in REPO_AFFILIATION for r in review.get("reviews", [])
        ):
            earned["approved"] = WEIGHTS["approved"]
    return {"subject": url, "head": head, "state": state, "points": earned, "next": action,
            "evidence": {"replay": (record.get("local_replay") or {}).get("run_id"),
                         "merge": record.get("merge_commit")}}


def score(records, candidates=()):
    rows = {}
    published_heads = set()
    linked = set()

    def include(row):
        key = row["subject"].lower()
        if key in rows and rows[key] != row:
            raise ValueError(f"conflicting snapshots for {key}")
        rows[key] = row

    for record in records:
        include(pr_row(record))
        published_heads.add(record.get("head"))
        linked.update(url.lower() for url in record.get("linked_issues", []))
    local_heads = {}
    for issue, path in candidates:
        row = candidate_row(issue, path)
        if row["head"] not in published_heads and issue.lower() not in linked:
            owner = local_heads.setdefault(row["head"], issue.lower())
            if owner != issue.lower():
                raise ValueError("one candidate revision cannot earn credit for two issue URLs")
            include(row)
    totals = Counter()
    ordered = sorted(rows.values(), key=lambda r: r["subject"])
    for row in ordered:
        row["score"] = sum(row["points"].values())
        totals.update(row["points"])
    points = sum(totals.values())
    work = [row for row in ordered if row["next"] in WORK or row["state"] == "LOCAL"]
    work.sort(key=lambda row: (-row["score"], row["subject"]))
    return {"policy_version": 1, "weights": WEIGHTS, "total": points, "delivered": totals["merged"],
            "provisional": points - totals["merged"], "subjects": len(rows),
            "mean_per_subject": round(points / len(rows), 2) if rows else 0,
            "by_milestone": {k: totals[k] for k in WEIGHTS}, "rows": ordered,
            "work_queue": [{"subject": r["subject"], "next": r["next"], "score": r["score"]} for r in work]}
