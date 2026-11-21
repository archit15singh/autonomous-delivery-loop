"""Read reviewed pilot contracts and verify evidence from the owned main workflow."""
import subprocess

from .github import OWNER_REPO
from .revisions import FULL_REVISION, git
from .verify import Contract


WORKFLOW = "trusted-candidate.yml"
CONTRACTS = ("pilot", "named-greeting")
REMOTE = f"https://github.com/{OWNER_REPO}.git"
SIGNER = f"{OWNER_REPO}/.github/workflows/{WORKFLOW}"


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


def contract_at(repo, policy, name):
    return Contract.from_bytes(git("show", f"{policy}:contracts/{name}.json", cwd=repo))
