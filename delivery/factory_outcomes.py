"""Join independently verified outcomes with exact-head delivery evidence."""
from collections import Counter
from datetime import datetime
import json

from .candidate import FULL_REVISION


def metric_coverage(runs):
    coverage = {}
    for key in ("wall_seconds", "cost_usd"):
        known = [run["metrics"][key] for run in runs if run["metrics"].get(key) is not None]
        coverage[key] = {"observed_runs": len(known),
                         "total": round(sum(known), 3) if runs and len(known) == len(runs) else None}
    return coverage


def timestamp(value):
    time = datetime.fromisoformat(value)
    if time.utcoffset() is None:
        raise ValueError("outcome observation requires a timezone")
    return time


def outcome_report(directory, prs, lifecycle, observations, production_environment):
    if not production_environment:
        raise ValueError("name the owned production environment explicitly")
    runs = [json.loads(path.read_text()) for path in sorted(directory.glob("*.json"))]
    repo = lifecycle["repository"].lower()
    owned_prefix = f"https://github.com/{repo}/pull/"
    indexed_prs = {}
    indexed_deployments = {}
    for run in runs:
        if run["pr"]:
            indexed_prs.setdefault(run["pr"].lower(), []).append(run)
        if run.get("runtime_identity") and (not run["pr"] or run["pr"].lower().startswith(owned_prefix)):
            key = (run["runtime_identity"]["deployment"], run["head"])
            indexed_deployments.setdefault(key, []).append(run)
    upstream = []
    for row in prs:
        url = row["url"].lower()
        if url.startswith(owned_prefix) or row["state"] != "MERGED":
            continue
        attempts = indexed_prs.get(url, [])
        head = row["head"]
        verified = bool(FULL_REVISION.fullmatch(head or "")) and any(
            run["head"] == head and run["outcome"].get("readiness") == "verified"
            and run["outcome"].get("browser") != "failed" for run in attempts
        )
        upstream.append({"pr": row["url"], "head": head, "merge_commit": row["merge_commit"],
                         "merged_at": row["merged_at"], "readiness_verified": verified,
                         "metrics": metric_coverage(attempts)})
    owned = []
    # A staging lifecycle snapshot cannot stand in for a configured production environment.
    if lifecycle["environment"] == production_environment:
        for deployment in lifecycle["deployments"]:
            revision, deployment_id = deployment["revision"], deployment["id"]
            matches = [sample for sample in observations if sample.get("revision") == revision
                       and sample.get("deployment") == deployment_id
                       and sample.get("verdict") in {"verified", "failed"}
                       and sample.get("ended_at") and sample.get("started_at")
                       and timestamp(sample["ended_at"]) > timestamp(sample["started_at"])
                       and timestamp(sample["started_at"]) >= timestamp(deployment["created_at"])]
            newest = max(matches, key=lambda sample: (timestamp(sample["ended_at"]), sample["verdict"] == "failed"),
                         default=None)
            verified = bool(newest and newest.get("reason") == "impact_threshold_passed"
                            and newest["verdict"] == "verified"
                            and deployment["reported_state"] == "success")
            attached_runs = indexed_deployments.get((deployment_id, revision), [])
            owned.append({"deployment": deployment_id, "revision": revision,
                          "runtime_verdict": "verified" if verified else
                          "failed" if newest and newest["verdict"] == "failed" else "inconclusive",
                          "metrics": metric_coverage(attached_runs)})
    return {"upstream": {"merged": len(upstream), "verified_merges": sum(row["readiness_verified"] for row in upstream),
                         "changes": upstream},
            "owned_production": {"environment": production_environment,
                                 "observed_environment": lifecycle["environment"],
                                 "verdicts": dict(Counter(row["runtime_verdict"] for row in owned)),
                                 "deployments": owned}}
