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
                patch.object(factory_issue.sys, "platform", "darwin"),
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

    def test_subagent_opt_in_is_bound_to_the_reviewed_plan(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            spec, approval = root / "spec.json", root / "approval.json"
            spec.write_text(json.dumps({
                "version": 1, "outcome": "Return health", "allowed_changes": ["pilot/service.py"],
                "max_repairs": 0, "probes": [{"path": "/health", "expect": {"ready": True}}],
                "reproduction": "Request health", "reproduction_path": "/health",
            }))
            url = f"https://github.com/{factory_issue.REPOSITORY}/issues/34"
            issue = {"id": 34, "title": "Health", "body": "", "updated_at": "today",
                     "labels": [{"name": factory_issue.LABEL}]}
            base = {"object": {"sha": "a" * 40}}
            with (
                patch.object(factory_issue, "check_issue", return_value={"route": "implement"}),
                patch.object(factory_issue, "gh_json", side_effect=[issue, base] * 3),
            ):
                original = factory_issue.issue_plan(url, spec)
                opted_in = factory_issue.issue_plan(url, spec, 2)
                self.assertNotIn("subagents", original)
                self.assertEqual(opted_in, {**original, "subagents": 2})
                approval.write_text(json.dumps({"plan": opted_in, "operator": "owner"}))
                result = factory_issue.run_issue(root, url, spec, approval, root / "ledger",
                                                 root / "runs", "model", 50)
                self.assertEqual(result["state"], "stale_approval")

    def test_unfinished_reservation_cannot_be_launched_again(self):
        with TemporaryDirectory() as garden:
            path = Path(garden) / "actions.sqlite3"
            self.assertIsNone(ActionLedger(path).reserve_once("owned_issue", "issue", "identity"))
            self.assertEqual(ActionLedger(path).reserve_once("owned_issue", "issue", "new-identity"),
                             {"identity": "identity", "result": None})


class GenerationRecoveryTest(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.spec = root / "spec.json"
        self.spec.write_text(json.dumps({
            "version": 1, "outcome": "Return the expected greeting", "allowed_changes": ["pilot/service.py"],
            "max_repairs": 0, "probes": [{"path": "/hello", "expect": {"ok": True}}],
        }))
        self.issue = f"https://github.com/{factory_issue.REPOSITORY}/issues/34"
        self.plan = {"issue": self.issue, "number": 34, "base": "a" * 40,
                     "snapshot_sha256": "b" * 64, "spec_sha256": factory_issue.Contract.read(self.spec).digest}
        self.root, self.ledger, self.receipts = root, root / "actions.db", root / "runs"
        self.approval = root / "approval.json"
        self.approve()
        self.enterContext(patch.object(factory_issue, "issue_plan", side_effect=lambda *_: self.plan.copy()))
        self.enterContext(patch.object(factory_issue, "gh_json", side_effect=lambda *args:
            {"login": "owner"} if args[-1] == "user" else {"permissions": {"push": True}}))
        self.enterContext(patch.object(factory_issue.sys, "platform", "darwin"))
        self.enterContext(patch.object(factory_issue, "running_definition",
                                             side_effect=lambda *_: {"revision": self.plan["base"]}))
        self.generate = self.enterContext(patch.object(factory_issue, "generate", return_value="c" * 40))
        self.publish = self.enterContext(patch.object(factory_issue, "publish", return_value="draft"))

    def approve(self):
        self.approval.write_text(json.dumps({"plan": self.plan, "operator": "owner"}))

    def run_issue(self, retry=None, receipts=None):
        return factory_issue.run_issue(self.root, self.issue, self.spec, self.approval, self.ledger,
                                       receipts or self.receipts, "model", 50, retry_generation=retry)

    def test_process_death_preserves_attempt_and_requires_an_explicit_current_retry(self):
        import subprocess
        import sys
        # Use a new interpreter so os._exit exercises SQLite durability and OS lock release.
        code = """
from pathlib import Path
from unittest.mock import patch
import json, os, sys
from delivery import factory_issue as f
root = Path(sys.argv[1])
grant = json.loads((root / 'approval.json').read_text())
def die(repo, folder, *args):
    (folder / 'codex.jsonl').write_text('partial trace')
    os._exit(73)
with patch.object(f, 'issue_plan', return_value=grant['plan']), patch.object(f.sys,'platform','darwin'), \\
     patch.object(f, 'gh_json', side_effect=[{'login':'owner'}, {'permissions':{'push':True}}]), \\
     patch.object(f, 'running_definition', return_value={'revision':grant['plan']['base']}), \\
     patch.object(f,'generate',side_effect=die):
    f.run_issue(root, grant['plan']['issue'],root/'spec.json',root/'approval.json',
                root/'actions.db',root/'runs','model',50)
"""
        result = subprocess.run([sys.executable, "-B", "-c", code, str(self.root)],
                                cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(result.returncode, 73)
        interrupted = self.run_issue()
        self.assertEqual((interrupted["state"], interrupted["attempt"]), ("generation_interrupted", 1))
        with self.assertRaisesRegex(ValueError, "original receipts"):
            self.run_issue(1, self.root / "other")
        self.plan = {**self.plan, "base": "d" * 40}
        self.assertEqual(self.run_issue(1)["state"], "stale_approval")
        self.approve()
        self.assertEqual(self.run_issue(42)["state"], "generation_interrupted")
        self.generate.assert_not_called()
        recovered = self.run_issue(1)
        self.assertEqual((recovered["state"], recovered["generation_attempt"]), ("published", 2))
        self.assertEqual((Path(interrupted["receipts"]) / "codex.jsonl").read_text(), "partial trace")
        self.assertEqual(self.generate.call_args.args[1].name, "attempt-2")
        self.assertEqual(self.run_issue(1)["state"], "already_dispatched")
        self.generate.assert_called_once()
        self.publish.assert_called_once()

    def test_lost_publication_response_reuses_verified_candidate_even_with_retry_flag(self):
        self.publish.side_effect = [OSError("reply lost"), "draft"]
        with self.assertRaisesRegex(OSError, "reply lost"):
            self.run_issue()
        self.plan = {**self.plan, "base": "d" * 40}
        self.approve()
        self.assertEqual(self.run_issue(1)["state"], "reconciliation_required")
        self.plan = {**self.plan, "base": "a" * 40}
        self.approve()
        self.assertEqual(self.run_issue(1)["head"], "c" * 40)
        self.generate.assert_called_once()
        self.assertEqual(self.publish.call_args_list[0], self.publish.call_args_list[1])

    def test_two_retries_of_same_attempt_launch_only_one_new_worker(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        self.generate.side_effect = ValueError("baseline unavailable")
        with self.assertRaises(ValueError):
            self.run_issue()
        started, release = Event(), Event()

        def fail_again(*args):
            started.set()
            self.assertTrue(release.wait(3))
            raise ValueError("second failure")

        self.generate.side_effect = fail_again
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.run_issue, 1)
            self.assertTrue(started.wait(3))
            second = pool.submit(self.run_issue, 1)
            release.set()
            with self.assertRaisesRegex(ValueError, "second failure"):
                first.result()
            self.assertEqual(second.result()["attempt"], 2)
        self.assertEqual(self.generate.call_count, 2)
        self.publish.assert_not_called()

    def test_legacy_recovery_checks_original_evidence_and_remote_branch(self):
        key = factory_issue.digest(self.plan)
        ActionLedger(self.ledger).reserve_once("owned_issue", self.issue, key)
        self.assertEqual(self.run_issue(1)["reason"], "original_receipts_missing")
        folder = self.receipts / key
        with factory_issue.lock(folder):
            pass
        self.assertEqual(self.run_issue(1)["reason"], "legacy_approval_missing")
        (folder / "approval.json").write_bytes(self.approval.read_bytes())
        with patch.object(factory_issue, "git", side_effect=[b"existing branch", b""]):
            self.assertEqual(self.run_issue(1)["reason"], "existing_issue_branch")
            self.assertEqual(self.run_issue(1)["generation_attempt"], 2)
        self.generate.assert_called_once()

    def test_legacy_verified_checkpoint_skips_generation_and_retry(self):
        key = factory_issue.digest(self.plan)
        ActionLedger(self.ledger).reserve_once("owned_issue", self.issue, key)
        folder = self.receipts / key
        with factory_issue.lock(folder):
            factory_issue.record(folder / "verified-head.json", {"candidate": "d" * 40})

        published = self.run_issue()
        self.assertEqual((published["state"], published["generation_attempt"]), ("published", 1))
        self.assertEqual(published["head"], "d" * 40)
        self.generate.assert_not_called()
        self.publish.assert_called_once_with(self.root, folder.resolve(), self.plan, "d" * 40)

    def test_retry_restores_published_receipt_and_index_after_indexing_failure(self):
        index = self.root / "index"

        def dispatch():
            return factory_issue.run_issue(self.root, self.issue, self.spec, self.approval,
                                           self.ledger, self.receipts, "model", 50, index)

        with patch.object(factory_issue, "index_publication", side_effect=[OSError("offline"), None]) as store:
            with self.assertRaisesRegex(OSError, "offline"):
                dispatch()
            folder = self.receipts / factory_issue.digest(self.plan)
            publication = folder / "publication.json"
            publication.unlink()
            duplicate = dispatch()
            self.assertEqual(duplicate["state"], "already_dispatched")
            result = duplicate["reservation"]["result"]
            self.assertEqual(json.loads(publication.read_text()), result)
            self.assertEqual(store.call_count, 2)
            store.assert_called_with(self.root, folder.resolve(), result, index)
        self.generate.assert_called_once()
        self.publish.assert_called_once()
