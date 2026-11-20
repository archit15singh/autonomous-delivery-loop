import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from delivery.verify import Contract, verify
from pilot.service import routes

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "contracts/pilot.json"
IDENTITY = {"status": 200, "body": {"revision": "revision", "deployment": "deploy"}}
CI = {"status": "passed", **IDENTITY["body"]}


class OutcomeTests(unittest.TestCase):
    def setUp(self):
        self.contract = Contract.read(CONTRACT_PATH)

    def verdict(self, responses, ci=CI, repairs=0):
        with patch("delivery.verify.fetch", side_effect=responses):
            return verify(self.contract, "http://local", "revision", "deploy", ci, repairs)

    def probes(self):
        return [{"status": 200, "body": check.expect} for check in self.contract.probes]

    def test_probe_must_return_exact_json_types(self):
        checks = self.probes()
        checks[0]["body"] = {"ready": 1}
        report = self.verdict([IDENTITY, *checks, IDENTITY])
        self.assertEqual((report["verdict"], report["next_action"]), ("failed", "repair"))

    def test_all_gates_pass(self):
        report = self.verdict([IDENTITY, *self.probes(), IDENTITY])
        self.assertEqual(report["verdict"], "verified")

    def test_revision_and_deployment_both_must_match(self):
        for altered in ({"revision": "different"}, {"deployment": "previous run"}):
            with self.subTest(altered=altered):
                bad = {"status": 200, "body": {**IDENTITY["body"], **altered}}
                report = self.verdict([bad])
                self.assertEqual(report["reason"], "wrong_deployment")

    def test_rollout_changes_mid_probe(self):
        report = self.verdict([IDENTITY, *self.probes(), {"status": 503}])
        self.assertEqual(report["reason"], "deployment_changed")

    def test_unavailable_runtime_and_stale_ci_are_inconclusive(self):
        self.assertEqual(self.verdict([{"error": "down"}])["verdict"], "inconclusive")
        self.assertEqual(self.verdict([], ci={**CI, "revision": "old"})["reason"],
                         "missing_or_stale_ci")

    def test_repair_budget_and_escalation(self):
        for attempts, action in ((0, "repair"), (2, "escalate")):
            report = self.verdict([], ci={**CI, "status": "failed"}, repairs=attempts)
            self.assertEqual(report["next_action"], action)

    def test_contract_rejects_non_local_probe(self):
        data = json.loads(CONTRACT_PATH.read_text())
        data["probes"][0]["path"] = "//example.org/health"
        with TemporaryDirectory() as folder:
            path = Path(folder) / "contract.json"
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                Contract.read(path)

    def test_greeting_baseline(self):
        self.assertEqual(routes("/health"), (200, {"ready": True}))
        self.assertEqual(routes("/greet"), (200, {"message": "Hello, world!"}))
        self.assertEqual(routes("/missing")[0], 404)


if __name__ == "__main__":
    unittest.main()
