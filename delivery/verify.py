"""Verify a deployment against the reviewed outcome contract."""
from dataclasses import asdict, dataclass
from hashlib import sha256
from http.client import HTTPException
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .impact import ImpactPolicy, impact_verdict
from .scenario import HttpStep, RedisStep, read_steps, readback


def product_path(value):
    return (isinstance(value, str) and len(value) <= 256
            and all(re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", part)
                    for part in value.split("/")))


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
    impact: ImpactPolicy | None = None
    acceptance: dict | None = None
    technical_brief: str | None = None
    steps: tuple[HttpStep | RedisStep, ...] = ()

    @classmethod
    def read(cls, path, *, product=False):
        return cls.from_bytes(path.read_bytes(), product=product)

    @classmethod
    def from_bytes(cls, raw, *, product=False):
        data = json.loads(raw)
        version = data.get("version") if isinstance(data, dict) else None
        if type(version) is not int or not (version == 1 or (product and version == 2)):
            raise ValueError("expected a version 1 outcome contract or a reviewed product scenario")
        checks = "probes" if version == 1 else "steps"
        fields = {"version", "outcome", "allowed_changes", "max_repairs", checks}
        if not fields <= data.keys() <= fields | {"impact", "acceptance", "technical_brief", "reproduction", "reproduction_path"}:
            raise ValueError("unexpected outcome contract fields")
        repairs = data["max_repairs"]
        if type(repairs) is not int or not 0 <= repairs <= 5:
            raise ValueError("max_repairs must be an integer from 0 to 5")
        if not isinstance(data["outcome"], str) or not data["outcome"].strip():
            raise ValueError("outcome must describe the expected behavior")
        paths = data["allowed_changes"]
        if not isinstance(paths, list) or not paths or any(
            not isinstance(item, str) or (not product and not item.startswith("pilot/"))
            or (product and not product_path(item))
            or ".." in item.split("/") or item.endswith("/") for item in paths
        ):
            raise ValueError("allowed_changes must name product files" if product else
                             "allowed_changes must name files inside pilot/")
        probes = []
        raw_probes = data.get("probes", [])
        if version == 1 and (not isinstance(raw_probes, list) or not raw_probes):
            raise ValueError("at least one behavior probe is required")
        for probe in raw_probes:
            if not isinstance(probe, dict) or probe.keys() != {"path", "expect"}:
                raise ValueError("probe requires path and expect")
            endpoint, expect = probe["path"], probe["expect"]
            if (not isinstance(endpoint, str) or not endpoint.startswith("/")
                    or endpoint.startswith("//") or endpoint == "/_revision"
                    or urlsplit(endpoint).fragment or not isinstance(expect, dict)):
                raise ValueError("probe requires a local path and a JSON object")
            probes.append(Probe(endpoint, expect))
        impact = ImpactPolicy.read(data["impact"]) if "impact" in data else None
        acceptance = data.get("acceptance")
        if "acceptance" in data and (
            not isinstance(acceptance, dict) or acceptance.keys() != {"expected", "control", "boundary"}
            or any(not isinstance(value, str) or not value.strip() for value in acceptance.values())
        ):
            raise ValueError("acceptance requires expected, control, and boundary examples")
        for key in ("technical_brief", "reproduction", "reproduction_path"):
            if key in data and (not isinstance(data[key], str) or not data[key].strip()):
                raise ValueError(f"{key} must be nonempty text")
        return cls(data["outcome"], tuple(paths), repairs, tuple(probes), sha256(raw).hexdigest(), impact,
                   acceptance, data.get("technical_brief"), read_steps(data["steps"]) if version == 2 else ())


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def fetch(origin, path, *, method="GET", body=None, read_error_body=False):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    request = Request(origin + path, data=data, headers=headers, method=method)
    try:
        with HTTP.open(request, timeout=5) as response:
            payload = response.read(65537)
            if len(payload) > 65536:
                return {"status": response.status, "error": "response too large"}
            if not payload:
                return {"status": response.status}
            try:
                body = json.loads(payload)
            except (UnicodeError, ValueError):
                return {"status": response.status, "error": "invalid JSON response"}
            return {"status": response.status, "body": body}
    except HTTPError as exc:
        with exc:
            if not read_error_body:
                return {"status": exc.code}
            payload = exc.read(65537)
            if len(payload) > 65536:
                return {"status": exc.code, "error": "response too large"}
            try:
                return {"status": exc.code, "body": json.loads(payload)}
            except (UnicodeError, ValueError):
                return {"status": exc.code}
    except (URLError, OSError, HTTPException) as exc:
        return {"error": str(exc)}


def advice(verdict, reason, repairs_used, max_repairs):
    if verdict == "verified":
        return "complete"
    if verdict == "failed" and reason in {"ci_failed", "probe_failed"} and repairs_used < max_repairs:
        return "repair"
    return "escalate"


def verify(contract, origin, revision, deployment, ci, repairs_used=0, impact_evidence=None, *, read_state=None):
    report = {
        "revision": revision, "deployment": deployment, "contract_sha256": contract.digest,
        "ci": ci, "identity": None, "probes": [], "repairs_used": repairs_used,
        "runtime_verdict": "not_evaluated",
        "impact": {"verdict": "not_evaluated" if contract.impact else "not_required"},
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

    report["runtime_verdict"] = "inconclusive"
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
    if contract.steps:
        report["steps"] = []
        for step in contract.steps:
            if fetch(origin, "/_revision") != identity:
                return finish("inconclusive", "deployment_changed")
            if isinstance(step, HttpStep):
                observed = fetch(origin, step.path, method=step.method, body=step.body, read_error_body=True)
                if "status" not in observed:
                    return finish("inconclusive", "runtime_unavailable")
                passed = (observed["status"] == step.status and observed.get("error") != "response too large" and
                          (step.expect is None or canonical_json(observed.get("body")) == canonical_json(step.expect)))
            else:
                if read_state is None:
                    return finish("inconclusive", "scenario_reader_unavailable")
                observed = readback(step, read_state)
                passed = observed == step.expect
            report["steps"].append({"kind": "http" if isinstance(step, HttpStep) else "redis",
                                    **asdict(step), "observed": observed, "passed": passed})
            if not passed:
                break
    # Detect a rollout that changes the serving deployment during the probe set.
    report["identity_after"] = fetch(origin, "/_revision")
    if report["identity_after"] != identity:
        return finish("inconclusive", "deployment_changed")
    if any("status" not in probe["observed"] for probe in report["probes"]):
        return finish("inconclusive", "runtime_unavailable")
    if not all(probe["passed"] for probe in report["probes"]):
        report["runtime_verdict"] = "failed"
        return finish("failed", "probe_failed")
    if any(not step["passed"] for step in report.get("steps", ())):
        report["runtime_verdict"] = "failed"
        return finish("failed", "scenario_step_failed")
    report["runtime_verdict"] = "verified"
    impact = report["impact"] = impact_verdict(contract.impact, impact_evidence, revision, deployment)
    if impact["verdict"] in {"failed", "inconclusive"}:
        return finish(impact["verdict"], impact["reason"])
    return finish("verified", "all_required_evidence_passed")
