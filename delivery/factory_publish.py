"""Publish an independently attested candidate to one owned staging namespace."""
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from .candidate import FULL_REVISION, check_candidate, git
from .upstream_actions import ActionLedger
from .verify import Contract


OWNER_REPO = "archit15singh/autonomous-delivery-loop"
REMOTE = f"https://github.com/{OWNER_REPO}.git"
SIGNER = f"{OWNER_REPO}/.github/workflows/trusted-candidate.yml"


def verify_signature(path, policy):
    subprocess.run(
        ["gh", "attestation", "verify", str(path), "--repo", OWNER_REPO, "--signer-workflow",
         SIGNER, "--source-ref", "refs/heads/main", "--source-digest", policy],
        stdout=subprocess.DEVNULL, check=True, timeout=40,
    )


def remote_ref(repo, ref):
    answer = git("ls-remote", "--refs", REMOTE, ref, cwd=repo).decode().strip()
    if not answer:
        return None
    revision, remote_name = answer.split("\t")
    if remote_name != ref or not FULL_REVISION.fullmatch(revision):
        raise ValueError("unexpected GitHub ref response")
    return revision


def create_staging_ref(repo, ref, candidate):
    current = remote_ref(repo, ref)
    if current not in {None, candidate}:
        raise ValueError("staging ref already points at a different commit")
    if current is None:
        try:
            subprocess.run(["gh", "api", "--method", "POST", f"repos/{OWNER_REPO}/git/refs",
                            "-f", f"ref={ref}", "-f", f"sha={candidate}"],
                           stdout=subprocess.DEVNULL, check=True, timeout=30)
        except subprocess.SubprocessError:
            if remote_ref(repo, ref) != candidate:
                raise
    if remote_ref(repo, ref) != candidate:
        raise ValueError("staging ref has no exact remote readback")


def publish(repo, manifest, candidate, contract_name, *, apply=False, ledger=None):
    if not FULL_REVISION.fullmatch(candidate) or contract_name not in {"pilot", "named-greeting"}:
        raise ValueError("publication requires an exact pilot candidate and approved contract")
    if apply and (ledger is None or os.getenv("GITHUB_ACTIONS") != "true"
                  or os.getenv("GITHUB_REPOSITORY") != OWNER_REPO
                  or os.getenv("GITHUB_REF") != "refs/heads/main" or not os.getenv("GH_TOKEN")):
        raise ValueError("staging writes require the owned main Actions publisher and a ledger")
    policy = remote_ref(repo, "refs/heads/main")
    if policy is None:
        raise ValueError("owned main is unavailable")
    with TemporaryDirectory(prefix="adl-publish-") as scratch:
        copy = Path(scratch) / "manifest.json"
        manifest_bytes = manifest.read_bytes()
        copy.write_bytes(manifest_bytes)
        payload = json.loads(copy.read_text())
        if (payload["version"] != 1 or payload["revision"] != candidate
                or payload["policy_revision"] != policy):
            raise ValueError("manifest candidate or current main policy does not match")
        verify_signature(copy, policy)
        if payload.get("runtime", {}).get("kind") != "compose":
            raise ValueError("staging publication requires signed Compose evidence")
        contract_path = Path(scratch) / "contract.json"
        contract_path.write_bytes(git("show", f"{policy}:contracts/{contract_name}.json", cwd=repo))
        contract = Contract.read(contract_path)
        if payload["contract_sha256"] != contract.digest:
            raise ValueError("manifest does not match the approved contract")
        check_candidate(candidate, policy, contract.allowed_changes, cwd=repo)
    branch = f"refs/heads/factory/verified-{candidate}"
    current = remote_ref(repo, branch)
    if current not in {None, candidate}:
        raise ValueError("owned staging branch has an unexpected head")
    reservation = f"refs/heads/factory/intent-{candidate}"
    receipt = {"repository": OWNER_REPO, "candidate": candidate, "policy": policy, "ref": branch,
               "state": "published" if apply or current == candidate else "verified_preview"}
    if not apply:
        return receipt
    log = ActionLedger(ledger)
    entry = {"candidate": candidate, "policy": policy, "manifest": sha256(manifest_bytes).hexdigest(),
             "reservation": reservation, "branch": branch}
    receipt["reservation"] = reservation
    receipt["action_id"] = log.staging_publication(**entry, state="reserved")
    if remote_ref(repo, "refs/heads/main") != policy:
        raise ValueError("main advanced; verify the candidate again")
    create_staging_ref(repo, reservation, candidate)
    if remote_ref(repo, "refs/heads/main") != policy:
        raise ValueError("main advanced; verify the candidate again")
    create_staging_ref(repo, branch, candidate)
    log.staging_publication(**entry, state="published")
    return receipt


def merge_preview(repo, base, candidate):
    if not all(FULL_REVISION.fullmatch(sha) for sha in (base, candidate)):
        raise ValueError("merge preview requires two exact revisions")
    result = subprocess.run(["git", "merge-tree", "--write-tree", base, candidate], cwd=repo,
                            text=True, capture_output=True, check=False)
    if result.returncode not in (0, 1):
        raise ValueError(result.stderr.strip() or "Git could not calculate the merge")
    tree, *details = result.stdout.splitlines()
    if not FULL_REVISION.fullmatch(tree):
        raise ValueError("Git did not return a merge tree")
    return {"base": base, "candidate": candidate, "tree": tree if result.returncode == 0 else None,
            "verdict": "mergeable" if result.returncode == 0 else "conflicting", "details": details}
