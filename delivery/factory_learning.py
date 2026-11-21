"""Measure factory outcomes and identify recurring failures in indexed runs."""
from collections import Counter, defaultdict
from hashlib import sha256
from statistics import median

from .run_index import assess_process, entries, index_spool, indexed_runs, run_record


def mine(directory, *, minimum=2):
    """A cluster produces a proposal brief. Review and independent replay govern adoption."""
    if not 2 <= minimum <= 50:
        raise ValueError("minimum distinct runs must be 2–50")
    clusters = defaultdict(dict)
    run_count = 0
    for name, run in entries(directory):
        if name != run["id"]:
            raise ValueError("run ID does not match its receipt name")
        run_count += 1
        for item in run["findings"]:
            if item["category"] == "factory":
                key = (item["dimension"], item["reason"])
                clusters[key][run["id"]] = {"run": run["id"], "head": run["head"],
                                            "factory_revision": run["factory_revision"],
                                            "receipt_digests": {kind: item["sha256"] for kind, item
                                                                in run.get("receipts", {}).items()}}
    proposals = [{"id": sha256(f"{dimension}:{reason}".encode()).hexdigest(),
                  "dimension": dimension, "reason": reason, "evidence": list(runs.values()),
                  "status": "needs_replay",
                  "acceptance": ["reproduce on the failing factory revision",
                                 "pass the same scenario on the proposed revision",
                                 "preserve a held-out normal case"]}
                 for (dimension, reason), runs in sorted(clusters.items()) if len(runs) >= minimum]
    return {"runs": run_count, "proposals": proposals}


def measure(directory):
    cohorts = defaultdict(list)
    for _, run in entries(directory):
        cohorts[run["factory_revision"]].append(run)
    result = []
    for revision, runs in sorted(cohorts.items()):
        verified = [run for run in runs if any(run["outcome"].get(kind) == "verified"
                    for kind in ("readiness", "runtime", "workflow")) and
                    not any(run["outcome"].get(kind) == "failed"
                            for kind in ("readiness", "runtime", "workflow", "browser"))]
        changes = {(run["pr"], run["head"]) for run in verified}
        columns = {}
        for metric in ("wall_seconds", "tokens", "cost_usd", "human_interventions"):
            values = [run["metrics"].get(metric) for run in runs]
            known = [value for value in values if value is not None]
            columns[metric] = {"observed": len(known),
                               "median": median(known) if known else None,
                               "per_verified_change": round(sum(known) / len(changes), 3)
                               if changes and len(known) == len(values) else None}
        assessments = Counter(key for run in runs for key, value in
                              run["outcome"].get("assessment", {}).items() if value != "unknown")
        result.append({"factory_revision": revision, "runs": len(runs), "verified_changes": len(changes),
                       "metrics": columns, "assessments_observed": dict(assessments)})
    return {"cohorts": result}


def pr_evidence(runs):
    entries = {}
    for run in runs:
        if not run["pr"]:
            continue
        key = (run["pr"], run["head"])
        entry = entries.setdefault(key, {"pr": key[0], "head": key[1], "runs": []})
        entry["runs"].append({field: run[field] for field in ("id", "outcome", "receipts")})
    return list(entries.values())
