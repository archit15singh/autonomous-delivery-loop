from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from delivery.upstream_actions import ActionLedger, SECOND


URL = "https://github.com/owner/project/pull/1"
HEAD, BASE, CANDIDATE, NEXT = (digit * 40 for digit in "abcd")
FAILURE = "windows:compiler"


def observation(head=HEAD, base=BASE, *, branch_update=False, state="OPEN"):
    return {"url": URL, "state": state, "head": head, "base": base, "base_branch": "main",
            "action": "investigate_failure",
            "signals": [{"name": "windows", "state": "failure", "url": "https://example.com/job/1"}],
            "review": {"action": "check_branch_update" if branch_update else "investigate_failure"}}


def remote(head=HEAD, base=BASE):
    return {"state": "OPEN", "isDraft": False, "headRefOid": head, "baseRefOid": base,
            "headRefName": "fix", "headRepository": {"nameWithOwner": "contributor/project"}}


def verified(candidate=CANDIDATE):
    return {"verdict": "verified", "candidate": candidate, "readiness": {"suite": {"passed": True}}}


class UpstreamActionTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(folder) / "actions.sqlite3"
        self.ledger = ActionLedger(self.path)
        self.now = 1000 * SECOND
        self.enterContext(patch("delivery.upstream_actions.time.time_ns", side_effect=lambda: self.now))

    def scan(self, record=None):
        self.now += SECOND
        return self.ledger.observe([record or observation()], self.now)

    def action(self):
        return self.ledger.status()["pending"][0]["id"]

    def reserve(self, action, lease, head=HEAD, candidate=CANDIDATE, failure=FAILURE):
        with patch("delivery.upstream_actions.live_pr", return_value=remote(head)):
            return self.ledger.reserve_push(action, lease, failure, verified(candidate))

    def test_repeated_scans_deduplicate_and_older_scans_cannot_restore_stale_work(self):
        self.assertEqual(self.scan()["planned"], 1)
        action = self.action()
        older = self.now
        updated = observation()
        updated["signals"][0]["url"] = "https://example.com/job/2"
        self.assertEqual(self.scan(updated)["planned"], 0)
        self.assertEqual(self.action(), action)
        self.scan(observation(CANDIDATE))
        fresh = self.action()
        self.assertNotEqual(fresh, action)
        self.assertEqual(self.ledger.observe([observation()], older)["ignored_older"], 1)
        with self.assertRaisesRegex(ValueError, "stale"):
            self.ledger.claim(action)
        self.assertEqual(self.action(), fresh)
        self.scan({"url": URL, "action": "lookup_failed"})
        self.assertEqual(self.ledger.status()["pending"], [])

    def test_one_lease_per_pr_with_concurrent_workers_and_restart_before_push(self):
        self.scan(observation(branch_update=True))
        plans = self.ledger.status()["pending"]
        self.assertEqual(len(plans), 2)

        def worker(action):
            try:
                return ActionLedger(self.path).claim(action, seconds=5)
            except ValueError as exc:
                self.assertIn("active lease", str(exc))
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, (plan["id"] for plan in plans)))
        original, = [result for result in results if result]
        self.assertEqual({plan["state"] for plan in self.ledger.status()["pending"]}, {"leased", "wait_for_lease"})
        self.scan(observation(CANDIDATE))
        with self.assertRaisesRegex(ValueError, "active lease"):
            self.ledger.claim(self.action())
        self.scan(observation(branch_update=True))
        self.now += 6 * SECOND
        resumed = ActionLedger(self.path).claim(original["id"])
        self.assertNotEqual(resumed["lease"], original["lease"])
        self.assertEqual(self.ledger.status()["repair_attempts"], [])
        with self.assertRaisesRegex(ValueError, "lease"):
            self.ledger.finish(original["id"], original["lease"])
        self.ledger.finish(original["id"], resumed["lease"])
        self.scan(observation(branch_update=True))
        self.assertEqual(len(self.ledger.status()["pending"]), 1)

    def test_rejects_stale_head_base_and_unverified_candidate_before_reservation(self):
        self.scan()
        action = self.action()
        lease = self.ledger.claim(action)["lease"]
        with self.assertRaisesRegex(ValueError, "verified upstream-prepare"):
            self.ledger.reserve_push(action, lease, FAILURE, {"candidate": CANDIDATE, "verdict": "failed"})
        for changed in (remote(NEXT), remote(base=NEXT)):
            with patch("delivery.upstream_actions.live_pr", return_value=changed):
                with self.assertRaisesRegex(ValueError, "changed"):
                    self.ledger.reserve_push(action, lease, FAILURE, verified())
        self.assertEqual(self.ledger.status()["repair_attempts"], [])

    def test_armed_crash_holds_even_after_lease_expiry_until_outcome_is_known(self):
        self.scan()
        action = self.action()
        lease = self.ledger.claim(action, seconds=1)["lease"]
        reservation = self.reserve(action, lease)
        self.assertEqual(reservation["expected_head"], HEAD)
        self.assertEqual(reservation["head_repository"], "contributor/project")
        self.now += 2 * SECOND
        reopened = ActionLedger(self.path)
        with self.assertRaisesRegex(ValueError, "unconfirmed push"):
            reopened.claim(action)
        with patch("delivery.upstream_actions.live_pr", return_value=remote()):
            self.assertEqual(reopened.reconcile(action)["state"], "unconfirmed")
            self.assertEqual(reopened.reconcile(action, confirmed_not_sent=True)["state"], "not_sent")
        self.assertEqual(reopened.status()["repair_attempts"][0]["attempts"], 1)
        self.assertIn("lease", reopened.claim(action))

    def test_scan_reconciles_recorded_candidate_after_crash_and_old_scan_cannot_confirm_it(self):
        self.scan()
        earlier_scan = self.now + 1
        action = self.action()
        self.now += SECOND
        lease = self.ledger.claim(action)["lease"]
        self.reserve(action, lease)
        lagged_result = self.ledger.observe([observation(CANDIDATE)], earlier_scan)
        self.assertEqual(lagged_result["reconciled"], 0)
        self.assertEqual(ActionLedger(self.path).status()["pending"][0]["state"], "reconcile")
        self.assertEqual(self.scan(observation(CANDIDATE))["reconciled"], 1)
        self.assertEqual(self.scan(observation(CANDIDATE))["reconciled"], 0)
        self.assertEqual(self.ledger.reconcile(action)["state"], "applied")
        self.assertEqual(self.ledger.status()["unconfirmed_pushes"], [])

    def test_budget_survives_follow_up_head_changes_and_rejects_renaming_same_signal(self):
        self.scan()
        first = self.action()
        self.reserve(first, self.ledger.claim(first)["lease"])
        self.scan(observation(CANDIDATE))
        second = self.action()
        lease = self.ledger.claim(second)["lease"]
        with self.assertRaisesRegex(ValueError, "keep it across heads"):
            self.reserve(second, lease, CANDIDATE, NEXT, "new-name")
        self.assertEqual(self.reserve(second, lease, CANDIDATE, NEXT)["attempt"], 2)
        self.scan(observation(NEXT))
        third = self.action()
        reopened = ActionLedger(self.path)
        lease = reopened.claim(third)["lease"]
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            self.reserve(third, lease, NEXT, "e" * 40)
        self.assertEqual(reopened.status()["repair_attempts"][0]["attempts"], 2)

    def test_reconcile_preserves_a_later_maintainer_head(self):
        self.scan()
        action = self.action()
        self.reserve(action, self.ledger.claim(action)["lease"])
        self.scan(observation(NEXT))
        with (patch("delivery.upstream_actions.live_pr", return_value=remote(NEXT)),
              patch("delivery.upstream_actions.is_ancestor", side_effect=[False, True]) as compare):
            self.assertEqual(self.ledger.reconcile(action)["state"], "unconfirmed")
            self.assertEqual(self.ledger.reconcile(action)["state"], "applied")
            compare.assert_called_with("contributor/project", CANDIDATE, NEXT)
        self.assertEqual(self.ledger.status()["pending"][0]["head"], NEXT)
