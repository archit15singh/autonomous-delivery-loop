from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from delivery.console_learning import learning
from delivery.factory_score import WEIGHTS
from delivery.upstream_actions import digest


class ConsoleLearningTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "checkout"
        self.root.mkdir()

    def save(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        return path

    def test_skips_workflow_source_changed_during_read(self):
        folder = self.root / ".github/workflows"
        folder.mkdir(parents=True)
        path = folder / "delivery.yml"
        path.write_text("name: Before\n")
        target = path.stat()
        fstat = os.fstat

        def rewrite_after_first_stat(fd):
            info = fstat(fd)
            if os.path.samestat(info, target) and info.st_mtime_ns == target.st_mtime_ns:
                path.write_text("name: During\n")
                os.utime(path, ns=(target.st_atime_ns, target.st_mtime_ns + 2_000_000_000))
            return info

        with patch("os.fstat", side_effect=rewrite_after_first_stat):
            workflows = learning(self.root)["workflows"]
        self.assertFalse(any(row.get("url") for row in workflows))
        self.assertIn("During", [row["title"] for row in learning(self.root)["workflows"]])

    def test_projects_receipts_into_display_evidence(self):
        subject = "https://github.com/example/factory/pull/14"
        score = {
            "total": 100, "delivered": 100, "provisional": 0, "subjects": 1,
            "by_milestone": {key: 100 if key == "merged" else 0 for key in WEIGHTS},
            "rows": [{"score": 100, "subject": subject, "state": "MERGED", "points": {"merged": 100},
                      "evidence": "/private/test/raw-receipt"}],
        }
        self.save(".adl/upstream-ci/score-round9.json", {**score, "total": 9})
        self.save(".adl/upstream-ci/score-round10.json", score)
        self.save(".adl/upstream-ci/score-round11.json", None)
        self.save(".adl/review-pilot/calibration-pr55.json", {
            "model": "gpt-6.2-sol", "rounds": 1, "examples": 2, "passed": True,
            "results": [
                {"expected_match": False, "judgment": {"matched": True, "reason": "private reason"}},
                {"expected_match": True, "judgment": {"matched": True}},
            ],
        })
        self.save(".adl/local-codex-pr57/exact-local-codex/usage.json", {
            "complete": False,
            "observed": {"output_tokens": 12},
            "estimated_cost_usd": 19.99, "actual_cost_usd": None,
            "threads": [{"rollout_path": "/private/test/rollout.jsonl"}],
        })
        revision = "a" * 40
        plan = self.save(".adl/factory-audit/current-plan.json", {
            "revision": revision,
            "steps": [{"id": "judge-controls", "argv": ["secret-arg"]},
                      {"id": "review", "tier": "full"}],
        })
        receipt_path = ".adl/factory-audit/fast-plan/workflow.json"
        self.save(receipt_path, {
            "identity": {"revision": revision, "tier": "fast",
                         "plan_sha256": sha256(plan.read_bytes()).hexdigest()},
            "steps": {"judge-controls": {"verdict": "verified", "log": "/private/test/log"}},
        })

        panels = learning(self.root)
        self.assertEqual(set(panels), {"improvements", "benchmarks", "agents", "judges", "usage", "workflows"})
        for rows in panels.values():
            self.assertTrue(rows)
            for row in rows:
                self.assertTrue({"title", "subtitle", "status", "details"} <= row.keys())
                self.assertIsInstance(row["details"], dict)
                self.assertTrue(row["details"]["evidence"])
        score_row, pr_row = [row for row in panels["improvements"] if row["status"] == "recorded"]
        self.assertIn("round 10", score_row["subtitle"])
        self.assertIn("Merged · 100 points", score_row["details"]["milestones"])
        self.assertEqual(pr_row["url"], subject)
        self.assertEqual(pr_row["details"]["url"], subject)
        self.assertEqual(panels["judges"][0]["status"], "failed")
        self.assertIn("False matches · 1", panels["judges"][0]["details"]["counts"])
        self.assertEqual([row["status"] for row in panels["usage"]], ["partial", "missing"])
        self.assertEqual([row["status"] for row in panels["workflows"]], ["verified", "defined"])

        rendered = json.dumps(panels, allow_nan=False)
        for private in ("private reason", "/private/test", "secret-arg", "19.99"):
            self.assertNotIn(private, rendered)

        plan.write_text(plan.read_text() + "\n")
        self.assertEqual(learning(self.root)["workflows"][0]["status"], "defined")

    def test_charts_only_complete_cohort_with_solved_outcomes_and_billed_values(self):
        cases = ["flask", "requests"]
        self.save("evals/frozen.json", {"cases": [
            {"id": case, "grader": "codex_issue_eval"} for case in cases
        ]})
        trials = [
            {"case": case, "model": "gpt-6.2-sol", "round": "repeat", "variant": "plain",
             "solved": solved, "capacity_event": False, "seconds": 20, "actual_cost_usd": cost}
            for case, solved, cost in zip(cases, (True, False), (0, 0.25))
        ]
        variants = [
            *trials,
            *[{**trial, "variant": "equipped", "actual_cost_usd": None, "estimated_cost_usd": 2}
              for trial in trials],
            {**trials[0], "variant": "equipped-feedback"},
            *[{**trials[0], "variant": "equipped-check"}] * 2,
            trials[0] | {"variant": "equipped-receipt", "actual_cost_usd": float("nan")},
        ]
        self.save("evals/results.json", {"trials": variants})
        rows = learning(self.root)["benchmarks"]
        measured = [row for row in rows if "cost" in row]
        self.assertEqual(len(measured), 1)
        self.assertEqual(measured[0]["model"], "gpt-6.2-sol")
        self.assertEqual(measured[0]["quality"], 0.5)
        self.assertEqual(measured[0]["cost"], 0.25)
        self.assertEqual(measured[0]["details"]["cost"], 0.25)
        self.assertTrue(any("Billed USD is missing" in row["details"]["evidence"] for row in rows))
        json.dumps(rows, allow_nan=False)

    def test_replay_outcomes_and_proposal_summary_exclude_raw_evidence(self):
        self.save(".adl/factory-table/merged-hosted-replays/readiness-index.json", {
            "passed": True,
            "cases": {
                "baseline": {"indexed": {"passed": True}, "ordinary": {"passed": True}},
                "candidate": {"indexed": {"passed": True, "log": "/private/log"},
                              "ordinary": {"passed": False}},
            },
        })
        guidance = "Private guidance containing /private/path"
        proposal = {"status": "proposed", "guidance": guidance, "candidate_sha256": digest(guidance),
                    "examples": 2, "disagreements": 1}
        self.save(f".adl/review-pilot/runs/{'a' * 64}/proposal.json", proposal)
        panels = learning(self.root)
        replay = next(row for row in panels["benchmarks"] if row["title"] == "Readiness indexing")
        self.assertEqual(replay["status"], "failed")
        self.assertIn("Candidate held-out control · failed", replay["details"]["checks"])
        candidate = next(row for row in panels["improvements"] if row["status"] == "proposed")
        self.assertEqual(candidate["details"]["evidence"], "Development disagreements · 1 across 2 examples.")
        self.assertNotIn("/private/", json.dumps(panels))

    def test_ignores_symlinked_artifacts_and_malformed_json(self):
        outside = self.root.parent / "outside"
        outside.mkdir()
        remote = outside / "results.json"
        remote.write_text(json.dumps({"trials": [
            {"model": "gpt-6.2-sol", "round": "repeat", "variant": "plain", "solved": True}
        ]}))
        (self.root / "evals").symlink_to(outside, target_is_directory=True)
        (self.root / ".adl").symlink_to(outside, target_is_directory=True)
        panels = learning(self.root)
        self.assertEqual(panels["usage"][0]["status"], "missing")
        self.assertTrue(all(row["status"] == "missing" for row in panels["benchmarks"]))

        (self.root / ".adl").unlink()
        target = self.save(".adl/review-pilot/calibration-pr55.json", {})
        target.unlink()
        target.symlink_to(remote)
        self.save(".adl/review-pilot/merged-experiment.json", {}).write_text("{ truncated")
        panels = learning(self.root)
        self.assertEqual(panels["judges"][0]["status"], "missing")
        self.assertEqual(panels["improvements"][0]["status"], "missing")
        self.assertNotIn(str(outside), json.dumps(panels))
        self.assertTrue(target.is_symlink())


if __name__ == "__main__":
    unittest.main()
