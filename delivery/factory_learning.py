"""Index trusted run receipts and mine reproducible factory failures."""
from collections import Counter, defaultdict
from datetime import datetime
from hashlib import file_digest, sha256
import json
from math import isfinite
from pathlib import Path
from statistics import median
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


def assess_process(facts):
    head, source = facts["head"], facts["evidence"]
    if not FULL_REVISION.fullmatch(head) or not isinstance(source, str) or not source.strip():
        raise ValueError("process evidence needs an exact head and a source")
    dimensions = {key: {"state": "unknown", "reason": "missing_observation", "evidence": source}
                  for key in sorted(ASSESSMENTS)}

    def score(dimension, failed, failure, success):
        dimensions[dimension] = {"state": "failed" if failed else "passed",
                                 "reason": failure if failed else success, "evidence": source}

    skills = facts.get("skills", {})
    if skills.get("complete") is True:
        required, loaded = skills["required"], skills["loaded"]
        if not all(isinstance(values, list) and all(isinstance(item, str) and item for item in values)
                   for values in (required, loaded)):
            raise ValueError("skill inventory needs lists of nonempty skill IDs")
        score("skill_adherence", bool(set(required) - set(loaded)),
              "required_skill_missing", "required_skills_loaded")
    tests = facts.get("tests", {})
    if tests.get("reviewed") is True:
        redundant = tests["redundant"]
        if not isinstance(redundant, list) or not all(isinstance(item, str) and item for item in redundant):
            raise ValueError("test review needs a list of confirmed redundant tests")
        score("test_redundancy", bool(redundant), "redundant_test_confirmed", "no_redundancy_observed")
    retries = facts.get("retries", {})
    if retries.get("complete") is True:
        repeated = retries["repeated_without_change"]
        if type(repeated) is not int or repeated < 0:
            raise ValueError("retry observation needs a nonnegative count")
        score("retry_efficiency", repeated > 0, "repeated_unchanged_failure", "no_unchanged_retries")
    return {"head": head, "dimensions": dimensions}


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
    if "assessment" in paths and "process" in paths:
        raise ValueError("choose scored process facts or a reviewed assessment")
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
        elif kind in {"assessment", "process"}:
            if kind == "process":
                data = assess_process(data)
            if data["head"] != head:
                raise ValueError("assessment belongs to another revision")
            for dimension, assessment in data["dimensions"].items():
                if (dimension not in ASSESSMENTS or assessment["state"] not in MODES
                        or not KEY.fullmatch(assessment["reason"]) or not assessment.get("evidence")):
                    raise ValueError("assessment requires a known dimension, reason and evidence")
                if assessment["state"] == "failed":
                    findings[(dimension, assessment["reason"])] = "factory"
            outcome.setdefault("assessment", {}).update({key: item["state"]
                                                         for key, item in data["dimensions"].items()})
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


def index_spool(spool, directory):
    for path in sorted(spool.glob("*.json")):
        run_record(path, directory)


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


def measure(directory):
    cohorts = defaultdict(list)
    for path in sorted(directory.glob("*.json")):
        run = json.loads(path.read_text())
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
