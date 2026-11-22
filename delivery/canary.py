"""Read rollout health from deployment-labelled Prometheus counters."""
from datetime import datetime, timezone
import json
import math
import os
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .revisions import FULL_REVISION


MAX_RESPONSE = 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def read_policy(raw, start, end):
    fields = {"version", "requests_metric", "successes_metric", "step_seconds", "minimum_requests",
              "minimum_success_rate", "max_success_rate_drop", "candidate", "control"}
    if not isinstance(raw, dict) or raw.keys() != fields or type(raw["version"]) is not int or raw["version"] != 1:
        raise ValueError("expected a version 1 canary policy")
    for name in ("requests_metric", "successes_metric"):
        if not isinstance(raw[name], str) or not re.fullmatch(r"[a-zA-Z_:][a-zA-Z0-9_:]{0,95}", raw[name]):
            raise ValueError("expected a Prometheus counter name")
    if raw["requests_metric"] == raw["successes_metric"]:
        raise ValueError("invoke distinct request and success counters")
    for name in ("candidate", "control"):
        cohort = raw[name]
        if (not isinstance(cohort, dict) or cohort.keys() != {"revision", "deployment"}
                or not isinstance(cohort["revision"], str) or not FULL_REVISION.fullmatch(cohort["revision"])
                or not isinstance(cohort["deployment"], str)
                or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", cohort["deployment"])):
            raise ValueError("canary cohorts require a full revision and deployment ID")
    if raw["candidate"]["deployment"] == raw["control"]["deployment"]:
        raise ValueError("canary and control require different deployments")
    step = raw["step_seconds"]
    count = raw["minimum_requests"]
    if (type(step) is not int or not 1 <= step <= 300 or type(count) is not int or count < 1
            or type(start) is not int or type(end) is not int or start <= 0 or end > int(datetime.now(timezone.utc).timestamp())
            or not 2 <= (end - start) // step <= 120 or (end - start) % step):
        raise ValueError("select a completed, aligned observation window with 3–121 points")
    for name in ("minimum_success_rate", "max_success_rate_drop"):
        if type(raw[name]) not in (float, int) or not 0 <= raw[name] <= 1:
            raise ValueError("canary success rates must be in 0–1")
    return raw


def prometheus(origin, *, token=None):
    parsed = urlsplit(origin)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/") or parsed.scheme not in ("https", "http")
            or (parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "::1"))):
        raise ValueError("select an HTTPS metrics origin or a loopback HTTP origin")
    opener = build_opener(ProxyHandler({}), NoRedirect())

    def query(selector, start, end, step):
        args = urlencode({"query": selector, "start": start, "end": end, "step": step})
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        request = Request(origin.rstrip("/") + "/api/v1/query_range?" + args, headers=headers)
        with opener.open(request, timeout=10) as response:
            data = response.read(MAX_RESPONSE + 1)
        if len(data) > MAX_RESPONSE:
            raise ValueError("Prometheus response exceeded the byte limit")
        return json.loads(data)

    return query


def counter(query, metric, identity, start, end, step):
    labels = ",".join(f"{key}={json.dumps(value)}" for key, value in identity.items())
    selector = f"{metric}{{{labels}}}"
    # Require a recent scrape at every evaluation point rather than carrying stale samples forward.
    response = query(f"{selector} and (time() - timestamp({selector}) <= {max(2 * step, 5)})", start, end, step)
    data = response["data"]
    if (response["status"] != "success" or response.get("warnings")
            or data["resultType"] != "matrix" or len(data["result"]) != 1):
        raise ValueError("expected exactly one complete counter series")
    item = data["result"][0]
    if item["metric"].get("__name__") != metric or any(item["metric"].get(k) != v for k, v in identity.items()):
        raise ValueError("metrics identity does not match the requested cohort")
    values = item["values"]
    if [pair[0] for pair in values] != list(range(start, end + 1, step)):
        raise ValueError("counter points do not cover the observation window")
    counts = [float(pair[1]) for pair in values]
    if (any(not math.isfinite(value) or not 0 <= value < 2 ** 53 or not value.is_integer() for value in counts)
            or any(left > right for left, right in zip(counts, counts[1:]))):
        raise ValueError("counter reset or non-integer sample")
    return [int(right - left) for left, right in zip(counts, counts[1:])]


def observe(policy, query, start, end):
    def stamp(value):
        return datetime.fromtimestamp(value, timezone.utc).isoformat()

    report = {"source": "prometheus", "metric": "request_success", "started_at": stamp(start),
              "ended_at": stamp(end), "policy": policy, "operator_approval_required": True}
    for cohort in ("candidate", "control"):
        identity = policy[cohort]
        step = policy["step_seconds"]
        try:
            requests = counter(query, policy["requests_metric"], identity, start, end, step)
            successes = counter(query, policy["successes_metric"], identity, start, end, step)
            if any(ok > total for total, ok in zip(requests, successes)):
                raise ValueError("success increment exceeds request increment")
        except (OSError, OverflowError, ValueError, KeyError, TypeError) as exc:
            return {**report, "verdict": "inconclusive", "reason": "metrics_unavailable",
                    "recommendation": "hold", "cohort": cohort, "detail": str(exc)}
        samples = sum(requests)
        report[cohort] = {**identity, "cohort": cohort, "source": "prometheus", "metric": "request_success",
                          "started_at": report["started_at"], "ended_at": report["ended_at"],
                          "samples": samples, "successes": sum(successes),
                          "success_rate": sum(successes) / samples if samples else None}
    candidate, control = report["candidate"], report["control"]
    if min(candidate["samples"], control["samples"]) < policy["minimum_requests"]:
        return {**report, "verdict": "inconclusive", "reason": "insufficient_requests", "recommendation": "hold"}
    floor = policy["minimum_success_rate"]
    if control["success_rate"] < floor:
        return {**report, "verdict": "inconclusive", "reason": "unhealthy_control", "recommendation": "hold"}
    drop = control["success_rate"] - candidate["success_rate"]
    if candidate["success_rate"] < floor or drop > policy["max_success_rate_drop"]:
        return {**report, "verdict": "failed", "reason": "candidate_regression", "recommendation": "review_rollback"}
    return {**report, "verdict": "verified", "reason": "canary_health_passed", "recommendation": "review_promotion"}


def register(actions):
    from pathlib import Path

    command = actions.add_parser("canary-observe", help="compare read-only metrics for exact deployments")
    command.add_argument("--policy", required=True, type=Path)
    command.add_argument("--origin", required=True)
    command.add_argument("--start", type=int, required=True, help="completed UTC epoch second")
    command.add_argument("--end", type=int, required=True)
    command.add_argument("--token-env", help="environment variable containing the read-only bearer token")


def dispatch(args):
    policy = read_policy(json.loads(args.policy.read_bytes()), args.start, args.end)
    token = os.environ[args.token_env] if args.token_env else None
    result = observe(policy, prometheus(args.origin, token=token), args.start, args.end)
    return result, int(result["verdict"] != "verified")
