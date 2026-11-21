"""Index trusted run receipts and mine reproducible factory failures."""
from collections import defaultdict
from datetime import datetime
from hashlib import file_digest, sha256
import json
from math import isfinite
from pathlib import Path
import re

from .candidate import FULL_REVISION
from .factory_evidence import browser_evidence
from .factory_workflow import lock, record
from .upstream_ci import PR_URL


KEY = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}", re.ASCII)
ASSESSMENTS = {"skill_adherence", "test_redundancy", "retry_efficiency"}
INFRASTRUCTURE = {"deadline_or_runner_unavailable", "runner_unavailable",
                  "runtime_unavailable", "missing_artifact", "missing_or_stale_ci"}
MODES = {"passed", "failed", "unknown"}


def read_receipt(path):
    contents = path.read_bytes()
    return json.loads(contents), {"file": path.name, "sha256": sha256(contents).hexdigest()}


def run_record(spec, directory):
    """Use operator-owned receipt paths. Store hashes and observations without copying raw traces."""
    request, source = read_receipt(spec)
    run_id, head, factory = request["id"], request["head"], request["factory_revision"]
    if (not KEY.fullmatch(run_id) or not FULL_REVISION.fullmatch(head)
            or not FULL_REVISION.fullmatch(factory)):
        raise ValueError("run needs a stable ID and full candidate and factory revisions")
    if datetime.fromisoformat(request["finished_at"]).utcoffset() is None:
        raise ValueError("run timestamp needs a timezone")
    pr = request.get("pr")
    if pr is not None and not PR_URL.fullmatch(pr):
        raise ValueError("expected an exact GitHub PR URL")

    receipts = {"spec": source}
    findings = {}
    outcome = {}
    retries = {"product": 0, "infrastructure": 0}
    paths = request.get("receipts", {})
    for kind, filename in paths.items():
        path = spec.parent / filename
        data, receipts[kind] = read_receipt(path)
        if kind == "workflow":
            if data["identity"]["revision"] != head:
                raise ValueError("workflow receipt belongs to another revision")
            outcome["workflow"] = data["status"]
            for step in data["steps"].values():
                for category in retries:
                    retries[category] += step.get("attempts", {}).get(category, 0)
                reason = step.get("reason", "")
                if step["state"] in {"failed", "inconclusive"} and KEY.fullmatch(reason):
                    category = ("infrastructure" if reason in INFRASTRUCTURE
                                else "factory" if reason in {"revision_changed", "tracked_source_changed"}
                                else "unclassified")
                    findings[("workflow", reason)] = category
        elif kind in {"readiness", "runtime", "browser", "pr"}:
            field = {"readiness": "candidate", "runtime": "revision", "browser": "after", "pr": "head"}[kind]
            if data[field] != head or (kind == "pr" and data["url"] != pr):
                raise ValueError(f"{kind} receipt belongs to another PR or revision")
            if kind == "pr":
                outcome.update(pr=data["state"], ci=data["action"], review=data.get("review", {}).get("action"))
            elif kind == "browser":
                passed, _ = browser_evidence(path, head)
                outcome[kind] = "verified" if passed else "failed"
            else:
                outcome[kind] = data["verdict"]
        elif kind == "recipe":
            if data["revision"] != request.get("base", head):
                raise ValueError("Codex recipe belongs to another starting revision")
        elif kind == "assessment":
            if data["head"] != head:
                raise ValueError("assessment belongs to another revision")
            for dimension, assessment in data["dimensions"].items():
                if (dimension not in ASSESSMENTS or assessment["state"] not in MODES
                        or not KEY.fullmatch(assessment["reason"]) or not assessment.get("evidence")):
                    raise ValueError("assessment requires a known dimension, reason and evidence")
                if assessment["state"] == "failed":
                    findings[(dimension, assessment["reason"])] = "factory"
            outcome[kind] = {key: item["state"] for key, item in data["dimensions"].items()}
        else:
            raise ValueError(f"unsupported receipt kind: {kind}")

    if not paths:
        raise ValueError("record at least one receipt")
    trace = request.get("trace")
    if trace:
        path = spec.parent / trace
        with path.open("rb") as file:
            receipts["trace"] = {"file": path.name, "sha256": file_digest(file, "sha256").hexdigest()}
    metrics = request.get("metrics", {})
    for name, value in metrics.items():
        if name not in {"wall_seconds", "tokens", "cost_usd", "human_interventions"} or (
            value is not None and (type(value) not in (int, float) or not isfinite(value) or value < 0)
        ):
            raise ValueError("invalid run metric")
    result = {"id": run_id, "head": head, "factory_revision": factory, "pr": pr,
              "finished_at": request["finished_at"], "metrics": metrics, "outcome": outcome,
              "retries": retries, "receipts": receipts,
              "findings": [{"dimension": dimension, "reason": reason, "category": category}
                           for (dimension, reason), category in sorted(findings.items())]}
    path = directory / f"{run_id}.json"
    with lock(directory):
        if path.exists():
            if json.loads(path.read_text()) != result:
                raise ValueError("run already exists with different evidence; use a new run ID")
        else:
            record(path, result)
    return result


def mine(directory, *, minimum=2):
    """A cluster produces a proposal brief. Review and independent replay govern adoption."""
    if not 2 <= minimum <= 50:
        raise ValueError("minimum distinct runs must be 2–50")
    clusters = defaultdict(dict)
    run_count = 0
    for path in sorted(directory.glob("*.json")):
        run = json.loads(path.read_text())
        if path.stem != run["id"]:
            raise ValueError("run ID does not match its receipt name")
        run_count += 1
        for item in run["findings"]:
            if item["category"] == "factory":
                key = (item["dimension"], item["reason"])
                clusters[key][run["id"]] = {"run": run["id"], "head": run["head"],
                                            "factory_revision": run["factory_revision"]}
    proposals = [{"id": sha256(f"{dimension}:{reason}".encode()).hexdigest(),
                  "dimension": dimension, "reason": reason, "evidence": list(runs.values()),
                  "status": "needs_replay",
                  "acceptance": ["reproduce on the failing factory revision",
                                 "pass the same scenario on the proposed revision",
                                 "preserve a held-out normal case"]}
                 for (dimension, reason), runs in sorted(clusters.items()) if len(runs) >= minimum]
    return {"runs": run_count, "proposals": proposals}


def pr_evidence(directory):
    entries = {}
    for path in sorted(directory.glob("*.json")):
        run = json.loads(path.read_text())
        if not run["pr"]:
            continue
        key = (run["pr"], run["head"])
        entry = entries.setdefault(key, {"pr": key[0], "head": key[1], "runs": []})
        entry["runs"].append({field: run[field] for field in ("id", "outcome", "receipts")})
    return list(entries.values())
