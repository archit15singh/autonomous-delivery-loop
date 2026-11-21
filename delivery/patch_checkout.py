"""Collect the changes a local writer made against an exact revision."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from .local_codex import require_success, run_codex
from .revisions import check_scope, git


@contextmanager
def patch_checkout(repo, revision):
    with TemporaryDirectory(prefix="adl-writer-") as folder:
        checkout = Path(folder) / "checkout"
        git("init", "--quiet", str(checkout))
        # A verified candidate can be a commit-tree object with no branch.
        git("fetch", "--quiet", "--no-tags", "--no-recurse-submodules",
            str(Path(repo).resolve()), revision, cwd=checkout)
        git("checkout", "--quiet", "--detach", revision, cwd=checkout)
        yield checkout


def collect_patch(checkout, revision, allowed):
    git("add", "-A", cwd=checkout)
    paths = git("diff", "--no-renames", "--name-only", "-z", revision, "--", cwd=checkout)
    check_scope(paths.decode().split("\0")[:-1], allowed)
    patch = git("diff", "--binary", revision, "--", cwd=checkout)
    if not patch:
        raise ValueError("Codex produced no change")
    return patch


def write_patch(repo, revision, task, allowed, *, events, model, timeout, subagents=0):
    with patch_checkout(repo, revision) as checkout:
        status = run_codex(cwd=checkout, prompt=task, model=model, timeout=timeout,
                           events=events, role="writer", subagents=subagents)
        require_success(status, timeout, events)
        return collect_patch(checkout, revision, allowed)
