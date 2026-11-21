"""Inspect exact Git revisions, enforce candidate scope and manage detached checkouts."""
from contextlib import contextmanager
import re
import subprocess


FULL_REVISION = re.compile(r"[0-9a-f]{40}")


def git(*args, cwd=None):
    return subprocess.check_output(["git", *args], cwd=cwd)


def check_scope(changed, allowed):
    outside = sorted(set(changed) - set(allowed))
    if outside:
        raise ValueError("Candidate changed protected paths: " + ", ".join(outside))


def paths_between(base, candidate, *, cwd=None):
    return git("diff", "--no-renames", "--name-only", "-z", base, candidate, "--", cwd=cwd).decode().split("\0")[:-1]


def check_candidate(head, base, allowed, *, cwd=None):
    if not FULL_REVISION.fullmatch(head) or not FULL_REVISION.fullmatch(base):
        raise ValueError("trusted and candidate revisions must be full Git SHAs")
    git("merge-base", "--is-ancestor", base, head, cwd=cwd)
    check_scope(paths_between(base, head, cwd=cwd), allowed)


@contextmanager
def checkout(repo, folder, base):
    git("worktree", "add", "--detach", str(folder), base, cwd=repo)
    try:
        yield folder
    finally:
        git("worktree", "remove", "--force", str(folder), cwd=repo)
