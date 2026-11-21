"""Describe the exact Git policy files used by a factory run."""
from hashlib import sha256
import json
from pathlib import Path

from .candidate import FULL_REVISION, git


POLICY_PATHS = ("delivery", "contracts", ".agents/skills", ".github/workflows", "verification", "evals")


def definition_digest(files):
    return sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def definition(repo, revision):
    if not FULL_REVISION.fullmatch(revision) or git("cat-file", "-t", revision, cwd=repo).strip() != b"commit":
        raise ValueError("factory definition requires an exact Git commit")
    tree = git("ls-tree", "-rz", revision, "--", *POLICY_PATHS, cwd=repo)
    files = {}
    for entry in tree.decode().split("\0"):
        if entry:
            descriptor, name = entry.split("\t", 1)
            mode, kind, digest = descriptor.split()
            files[name] = {"mode": mode, "kind": kind, "git_object": digest}
    if not files:
        raise ValueError("commit has no factory definition files")
    return {"revision": revision, "files": files, "sha256": definition_digest(files)}


def check_definition(item, revision):
    if item != definition(Path(__file__).resolve().parents[1], revision):
        raise ValueError("factory definition differs from its revision or content digest")


def running_definition(repo, expected=None):
    revision = git("rev-parse", "HEAD", cwd=repo).decode().strip()
    if (expected and revision != expected) or git(
        "status", "--porcelain", "--untracked-files=all", "--", *POLICY_PATHS, cwd=repo
    ):
        raise ValueError("run indexing requires an unchanged committed factory definition")
    return definition(repo, revision)
