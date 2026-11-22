"""Compare trusted observations and turn them into stable delivery evidence."""
from collections import Counter
from datetime import datetime
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
from threading import Thread

from .impact import impact_verdict
from .verify import Contract, Probe, canonical_json, verify


def self_check():
    revision, deployment = "a" * 40, "control"
    contract = Contract("The control returns its expected value.", ("pilot/service.py",), 2,
                        (Probe("/value", {"value": 42}),), "control")
    cases = [
        ("known-good", "verified", "all_required_evidence_passed"),
        ("wrong-behavior", "failed", "probe_failed"),
        ("stale-ci", "inconclusive", "missing_or_stale_ci"),
        ("wrong-deployment", "inconclusive", "wrong_deployment"),
        ("rollout-during-check", "inconclusive", "deployment_changed"),
        ("runtime-unavailable", "inconclusive", "runtime_unavailable"),
    ]

    def run(case):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                if self.path == "/_revision":
                    state = "other" if case == "wrong-deployment" or (
                        case == "rollout-during-check" and self.server.probed) else deployment
                    body = {"revision": revision, "deployment": state}
                else:
                    self.server.probed = True
                    if case == "runtime-unavailable":
                        self.close_connection = True
                        return
                    body = {"value": 41 if case == "wrong-behavior" else 42}
                payload = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            server.probed = False
            worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
            worker.start()
            try:
                ci = {"revision": "b" * 40 if case == "stale-ci" else revision,
                      "deployment": deployment, "status": "passed"}
                return verify(contract, f"http://127.0.0.1:{server.server_port}", revision, deployment, ci)
            finally:
                server.shutdown()
                worker.join()

    results = []
    for case, verdict, reason in cases:
        actual = run(case)
        results.append({"case": case, "verdict": actual["verdict"], "reason": actual["reason"],
                        "passed": (actual["verdict"], actual["reason"]) == (verdict, reason)})
    count = classify_check(0, 0)
    results.append({"case": "empty-test-discovery", **count, "passed": count["verdict"] == "inconclusive"})
    return {"passed": all(case["passed"] for case in results), "cases": results}


def classify_check(exit_code, tests=None):
    if exit_code is None:
        return {"verdict": "inconclusive", "reason": "deadline_or_runner_unavailable"}
    if exit_code == 0 and tests == 0:
        return {"verdict": "inconclusive", "reason": "empty_test_discovery"}
    return {"verdict": "verified", "reason": "exit_zero"} if exit_code == 0 else {
        "verdict": "failed", "reason": "nonzero_exit"}


def failure_fingerprint(failure):
    parts = [failure.get(key, "").strip() for key in ("check", "test", "signature")]
    if not all(parts):
        raise ValueError("failure needs check, test and a stable error signature")
    return sha256(canonical_json(parts).encode()).hexdigest()


def compare_failures(head, base):
    """Consume structured failures from a trusted check runner, never free-text instructions."""
    if head["environment"] != base["environment"] or head["base"] != base["revision"]:
        return {"verdict": "inconclusive", "reason": "baseline_identity_mismatch"}
    if head.get("complete") is not True or base.get("complete") is not True:
        return {"verdict": "inconclusive", "reason": "incomplete_check"}
    baseline = {failure_fingerprint(item) for item in base["failures"]}
    routes = []
    for item in head["failures"]:
        fingerprint = failure_fingerprint(item)
        routes.append({**item, "fingerprint": fingerprint,
                       "action": "follow_upstream_dependency" if fingerprint in baseline else "investigate_candidate"})
    return {"verdict": "classified", "head": head["revision"], "base": base["revision"], "routes": routes}


def portfolio(records, ledger, related=()):
    comparisons = {}
    for item in related:
        key = (item.get("pr"), item.get("head"))
        comparisons[key] = {**comparisons.get(key, {}), **item}
    queued = {}
    for action in ledger.get("pending", []):
        queued.setdefault((action["pr"].lower(), action["head"]), []).append(
            {key: action[key] for key in ("id", "kind", "state")})
    holds = {item["pr"].lower(): item for item in ledger.get("unconfirmed_pushes", [])}
    result = []
    for item in records:
        pr, head = item["url"], item.get("head")
        attached = comparisons.get((pr, head))
        review = item.get("review", {})
        result.append({"pr": pr, "head": head, "base": item.get("base"), "state": item.get("state"),
                       "ci": item["action"], "signals": item.get("signals", []), "review": review.get("action"),
                       "decision": review.get("decision"), "actions": queued.get((pr.lower(), head), []),
                       "unconfirmed_push": holds.get(pr.lower()), "evidence": attached,
                       "local_replay": item.get("local_replay"),
                       "merge": {key: item[key] for key in ("merged_at", "merged_by", "merge_commit") if key in item}})
    return {"counts": dict(Counter(row["state"] or "UNKNOWN" for row in result)), "prs": result}


EVENTS = ("proposed", "verified", "published", "merged", "declined", "reverted", "released")


def adoption(events):
    history = {}
    for event in events:
        if event["event"] not in EVENTS or not re.fullmatch(r"[0-9a-f]{40}", event["revision"]):
            raise ValueError("adoption event requires a known event and full revision")
        if datetime.fromisoformat(event["at"]).utcoffset() is None:
            raise ValueError("adoption event requires a timezone")
        head = history.setdefault((event["subject"], event["revision"]), {})
        head.setdefault(event["event"], event)
    return {"counts": dict(Counter(kind for item in history.values() for kind in item)),
            "subjects": [list(item.values()) for item in history.values()]}


def compose_evidence(runtime, revision, policy, source_sha256, contract_sha256):
    observation = runtime.get("observation", {})
    cleanup = runtime.get("cleanup", {})
    image = runtime.get("image_id", "")
    deployment = runtime.get("deployment", "")
    if (runtime.get("verdict") != "verified" or runtime.get("revision") != revision
            or runtime.get("policy_revision") != policy or runtime.get("source_sha256") != source_sha256
            or runtime.get("contract_sha256") != contract_sha256
            or not re.fullmatch(r"adl-pilot-[0-9a-f]{16}", deployment)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", image)
            or runtime.get("redis_counter") != "2"
            or cleanup != {"status": "confirmed", "remaining":
                           {"container": [], "network": [], "volume": [], "image": []}}
            or observation.get("verdict") != "verified" or observation.get("revision") != revision
            or observation.get("deployment") != deployment
            or observation.get("contract_sha256") != contract_sha256
            or observation.get("ci", {}).get("artifact_sha256") != image.removeprefix("sha256:")):
        raise ValueError("candidate requires exact Compose evidence, Redis readback, and confirmed cleanup")
    return {"kind": "compose", "deployment": deployment, "image_id": image,
            "receipt_sha256": sha256(canonical_json(runtime).encode()).hexdigest()}


def bundle(receipt, artifacts, *, runtime=None):
    if receipt.get("verdict") != "verified":
        raise ValueError("bundle requires a verified receipt")
    revision = receipt["revision"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("bundle requires a full candidate revision")
    files = [{"name": path.name, "sha256": sha256(path.read_bytes()).hexdigest(),
              "bytes": path.stat().st_size} for path in artifacts]
    if len({item["name"] for item in files}) != len(files):
        raise ValueError("artifact names must be unique")
    return {"version": 1, "revision": revision, "deployment": receipt["deployment"],
            "policy_revision": receipt["ci"]["policy_revision"],
            "contract_sha256": receipt["contract_sha256"], "receipt_sha256":
                sha256(canonical_json(receipt).encode()).hexdigest(), "artifacts": files,
            **({"runtime": runtime} if runtime is not None else {})}


def analysis_observation(run, policy, revision, deployment, *, uid):
    meta, status = run["metadata"], run.get("status", {})
    annotations = meta.get("annotations", {})
    if (run.get("kind") != "AnalysisRun" or meta.get("uid") != uid
            or annotations.get("adl/revision") != revision
            or annotations.get("adl/deployment") != deployment):
        return impact_verdict(policy, {}, revision, deployment)
    target = next((item for item in status.get("metricResults", []) if item["name"] == policy.metric), {})
    observations = target.get("measurements", [])
    if (status.get("phase") not in {"Successful", "Failed"} or not observations
            or any(item.get("phase") not in {"Successful", "Failed"} for item in observations)):
        return impact_verdict(policy, None, revision, deployment)
    try:
        start = min(datetime.fromisoformat(item["startedAt"]) for item in observations)
        end = max(datetime.fromisoformat(item["finishedAt"]) for item in observations)
    except (KeyError, ValueError, TypeError):
        return impact_verdict(policy, None, revision, deployment)
    evidence = {"revision": revision, "deployment": deployment, "source": policy.source,
                "metric": policy.metric, "cohort": policy.cohort, "started_at": start.isoformat(),
                "ended_at": end.isoformat(), "samples": len(observations),
                "successes": sum(item["phase"] == "Successful" for item in observations)}
    if status["phase"] == "Failed":
        result = impact_verdict(policy, evidence, revision, deployment)
        return {**result, "verdict": "failed", "reason": "analysis_run_failed"}
    return impact_verdict(policy, evidence, revision, deployment)
