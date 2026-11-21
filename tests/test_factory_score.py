from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from delivery.factory_score import score

HEAD = "1" * 40
BASE = "2" * 40
PR = "https://github.com/owner/repo/pull/1"


def observation():
    return {"url": PR, "state": "OPEN", "head": HEAD, "base": BASE, "draft": False,
            "signals": [{"state": "success"}], "action": "checks_passed",
            "local_replay": {"status": "verified", "base": BASE, "head": HEAD},
            "review": {"decision": "APPROVED", "action": "await_maintainer_merge",
                       "reviews": [{"state": "APPROVED", "association": "MEMBER",
                                    "participant": "human", "head": HEAD}]}}


class FactoryScoreTests(unittest.TestCase):
    def test_success_and_merge_settlement(self):
        row = observation()
        self.assertEqual(score([row, row])["total"], 60)
        self.assertEqual(score([row])["work_queue"], [])
        row.update(state="MERGED", merged_at="2026-11-22T00:00:00Z", merge_commit=HEAD)
        self.assertEqual(score([row])["delivered"], 100)
        self.assertEqual(score([row])["provisional"], 0)
        row["state"] = "CLOSED"
        self.assertEqual(score([row])["total"], 0)

    def test_stale_or_unconfirmed_milestones(self):
        row = observation()
        row["local_replay"]["base"] = HEAD
        row["signals"].append({"state": "action_required"})
        row["review"]["reviews"][0]["head"] = BASE
        self.assertEqual(score([row])["total"], 0)
        with self.assertRaisesRegex(ValueError, "conflicting"):
            score([row, {**row, "state": "CLOSED"}])

    def test_candidate_reproduction_and_promotion_do_not_stack(self):
        with TemporaryDirectory() as root:
            folder = Path(root)
            (folder / "probe.log").write_bytes(b"observed")
            check = {"passed": True, "expected_exit": 0, "exit": 0, "log": "probe.log",
                     "signal": "observed", "log_sha256": sha256(b"observed").hexdigest()}
            receipt = {"base": BASE, "candidate": HEAD, "verdict": "verified",
                       "before": {**check, "expected_exit": 7, "exit": 7}, "after": check,
                       "readiness": {"suite": check, "setup": dict.fromkeys(("baseline", "candidate"), check),
                                     "controls": dict.fromkeys(("baseline", "candidate"), [check])}}
            path = folder / "receipt.json"
            path.write_text(json.dumps(receipt))
            candidate = ("https://github.com/owner/repo/issues/1", path)
            self.assertEqual(score([], [candidate, candidate])["total"], 30)
            self.assertEqual(score([observation()], [candidate])["total"], 60)
            receipt["verdict"] = "failed"
            path.write_text(json.dumps(receipt))
            self.assertEqual(score([], [candidate])["total"], 10)
            (folder / "probe.log").write_bytes(b"edited")
            with self.assertRaisesRegex(ValueError, "changed"):
                score([], [candidate])
