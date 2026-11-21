"""Validate, fingerprint and index trusted run receipts."""
from datetime import datetime
from hashlib import file_digest, sha256
import json
from math import isfinite
import re

from .revisions import FULL_REVISION
from .factory_definition import check_definition
from . import browser_proof
from .run_state import lock, record
from .github import PR_URL


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
    if request.get("base") and not FULL_REVISION.fullmatch(request["base"]):
        raise ValueError("run baseline must be an exact Git revision")
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
    provenance = {}
    runtime_identity = None
    for kind, filename in paths.items():
        path = spec.parent / filename
        if kind == "browser":
            base = request.get("base") or None
            proof = browser_proof.capture(path, head=head, base=base)
            receipts[kind] = proof.receipt_reference
            outcome[kind] = "verified" if proof.passed else "failed"
            if base:
                provenance["browser_base"] = base
            continue
        data, receipts[kind] = read_receipt(path)
        if kind == "definition":
            check_definition(data, factory)
            provenance["definition"] = data["sha256"]
        elif kind == "workflow":
            provenance["workflow_plan"] = data["identity"].get("plan_sha256")
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
        elif kind in {"readiness", "runtime", "pr"}:
            field = {"readiness": "candidate", "runtime": "revision", "pr": "head"}[kind]
            if data[field] != head or (kind == "pr" and data["url"] != pr):
                raise ValueError(f"{kind} receipt belongs to another PR or revision")
            if kind == "pr":
                outcome.update(pr=data["state"], ci=data["action"], review=data.get("review", {}).get("action"))
            else:
                outcome[kind] = data["verdict"]
                if kind == "readiness":
                    if request.get("base") and data["base"] != request["base"]:
                        raise ValueError("readiness receipt belongs to another baseline")
                    provenance["contract"] = data.get("contract_sha256")
                else:
                    runtime_identity = {"deployment": data.get("deployment")}
                    provenance["runtime_contract"] = data.get("contract_sha256")
        elif kind == "recipe":
            if data["revision"] != request.get("base", head):
                raise ValueError("Codex recipe belongs to another starting revision")
            provenance["recipe"] = {key: data[key] for key in (
                "model", "codex", "skill_sha256", "contract_sha256", "sandbox") if key in data}
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
    for attachment in ("patch", "trace"):
        if request.get(attachment):
            path = spec.parent / request[attachment]
            with path.open("rb") as file:
                receipts[attachment] = {"file": path.name, "sha256": file_digest(file, "sha256").hexdigest()}
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
    if request.get("base"):
        result["base"] = request["base"]
    if provenance:
        result["provenance"] = provenance
    if runtime_identity:
        result["runtime_identity"] = runtime_identity
    path = directory / f"{run_id}.json"
    with lock(directory):
        if path.exists():
            existing = json.loads(path.read_text())
            if existing == result:
                return existing
            additions = {"base", "provenance", "runtime_identity"}
            if not additions.intersection(existing) and existing == {
                key: value for key, value in result.items() if key not in additions
            }:
                return existing
            raise ValueError("run already exists with different evidence; use a new run ID")
        else:
            record(path, result)
    return result


def index_spool(spool, directory):
    for path in sorted(spool.glob("*.json")):
        run_record(path, directory)


def entries(directory):
    """Yield index filenames and records in deterministic order, including legacy records."""
    for path in sorted(directory.glob("*.json")):
        yield path.stem, json.loads(path.read_text())


def indexed_runs(directory):
    if not directory.is_dir():
        raise ValueError("factory run index must be an existing directory")
    return [run for _, run in entries(directory)]
