import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from delivery.factory_lifecycle import github_events, read_analysis_run, revert_events


class LifecycleTests(unittest.TestCase):
    def test_deployment_success_remains_inconclusive_and_tags_report_mutability(self):
        revision = "1" * 40
        stamp = "2026-11-21T00:00:00Z"
        def github(*args):
            path = args[1]
            if path.endswith("/deployments"):
                return [{"id": 1, "sha": revision, "environment": "production", "created_at": stamp}]
            if "/statuses" in path:
                return [{"state": "success", "created_at": stamp}]
            if "/releases" in path:
                return [{"draft": False, "tag_name": "v1", "published_at": stamp, "html_url": "release"}]
            return {"sha": revision}
        with patch("delivery.factory_lifecycle.gh_json", side_effect=github):
            report = github_events("owner/repo", "production", 1)
        self.assertEqual(report["deployments"][0]["runtime_verdict"], "inconclusive")
        self.assertEqual(report["events"][0]["event"], "released")
        self.assertFalse(report["events"][0]["immutable"])

    def test_real_git_revert_is_observed(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            def git(*args):
                return subprocess.check_output(["git", "-C", root, *args], text=True).strip()
            git("init", "-q")
            git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@example.invalid")
            git("commit", "--allow-empty", "-qm", "base")
            beginning = git("rev-parse", "HEAD")
            (root / "change").write_text("new")
            git("add", "change")
            git("commit", "-qm", "change")
            change = git("rev-parse", "HEAD")
            git("revert", "--no-edit", change)
            end = git("rev-parse", "HEAD")
            self.assertEqual(revert_events(root, beginning, end)[0]["subject"], change)

    def test_analysis_live_read_is_explicit_and_uses_read_only_get(self):
        with patch("delivery.factory_lifecycle.subprocess.check_output",
                   return_value=json.dumps({"kind": "AnalysisRun"}).encode()) as command:
            with self.assertRaises(ValueError):
                read_analysis_run(None, "team", "run")
            self.assertEqual(read_analysis_run("approved", "team", "run")["kind"], "AnalysisRun")
            argv = command.call_args.args[0]
            self.assertEqual(argv[1:6], ["--context=approved", "--namespace=team",
                                         "get", "analysisruns.argoproj.io", "run"])
