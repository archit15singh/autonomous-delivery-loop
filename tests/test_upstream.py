import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from delivery.upstream import replay
from delivery.upstream_pr import prepare


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
                "from pathlib import Path\nfrom app import VERSION\n"
                "assert list(Path.cwd().parent.iterdir()) == [Path.cwd()]\n"
                "print(f'version={VERSION}')\n"
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

    @patch.dict("os.environ", {"GITHUB_ACTIONS": "false"})
    def test_prepare_requires_local_setup_controls_suite_and_exact_head(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            repo = root / "repo"
            repo.mkdir()

            def git(*args):
                return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()

            git("init", "--quiet")
            git("config", "user.name", "ADL Test")
            git("config", "user.email", "adl@example.invalid")
            source = repo / "app.py"
            source.write_text("raise SystemExit('bug reproduced')\n")
            git("add", "app.py")
            git("commit", "--quiet", "-m", "base")
            base = git("rev-parse", "HEAD")
            source.write_text("print('correct result')\n")
            git("commit", "--quiet", "-am", "candidate")
            head = git("rev-parse", "HEAD")
            template = root / "template.md"
            template.write_text("Fix the CLI output.")
            contract = root / "contract.json"
            evidence = "https://example.test/replay"

            def command(name, source, expected, **metadata):
                return {"name": name, "command": [sys.executable, "-c", source],
                        "contains": expected, **metadata}

            profile = {
                "live_entrypoint": "Run the CLI",
                "setup": command("Provision fixture", "from pathlib import Path; "
                                 "Path('.ready').touch(); print('setup ok')", "setup ok"),
                "controls": [
                    command("Ordinary input", "print('normal ok')", "normal ok", kind="normal"),
                    command("Empty input", "print('boundary ok')", "boundary ok", kind="boundary"),
                ],
                "exclusions": {"failure": "Input validation lives in a separate command."},
                "suite": command("Existing tests", "print('suite ok')", "suite ok"),
            }
            data = {
                "base": base, "candidate": head, "allowed_paths": ["app.py"],
                "regression_paths": [],
                "command": [sys.executable, "-c", "from pathlib import Path; "
                            "assert Path('.ready').exists(); exec(Path('app.py').read_text())"],
                "before": {"exit": 1, "contains": "bug reproduced"},
                "after": {"exit": 0, "contains": "correct result"},
            }

            def run(label):
                contract.write_text(json.dumps(data))
                return prepare(repo, contract, template, evidence, root / label)

            with self.assertRaisesRegex(ValueError, "local readiness profile"):
                run("legacy")
            data["readiness"] = profile
            with patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}):
                with self.assertRaisesRegex(ValueError, "local development environment"):
                    run("hosted")
            with self.assertRaisesRegex(ValueError, "proposed PR head"):
                data["candidate"] = base
                run("stale")
            data["candidate"] = head
            result = run("passing")
            self.assertEqual(result["verdict"], "verified")
            body = (root / "passing" / "pr.md").read_text()
            for fact in (head, base, "bug reproduced", "correct result", "Existing tests",
                         "Input validation", evidence):
                self.assertIn(fact, body)

            profile["controls"][0]["contains"] = "missing"
            result = run("failed-control")
            self.assertEqual(result["verdict"], "unverified")
            self.assertTrue((root / "failed-control" / "receipt.json").exists())
            self.assertFalse((root / "failed-control" / "pr.md").exists())
            profile["controls"][0]["contains"] = "normal ok"
            profile["suite"]["contains"] = "suite failure"
            self.assertEqual(run("failed-suite")["verdict"], "unverified")
            self.assertFalse((root / "failed-suite" / "pr.md").exists())
            profile["controls"].pop()
            with self.assertRaisesRegex(ValueError, "boundary or failure control"):
                run("no-edge-case")
