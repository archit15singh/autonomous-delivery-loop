import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from delivery.verify import Contract, verify


class ImpactTests(unittest.TestCase):
    def setUp(self):
        self.revision = "sample-revision"
        self.deployment = "sample-deployment"
        body = {"revision": self.revision, "deployment": self.deployment}
        identity = {"status": 200, "body": body}
        self.ci = {**body, "status": "passed"}
        self.responses = [identity, {"status": 200, "body": {"ready": True}}, identity]
        self.policy = {
            "source": "synthetic-collector", "metric": "greeting_completion", "cohort": "preview",
            "minimum_samples": 100, "minimum_window_seconds": 3600, "minimum_success_rate": 0.9,
        }
        self.evidence = {
            **body, "source": "synthetic-collector", "metric": "greeting_completion", "cohort": "preview",
            "started_at": "2026-11-20T08:00:00+00:00", "ended_at": "2026-11-20T10:00:00+00:00",
            "samples": 100, "successes": 92,
        }
        with TemporaryDirectory() as folder:
            path = Path(folder) / "contract.json"
            path.write_text(json.dumps({
                "version": 1, "outcome": "Ready with enough completed requests",
                "allowed_changes": ["pilot/service.py"], "max_repairs": 2,
                "probes": [{"path": "/health", "expect": {"ready": True}}],
                "impact": self.policy,
            }))
            self.contract = Contract.read(path)

    def check(self, evidence):
        with patch("delivery.verify.fetch", side_effect=self.responses):
            return verify(self.contract, "http://loopback", self.revision,
                          self.deployment, self.ci, impact_evidence=evidence)

    def test_sufficient_observation_requires_expected_rate(self):
        good = self.check(self.evidence)
        bad = self.check({**self.evidence, "successes": 89})
        self.assertEqual(good["verdict"], "verified")
        self.assertEqual(good["impact"]["success_rate"], 0.92)
        self.assertEqual((bad["verdict"], bad["runtime_verdict"], bad["next_action"]),
                         ("failed", "verified", "escalate"))

    def test_healthy_runtime_leaves_missing_or_small_impact_inconclusive(self):
        for evidence in (None, {**self.evidence, "samples": 5, "successes": 5},
                         {**self.evidence, "ended_at": "2026-11-20T08:05:00+00:00"}):
            with self.subTest(evidence=evidence):
                report = self.check(evidence)
                self.assertEqual((report["verdict"], report["runtime_verdict"]),
                                 ("inconclusive", "verified"))

    def test_wrong_scope_and_invalid_counts_never_verify_impact(self):
        for change in ({"revision": "old"}, {"deployment": "rollout-2"}, {"cohort": "other"},
                       {"source": "other"}, {"successes": True}, {"successes": 101}):
            with self.subTest(change=change):
                self.assertEqual(self.check({**self.evidence, **change})["verdict"], "inconclusive")


if __name__ == "__main__":
    unittest.main()
