"""Publish an independently attested candidate to one owned staging namespace."""
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from .candidate import FULL_REVISION, check_candidate, git
from .verify import Contract


OWNER_REPO = "archit15singh/autonomous-delivery-loop"
REMOTE = f"git@github.com:{OWNER_REPO}.git"
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


def publish(repo, manifest, candidate, contract_name, *, apply=False):
    if not FULL_REVISION.fullmatch(candidate) or contract_name not in {"pilot", "named-greeting"}:
        raise ValueError("publication requires an exact pilot candidate and approved contract")
    policy = remote_ref(repo, "refs/heads/main")
    if policy is None:
        raise ValueError("owned main is unavailable")
    with TemporaryDirectory(prefix="adl-publish-") as scratch:
        copy = Path(scratch) / "manifest.json"
        copy.write_bytes(manifest.read_bytes())
        payload = json.loads(copy.read_text())
        if (payload["version"] != 1 or payload["revision"] != candidate
                or payload["policy_revision"] != policy):
            raise ValueError("manifest candidate or current main policy does not match")
        verify_signature(copy, policy)
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
    if apply and current is None:
        if remote_ref(repo, "refs/heads/main") != policy:
            raise ValueError("main advanced; verify the candidate again")
        try:
            git("push", f"--force-with-lease={branch}:", REMOTE, f"{candidate}:{branch}", cwd=repo)
        except subprocess.CalledProcessError:
            if remote_ref(repo, branch) != candidate:
                raise
    if apply and remote_ref(repo, branch) != candidate:
        raise ValueError("publication has no matching remote readback")
    return {"repository": OWNER_REPO, "candidate": candidate, "policy": policy, "ref": branch,
            "state": "published" if apply or current == candidate else "verified_preview"}


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
