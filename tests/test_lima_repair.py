from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from delivery import lima_repair


class LimaRepairTests(unittest.TestCase):
    def test_verified_failure_gets_one_repair_and_a_fresh_browser_run(self):
        failed = {"verdict": "failed", "reason": "redis_readback_mismatch", "redis_counter": "",
                  "cleanup": {"status": "confirmed"}, "observation": {"probes": []}}
        passed = {"verdict": "verified", "reason": "all_required_evidence_passed"}
        with TemporaryDirectory() as folder, \
             patch.object(lima_repair, "running_definition", return_value={"revision": "a" * 40}), \
             patch.object(lima_repair, "check_candidate"), \
             patch.object(lima_repair, "run", side_effect=[failed, passed]) as run, \
             patch.object(lima_repair, "Lima"), \
             patch.object(lima_repair, "guest_patch", return_value=b"candidate") as guest, \
             patch.object(lima_repair, "repaired_commit", return_value="b" * 40):
            state = Path(folder)
            result = lima_repair.repair(state, "a" * 40, browser=True)
            self.assertEqual(result["verdict"], "verified")
            self.assertEqual(result["repair_attempts"], 1)
            self.assertEqual(run.call_args_list[0].args, (state / "before", "a" * 40))
            self.assertEqual(run.call_args_list[1].args, (state / "after", "b" * 40))
            self.assertTrue(all(call.kwargs == {"browser": True} for call in run.call_args_list))
            self.assertIn('"redis_counter": {"expected": "2", "observed": ""}', guest.call_args.args[3])
            with self.assertRaisesRegex(ValueError, "already owns"):
                lima_repair.repair(state, "a" * 40)
            guest.assert_called_once()

    def test_uncertain_cleanup_prevents_dispatch(self):
        failed = {"verdict": "failed", "reason": "probe_failed", "cleanup": {"status": "unconfirmed"}}
        with TemporaryDirectory() as folder, \
             patch.object(lima_repair, "running_definition", return_value={"revision": "a" * 40}), \
             patch.object(lima_repair, "check_candidate"), \
             patch.object(lima_repair, "run", return_value=failed), \
             patch.object(lima_repair, "guest_patch") as guest:
            result = lima_repair.repair(Path(folder), "a" * 40)
            self.assertEqual(result["repair_attempts"], 0)
            guest.assert_not_called()
