from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from delivery import browser_proof
from delivery.upstream_ci import attach_local_replay
from delivery.factory_evidence import portfolio
from delivery.factory_learning import assess_process, indexed_runs, measure, mine, pr_evidence, run_record
from delivery.factory_benchmark import cost_route


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
            paired = pr_evidence(indexed_runs(workspace))
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
            self.assertTrue(browser_proof.capture(path, head=head, base=base).passed)
            with self.assertRaisesRegex(ValueError, "another baseline"):
                browser_proof.capture(path, head=head, base=head)
            # Indexing and publishing must use the same validated revision pair.
            request = {"id": "ui-replay", "head": head, "base": "3" * 40,
                       "factory_revision": head, "pr": "https://github.com/Owner/Repo/pull/1",
                       "finished_at": "2026-11-21T00:00:00+00:00",
                       "receipts": {"browser": path.name, "readiness": "readiness.json"}}
            spec = root / "spec.json"
            spec.write_text(json.dumps(request))
            with self.assertRaisesRegex(ValueError, "another baseline"):
                run_record(spec, root / "index")
            self.assertFalse((root / "index" / "ui-replay.json").exists())
            (root / "readiness.json").write_text(json.dumps(
                {"verdict": "verified", "candidate": head, "base": base}))
            spec.write_text(json.dumps({**request, "base": base}))
            run = run_record(spec, root / "index")
            self.assertEqual(run["provenance"]["browser_base"], base)
            row = {"url": request["pr"], "base": base, "head": head, "state": "OPEN"}
            attach_local_replay([row], [run])
            self.assertEqual(row["local_replay"]["status"], "verified")
            attach_local_replay([row], [{**run, "provenance": {}}])
            self.assertEqual(row["local_replay"]["status"], "unverified")
            proof = browser_proof.capture(path, base=base, head=head)
            self.assertEqual(proof.receipt_reference, run["receipts"]["browser"])
            (root / "before-primary.png").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                browser_proof.capture(path, head=head, base=base)
            path.unlink()
            archive = root / "archived"
            proof.archive(archive)
            self.assertEqual(json.loads((archive / path.name).read_bytes()), result)
            self.assertEqual((archive / "before-primary.png").read_bytes(), b"before-primary.png")



    def test_cost_routing_requires_verified_paid_trials_in_two_rounds(self):
        rows = []
        for name in ("one", "two"):
            for variant, cost in (("baseline", 2.0), ("candidate", 1.5)):
                rows.append({"round": name, "case": "sample", "variant": variant, "verified": True,
                             "seconds": 20, "tokens": 100, "interventions": 0, "cost_usd": cost})
        self.assertEqual(cost_route(["sample"], rows)["recommendation"], "candidate")
        self.assertEqual(cost_route(["sample"], rows[:2])["reason"], "needs_two_paired_rounds")
        rows[-1].pop("cost_usd")
        self.assertEqual(cost_route(["sample"], rows)["reason"], "billed_cost_incomplete")
        rows[-1]["verified"] = False
        self.assertEqual(cost_route(["sample"], rows)["reason"], "verification_incomplete")

    def test_measure_deduplicates_verified_outcomes_and_preserves_unknown_cost(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            prototype = {"factory_revision": "a" * 40, "head": "b" * 40, "pr": None}
            for index, (verdict, seconds) in enumerate((("verified", 10), ("verified", 20), ("failed", 30))):
                (root / f"{index}.json").write_text(json.dumps({**prototype, "id": str(index),
                    "metrics": {"wall_seconds":seconds}, "outcome":{"readiness":verdict}}))
            result = measure(root)["cohorts"][0]
            self.assertEqual(result["verified_changes"], 1)
            self.assertEqual(result["metrics"]["wall_seconds"]["per_verified_change"], 60)
            self.assertIsNone(result["metrics"]["cost_usd"]["per_verified_change"])


    def test_process_assessment_does_not_infer_missing_evidence(self):
        known = assess_process({"head": "a" * 40, "evidence": "reviewed trace",
                                "skills": {"complete": True, "required": ["review"], "loaded": []},
                                "retries": {"complete": True, "repeated_without_change": 1}})
        result = {key: value["state"] for key, value in known["dimensions"].items()}
        self.assertEqual(result, {"skill_adherence": "failed", "retry_efficiency": "failed",
                                  "test_redundancy": "unknown"})
