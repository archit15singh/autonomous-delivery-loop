import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from delivery import factory_issue
from delivery.upstream_actions import ActionLedger


class IssueDispatchTest(unittest.TestCase):
    def test_approval_binds_spec_and_duplicate_dispatch_returns_previous_pr(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            spec, approval, ledger = [root / name for name in ("spec.json", "approval.json", "ledger.db")]
            spec.write_text(json.dumps({
                "version": 1, "outcome": "An observable outcome", "allowed_changes": ["pilot/service.py"],
                "max_repairs": 0, "probes": [{"path": "/health", "expect": {"ready": True}}],
            }))
            sha = factory_issue.Contract.read(spec).digest
            url = f"https://github.com/{factory_issue.REPOSITORY}/issues/34"
            plan = {"issue": url, "number": 34, "base": "a" * 40,
                    "snapshot_sha256": "b" * 64, "spec_sha256": sha}
            approval.write_text(json.dumps({"plan": plan, "operator": "owner"}))
            with (
                patch.object(factory_issue, "issue_plan", return_value=plan) as read_plan,
                patch.object(factory_issue, "gh_json", side_effect=[
                    {"login": "owner"}, {"permissions": {"push": True}},
                    {"login": "owner"}, {"permissions": {"push": True}},
                ]),
                patch.object(factory_issue, "running_definition", return_value={"revision": plan["base"]}),
                patch.object(factory_issue, "generate", return_value="c" * 40) as generate,
                patch.object(factory_issue, "publish", return_value="https://example.test/pr") as publish,
            ):
                def dispatch(grant):
                    return factory_issue.run_issue(root, url, spec, grant, ledger, root / "runs", "model", 50)

                self.assertEqual(dispatch(None)["state"], "waiting_for_approval")
                read_plan.return_value = {**plan, "spec_sha256": "changed"}
                self.assertEqual(dispatch(approval)["state"], "stale_approval")
                self.assertFalse(ledger.exists())
                read_plan.return_value = plan
                first = dispatch(approval)
                second = dispatch(approval)
                generate.assert_called_once()
                publish.assert_called_once()
                self.assertEqual(first["state"], "published")
                self.assertEqual(second["reservation"]["result"], first)

    def test_unfinished_reservation_cannot_be_launched_again(self):
        with TemporaryDirectory() as garden:
            path = Path(garden) / "actions.sqlite3"
            self.assertIsNone(ActionLedger(path).reserve_once("owned_issue", "issue", "identity"))
            self.assertEqual(ActionLedger(path).reserve_once("owned_issue", "issue", "new-identity"),
                             {"identity": "identity", "result": None})
