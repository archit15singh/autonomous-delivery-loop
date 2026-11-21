"""Collect the changes a local writer made against an exact revision."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from .revisions import check_scope, git


@contextmanager
def patch_checkout(repo, revision):
    with TemporaryDirectory(prefix="adl-writer-") as folder:
        checkout = Path(folder) / "checkout"
        git("clone", "--quiet", "--no-local", str(repo), str(checkout))
        git("checkout", "--quiet", "--detach", revision, cwd=checkout)
        git("remote", "remove", "origin", cwd=checkout)
        yield checkout


def collect_patch(checkout, revision, allowed):
    git("add", "-A", cwd=checkout)
    paths = git("diff", "--no-renames", "--name-only", "-z", revision, "--", cwd=checkout)
    check_scope(paths.decode().split("\0")[:-1], allowed)
    patch = git("diff", "--binary", revision, "--", cwd=checkout)
    if not patch:
        raise ValueError("Codex produced no change")
    return patch
