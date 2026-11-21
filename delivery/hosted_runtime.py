"""Dispatch the owned runtime sandbox and collect evidence from its exact run."""
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory

from .candidate import FULL_REVISION, check_candidate, git
from .factory_evidence import compose_evidence
from .factory_publish import OWNER_REPO, remote_ref, verify_signature
from .factory_workflow import lock, record
from .upstream_ci import gh_json
from .verify import Contract, canonical_json


WORKFLOW = "trusted-candidate.yml"
RUN_URL = re.compile(rf"https://github\.com/{re.escape(OWNER_REPO)}/actions/runs/([1-9][0-9]*)")
CONTRACTS = ("pilot", "named-greeting")


def contract_at(repo, policy, name, folder):
    path = Path(folder) / "contract.json"
    path.write_bytes(git("show", f"{policy}:contracts/{name}.json", cwd=repo))
    return Contract.read(path)


def start(repo, state, revision, name):
    if not FULL_REVISION.fullmatch(revision) or name not in CONTRACTS:
        raise ValueError("hosted runtime needs an exact revision and an approved contract")
    with lock(state):
        path = state / "request.json"
        if path.exists():
            raise ValueError("this state already holds a dispatch; collect it without starting another run")
        policy = remote_ref(repo, "refs/heads/main")
        if policy is None:
            raise ValueError("owned main is unavailable")
        with TemporaryDirectory(dir=state) as folder:
            contract = contract_at(repo, policy, name, folder)
        check_candidate(revision, policy, contract.allowed_changes, cwd=repo)
        request = {"revision": revision, "contract": name, "contract_sha256": contract.digest,
                   "policy_revision": policy, "status": "dispatch_unconfirmed"}
        record(path, request)
        answer = subprocess.run(
            ["gh", "workflow", "run", WORKFLOW, "--repo", OWNER_REPO, "--ref", "main",
             "-f", f"candidate={revision}", "-f", f"contract={name}", "-f", "repairs-used=0",
             "-f", "publish=false"],
            text=True, capture_output=True, timeout=40,
        )
        if answer.returncode:
            raise ValueError(f"GitHub dispatch remains unconfirmed: {answer.stderr.strip()}")
        url = answer.stdout.strip()
        match = RUN_URL.fullmatch(url)
        if not match:
            raise ValueError("GitHub did not return the unique run URL; the dispatch remains unconfirmed")
        request.update(run_id=int(match[1]), url=url, status="dispatched")
        record(path, request)
        return request


def collect(repo, state):
    with lock(state):
        request = json.loads((state / "request.json").read_text())
        match = RUN_URL.fullmatch(request.get("url", ""))
        if not match or request.get("run_id") != int(match[1]):
            raise ValueError("dispatch is unconfirmed; locate the run in GitHub before starting another")
        run_id = request["run_id"]
        revision, policy = request["revision"], request["policy_revision"]
        endpoint = f"repos/{OWNER_REPO}/actions/runs/{run_id}"
        run = gh_json("api", endpoint)
        attempt = run["run_attempt"]
        result = {**request, "status": run["status"], "attempt": attempt, "conclusion": run["conclusion"]}
        if run["status"] != "completed":
            # GitHub may still be resolving the dispatch title and policy revision.
            return result
        if (run["id"] != run_id or run["repository"]["full_name"] != OWNER_REPO
                or run["event"] != "workflow_dispatch" or run["head_branch"] != "main"
                or run["head_sha"] != policy or run["path"] != f".github/workflows/{WORKFLOW}"
                or run["display_title"] != f"Verify {revision} against {request['contract']}"):
            raise ValueError("hosted run differs from the reserved candidate or main policy")
        deployment = f"{run_id}-{attempt}"
        artifacts = gh_json("api", f"{endpoint}/artifacts")
        available = {a["name"] for a in artifacts["artifacts"] if not a["expired"]}
        with TemporaryDirectory(dir=state) as folder:
            folder = Path(folder)
            names = {"stage": f"trusted-evidence-{deployment}", "runtime": f"trusted-compose-{deployment}",
                     "manifest": f"verified-manifest-{deployment}"}
            paths = {}
            for key, filename in (("stage", "evidence.json"), ("runtime", "runtime.json"),
                                  ("manifest", "verified-manifest.json")):
                if names[key] in available:
                    target = folder / key
                    subprocess.run(["gh", "run", "download", str(run_id), "--repo", OWNER_REPO,
                                    "--name", names[key], "--dir", str(target)], check=True, timeout=60)
                    paths[key] = target / filename
            evidence = {key: json.loads(path.read_text()) for key, path in paths.items()}
            stage, runtime = evidence.get("stage"), evidence.get("runtime")
            if stage and (stage["revision"] != revision or stage["deployment"] != deployment
                          or stage["ci"]["policy_revision"] != policy
                          or stage["contract_sha256"] != request["contract_sha256"]):
                raise ValueError("hosted HTTP evidence belongs to a different candidate or run")
            if runtime and (runtime["revision"] != revision or runtime["policy_revision"] != policy):
                raise ValueError("hosted Compose evidence belongs to a different candidate or policy")
            result["verdict"], result["reason"] = "inconclusive", "hosted_evidence_incomplete"
            if run["conclusion"] == "success" and stage and runtime and "manifest" in evidence:
                manifest = evidence["manifest"]
                contract = contract_at(repo, policy, "compose-pilot", folder)
                source_hash = sha256(git("show", f"{revision}:pilot/service.py", cwd=repo)).hexdigest()
                checked = compose_evidence(runtime, revision, policy, source_hash, contract.digest)
                expected = {"revision": revision, "policy_revision": policy, "deployment": deployment,
                            "contract_sha256": request["contract_sha256"], "runtime": checked,
                            "receipt_sha256": sha256(canonical_json(stage).encode()).hexdigest()}
                if stage["verdict"] != "verified" or any(manifest.get(k) != v for k, v in expected.items()):
                    raise ValueError("signed manifest does not bind the observed runtime and HTTP evidence")
                verify_signature(paths["manifest"], policy)
                result.update(verdict="verified", reason="signed_runtime_and_cleanup_verified")
            elif run["conclusion"] == "failure":
                failed = next((receipt for receipt in (runtime, stage)
                               if receipt and receipt["verdict"] == "failed"), None)
                if failed:
                    result.update(verdict="failed", reason=failed["reason"])
            for key, artifact in paths.items():
                # Keep original bytes for independent signature and hash verification.
                artifact.replace(state / f"{key}-{attempt}.json")
            if "runtime" in paths:
                for filename in ("final.log", "before_retry.log"):
                    log = folder / "runtime" / filename
                    observation = runtime.get(f"{filename.removesuffix('.log')}_diagnostics", {})
                    if log.is_file() and sha256(log.read_bytes()).hexdigest() == observation.get("sha256"):
                        log.replace(state / f"{attempt}-{filename}")
        record(state / "result.json", result)
        return result
