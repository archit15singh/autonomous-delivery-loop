from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from delivery.factory_resume import resume
from delivery.upstream_actions import ActionLedger


class ResumeTests(unittest.TestCase):
    def test_new_worker_recovers_existing_claim_after_head_changes(self):
        with TemporaryDirectory() as folder:
            state = Path(folder)
            (state / "factory-runs").mkdir()
            ledger = ActionLedger(state / "upstream-ci/actions.sqlite3")
            note = state / "upstream-ci/active.md"
            note.write_text("Confirm that the maintainer has accepted the change.")
            url = "https://github.com/owner/repo/pull/1"
            record = {"url": url, "head": "a" * 40, "base": "b" * 40, "state": "OPEN",
                      "action": "investigate_failure", "signals": [{"state": "failure", "name": "build"}],
                      "review": {"action": "investigate_failure"}}
            with patch("delivery.factory_resume.inspect_prs", return_value=[record]):
                first, code = resume(Path("."), state, None, url)
            self.assertEqual(code, 0)
            claim = ledger.claim(first["pending"][0]["id"])
            record["head"] = "c" * 40
            with patch("delivery.factory_resume.inspect_prs", return_value=[record]):
                fresh, code = resume(Path("."), state, None, url)
            self.assertEqual(code, 0)
            self.assertEqual(fresh["operator_note"], note.read_text())
            self.assertEqual(fresh["disposition"], "respect_existing_lease")
            self.assertEqual(fresh["active_leases"][0]["head"], "a" * 40)
            self.assertNotIn(claim["lease"], str(fresh))
            with patch("delivery.factory_resume.inspect_prs", return_value=[{"url": url, "action": "lookup_failed"}]):
                partial, code = resume(Path("."), state, None, url)
            self.assertEqual(code, 1)
            self.assertEqual(partial["pending"], [])
            self.assertTrue(partial["active_leases"])

    def test_missing_state_does_not_initialize_a_replacement_ledger(self):
        with TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "existing action ledger"):
                resume(Path("."), Path(folder), None, "https://github.com/owner/repo/pull/1")
            self.assertEqual(list(Path(folder).iterdir()), [])
