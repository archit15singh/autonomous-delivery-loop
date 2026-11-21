from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from delivery import factory_feedback as feedback
from delivery.upstream_actions import digest


class FeedbackTest(unittest.TestCase):
    def test_failure_creates_one_issue_and_health_creates_none(self):
        with TemporaryDirectory() as folder:
            ledger = Path(folder) / "ledger.sqlite3"
            observation = {
                "environment": "hosted-staging", "deployment": "100-1", "revision": "a" * 40,
                "url": "https://github.com/example/example/actions/runs/100",
                "receipt": {"verdict": "failed", "reason": "probe_failed",
                            "probes": [{"path": "/greet", "passed": False}]},
            }
            with patch.object(feedback.subprocess, "check_output", return_value="https://example.test/issue") as create:
                self.assertEqual(feedback.signal(observation, ledger)["state"], "would_file_investigation")
                self.assertEqual(feedback.signal(observation, ledger, True)["state"], "filed_investigation")
                self.assertEqual(feedback.signal(observation, ledger, True)["state"], "already_observed")
                healthy = {**observation, "receipt": {"verdict": "verified"}}
                self.assertEqual(feedback.signal(healthy, ledger, True)["state"], "no_actionable_signal")
                create.assert_called_once()

    def test_review_replay_requires_removal_and_retains_valid_finding(self):
        with TemporaryDirectory() as folder:
            old = Path(folder) / "old.md"
            old.write_text("Review policy")
            new = Path(folder) / "new.md"
            new.write_text("Revised review policy")
            subject = {"pr": "original", "head": "a" * 40, "base": "b" * 40}
            rejected = {"key": "false-positive", "path": "pilot/service.py", "finding": "An inaccurate claim"}
            valid = {"key": "valid-finding", "path": "pilot/service.py", "finding": "An actual regression"}
            original = {**subject, "findings": [rejected], "skill": digest(old.read_text())}
            correction = {**subject, "key": rejected["key"], "finding_sha256": digest(rejected),
                          "report_sha256": digest(original), "operator": "maintainer"}
            control = {**subject, "head": "c" * 40, "key": valid["key"], "path": valid["path"]}
            for after, passed in (([valid], True), ([], False)):
                with patch.object(feedback, "review", side_effect=[original, {"findings": []},
                                                               {"findings": [valid]}, {"findings": after}]):
                    result = feedback.review_replay(Path(folder), correction, original, control,
                                                    old, new, "model", 30)
                    self.assertIs(result["passed"], passed)
