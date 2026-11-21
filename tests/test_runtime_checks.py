import unittest
from unittest.mock import Mock

from delivery.runtime_checks import assess_cleanup, assess_observation


class RuntimeChecksTests(unittest.TestCase):
    def test_product_failure_skips_stateful_readback(self):
        read_counter = Mock()
        observation = {"verdict": "failed", "reason": "probe_failed"}
        receipt = {}
        assess_observation(receipt, observation, read_counter)
        read_counter.assert_not_called()
        self.assertEqual(receipt, {"observation": observation, **observation})

    def test_unconfirmed_cleanup_takes_precedence_and_keeps_the_evidence(self):
        receipt = {}
        observation = {"verdict": "verified", "reason": "all_required_evidence_passed"}
        assess_observation(receipt, observation, lambda: "1")
        self.assertEqual(receipt["reason"], "redis_readback_mismatch")
        cleanup = {"status": "unconfirmed", "error": "engine unavailable"}
        assess_cleanup(receipt, cleanup)
        self.assertEqual(receipt, {
            "observation": observation, "redis_counter": "1", "cleanup": cleanup,
            "verdict": "inconclusive", "reason": "cleanup_unconfirmed",
        })
