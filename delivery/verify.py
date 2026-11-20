"""Verify a deployment against the reviewed outcome contract."""
from dataclasses import asdict, dataclass
from hashlib import sha256
from http.client import HTTPException
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


HTTP = build_opener(NoRedirect())


@dataclass(frozen=True)
class Probe:
    path: str
    expect: dict


@dataclass(frozen=True)
class Contract:
    outcome: str
    allowed_changes: tuple[str, ...]
    max_repairs: int
    probes: tuple[Probe, ...]
    digest: str

    @classmethod
    def read(cls, path):
        raw = path.read_bytes()
        data = json.loads(raw)
        fields = {"version", "outcome", "allowed_changes", "max_repairs", "probes"}
        if not isinstance(data, dict) or data.keys() != fields or data["version"] != 1:
            raise ValueError("expected a version 1 outcome contract")
        repairs = data["max_repairs"]
        if type(repairs) is not int or not 0 <= repairs <= 5:
            raise ValueError("max_repairs must be an integer from 0 to 5")
        if not isinstance(data["outcome"], str) or not data["outcome"].strip():
            raise ValueError("outcome must describe the expected behavior")
        paths = data["allowed_changes"]
        if not isinstance(paths, list) or not paths or any(
            not isinstance(item, str) or not item.startswith("pilot/")
            or ".." in item.split("/") or item.endswith("/") for item in paths
        ):
            raise ValueError("allowed_changes must name files inside pilot/")
        probes = []
        if not isinstance(data["probes"], list) or not data["probes"]:
            raise ValueError("at least one behavior probe is required")
        for probe in data["probes"]:
            if not isinstance(probe, dict) or probe.keys() != {"path", "expect"}:
                raise ValueError("probe requires path and expect")
            endpoint, expect = probe["path"], probe["expect"]
            if (not isinstance(endpoint, str) or not endpoint.startswith("/")
                    or endpoint.startswith("//") or endpoint == "/_revision"
                    or urlsplit(endpoint).fragment or not isinstance(expect, dict)):
                raise ValueError("probe requires a local path and a JSON object")
            probes.append(Probe(endpoint, expect))
        return cls(data["outcome"], tuple(paths), repairs, tuple(probes), sha256(raw).hexdigest())


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def fetch(origin, path):
    try:
        with HTTP.open(origin + path, timeout=5) as response:
            payload = response.read(65537)
            if len(payload) > 65536:
                return {"status": response.status, "error": "response too large"}
            try:
                body = json.loads(payload)
            except (UnicodeError, ValueError):
                return {"status": response.status, "error": "invalid JSON response"}
            return {"status": response.status, "body": body}
    except HTTPError as exc:
        return {"status": exc.code}
    except (URLError, OSError, HTTPException) as exc:
        return {"error": str(exc)}


def advice(verdict, reason, repairs_used, max_repairs):
    if verdict == "verified":
        return "complete"
    if verdict == "failed" and reason in {"ci_failed", "probe_failed"} and repairs_used < max_repairs:
        return "repair"
    return "escalate"


def verify(contract, origin, revision, deployment, ci, repairs_used=0):
    report = {
        "revision": revision, "deployment": deployment, "contract_sha256": contract.digest,
        "ci": ci, "identity": None, "probes": [], "repairs_used": repairs_used,
    }

    def finish(verdict, reason):
        return {**report, "verdict": verdict, "reason": reason,
                "next_action": advice(verdict, reason, repairs_used, contract.max_repairs)}

    if not isinstance(ci, dict) or ci.get("revision") != revision or ci.get("deployment") != deployment:
        return finish("inconclusive", "missing_or_stale_ci")
    if ci.get("status") == "failed":
        return finish("failed", "ci_failed")
    if ci.get("status") != "passed":
        return finish("inconclusive", "missing_or_stale_ci")

    identity = fetch(origin, "/_revision")
    report["identity"] = identity
    if identity.get("status") != 200 or "body" not in identity:
        return finish("inconclusive", "runtime_unavailable")
    if identity["body"] != {"revision": revision, "deployment": deployment}:
        return finish("inconclusive", "wrong_deployment")

    for probe in contract.probes:
        observed = fetch(origin, probe.path)
        report["probes"].append({
            **asdict(probe), "observed": observed,
            "passed": observed.get("status") == 200 and "body" in observed
            and canonical_json(observed["body"]) == canonical_json(probe.expect),
        })
    # Detect a rollout that changes the serving deployment during the probe set.
    report["identity_after"] = fetch(origin, "/_revision")
    if report["identity_after"] != identity:
        return finish("inconclusive", "deployment_changed")
    if any("status" not in probe["observed"] for probe in report["probes"]):
        return finish("inconclusive", "runtime_unavailable")
    if not all(probe["passed"] for probe in report["probes"]):
        return finish("failed", "probe_failed")
    return finish("verified", "all_required_evidence_passed")
