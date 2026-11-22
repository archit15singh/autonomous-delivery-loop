from pathlib import Path
import unittest

from delivery.candidate import repair_context
from delivery.revisions import check_scope
from delivery.verify import Contract

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "contracts/named-greeting.json"


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.contract = Contract.read(CONTRACT_PATH)
        self.receipt = {"verdict": "failed", "reason": "probe_failed", "revision": "current",
                        "repairs_used": 0, "probes": [], "contract_sha256": self.contract.digest}

    def test_scope(self):
        check_scope(["pilot/service.py"], self.contract.allowed_changes)
        with self.assertRaises(ValueError):
            check_scope([".github/workflows/trusted-candidate.yml"], self.contract.allowed_changes)

    def test_only_matching_actionable_evidence_authorizes_repair(self):
        self.assertEqual(repair_context(self.contract, "current", self.receipt)[1], 1)
        for invalid in ({"revision": "old"}, {"repairs_used": 2},
                        {"contract_sha256": "other"}, {"verdict": "inconclusive"}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                repair_context(self.contract, "current", {**self.receipt, **invalid})


if __name__ == "__main__":
    unittest.main()
