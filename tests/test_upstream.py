import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from delivery.upstream import replay


class UpstreamReplayTests(unittest.TestCase):
    def test_replay_requires_the_reported_failure_and_the_candidate_success(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            repo = root / "repo"
            repo.mkdir()

            def git(*args):
                return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()

            git("init", "--quiet")
            git("config", "user.name", "ADL Test")
            git("config", "user.email", "adl@example.invalid")
            (repo / "app.py").write_text("VERSION = 'old'\n")
            git("add", "app.py")
            git("commit", "--quiet", "-m", "base")
            base = git("rev-parse", "HEAD")
            (repo / "app.py").write_text("VERSION = 'new'\n")
            (repo / "regression.py").write_text(
                "from app import VERSION\nprint(f'version={VERSION}')\n"
                "raise SystemExit(VERSION != 'new')\n"
            )
            git("add", "app.py", "regression.py")
            git("commit", "--quiet", "-m", "candidate")
            candidate = git("rev-parse", "HEAD")

            contract = root / "contract.json"
            data = {
                "base": base, "candidate": candidate,
                "allowed_paths": ["app.py", "regression.py"],
                "regression_paths": ["regression.py"],
                "command": [sys.executable, "regression.py"],
                "before": {"exit": 1, "contains": "version=old"},
                "after": {"exit": 0, "contains": "version=new"},
            }
            contract.write_text(json.dumps(data))
            receipt = replay(repo, contract, root / "verified")
            self.assertEqual(receipt["verdict"], "verified")
            self.assertEqual((root / "verified" / "before.log").read_text(), "version=old\n")
            self.assertEqual((root / "verified" / "after.log").read_text(), "version=new\n")
            self.assertEqual(git("rev-parse", "HEAD"), candidate)
            self.assertEqual(git("worktree", "list", "--porcelain").count("worktree "), 1)

            data["before"]["contains"] = "a different failure"
            contract.write_text(json.dumps(data))
            receipt = replay(repo, contract, root / "unverified")
            self.assertEqual(receipt["verdict"], "unverified")
            self.assertEqual(receipt["before"]["exit"], 1)
            self.assertFalse(receipt["before"]["signal_observed"])
            self.assertTrue(receipt["after"]["passed"])
