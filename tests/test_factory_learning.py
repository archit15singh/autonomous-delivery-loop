from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from delivery.factory_evidence import browser_evidence, portfolio
from delivery.factory_learning import mine, pr_evidence, run_record


class LearningTests(unittest.TestCase):
    def test_index_filters_stale_evidence_and_groups_distinct_factory_failures(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            head, factory = "1" * 40, "2" * 40
            pr = "https://github.com/owner/repo/pull/1"
            workspace = root / "runs"
            workflow = root / "workflow.json"
            spec = root / "spec.json"
            request = {"head": head, "factory_revision": factory, "pr": pr,
                       "finished_at": "2026-11-21T00:00:00+00:00", "receipts": {"workflow": workflow.name}}
            first = {"identity": {"revision": head}, "status": "failed",
                     "steps": {"one": {"state": "failed", "reason": "revision_changed"},
                               "two": {"state": "failed", "reason": "revision_changed"},
                               "three": {"state": "inconclusive", "reason": "runner_unavailable"}}}
            workflow.write_text(json.dumps(first))
            for run_id in ("original", "reproduction"):
                spec.write_text(json.dumps({**request, "id": run_id}))
                self.assertEqual(run_record(spec, workspace), run_record(spec, workspace))
                if run_id == "original":
                    self.assertEqual(mine(workspace)["proposals"], [])
            report = mine(workspace)
            self.assertEqual([row["reason"] for row in report["proposals"]], ["revision_changed"])
            paired = pr_evidence(workspace)
            snapshots = [{"url": pr, "head": head, "action": "checks_passed"},
                         {"url": pr, "head": factory, "action": "wait_for_ci"}]
            view = portfolio(snapshots, {}, paired)["prs"]
            self.assertEqual(len(view[0]["evidence"]["runs"]), 2)
            self.assertIsNone(view[1]["evidence"])
            workflow.write_text(json.dumps({**first, "identity": {"revision": factory}}))
            with self.assertRaisesRegex(ValueError, "another revision"):
                run_record(spec, workspace)

    def test_browser_binds_baseline_candidate_and_screenshot_bytes(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            base, head = "1" * 40, "2" * 40
            result = {"before": base, "after": head, "passed": True, "outcomes": {}}
            for phase in ("before", "after"):
                result["outcomes"][phase] = {}
                for scenario in ("primary", "control"):
                    name = f"{phase}-{scenario}.png"
                    (root / name).write_bytes(name.encode())
                    result["outcomes"][phase][scenario] = {"screenshot": name, "errors": [],
                        "observed": "correct", "expected": "correct",
                        "sha256": sha256(name.encode()).hexdigest(), "passed": True}
            path = root / "browser.json"
            path.write_text(json.dumps(result))
            self.assertTrue(browser_evidence(path, head, base)[0])
            with self.assertRaisesRegex(ValueError, "another baseline"):
                browser_evidence(path, head, head)
            (root / "before-primary.png").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                browser_evidence(path, head, base)
