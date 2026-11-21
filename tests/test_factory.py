import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from delivery.factory_benchmark import dataset, promotion
from delivery.factory_evidence import analysis_observation, compare_failures, self_check
from delivery.factory_publish import merge_preview
from delivery.factory_workflow import intake, workflow
from delivery.impact import ImpactPolicy


class FactoryTests(unittest.TestCase):
    def test_real_http_verifier_controls(self):
        self.assertTrue(self_check()["passed"])

    def test_failure_comparison_requires_matching_complete_baseline(self):
        failure = {"check": "Windows", "test": "compile", "signature": "STL1000"}
        baseline = {"revision": "base", "complete": True, "environment": "windows", "failures": [failure]}
        candidate = {**baseline, "revision": "head", "base": "base", "failures": [
            failure, {**failure, "signature": "incorrect status"}]}
        found = compare_failures(candidate, baseline)
        self.assertEqual([route["action"] for route in found["routes"]],
                         ["follow_upstream_dependency", "investigate_candidate"])
        self.assertEqual(compare_failures(candidate, {**baseline, "complete": False})["verdict"], "inconclusive")

    def test_resume_skips_completed_steps_and_rejects_stale_approval(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()

            def git(*args):
                return subprocess.check_output(["git", *args], cwd=repo).decode().strip()

            git("init", "--quiet")
            git("-c", "user.email=fixture@example.invalid", "-c", "user.name=Fixture",
                "commit", "--allow-empty", "--quiet", "-m", "base")
            base = git("rev-parse", "HEAD")
            git("-c", "user.email=fixture@example.invalid", "-c", "user.name=Fixture",
                "commit", "--allow-empty", "--quiet", "-m", "candidate")
            head = git("rev-parse", "HEAD")
            self.assertEqual(merge_preview(repo, base, head)["tree"], git("rev-parse", "HEAD^{tree}"))
            plan = root / "plan.json"
            plan.write_text(json.dumps({"version": 1, "revision": head, "steps": [
                {"id": "check", "kind": "command", "argv": [sys.executable, "-c", "print('Ran 1 tests')"],
                 "test_count_pattern": r"Ran (\d+) tests"},
                {"id": "operator", "kind": "approval"},
            ]}))
            state = workflow(plan, repo, root / "run", "full")
            self.assertEqual(state["status"], "waiting_for_approval")
            approval = state["approval_request"]
            self.assertEqual(workflow(plan, repo, root / "run", "full", {**approval, "revision": base})["status"],
                             "waiting_for_approval")
            verified = workflow(plan, repo, root / "run", "full", approval)
            self.assertEqual(verified["status"], "verified")
            self.assertEqual(verified["steps"]["check"]["attempt"], 1)

    def test_rollout_uses_exact_identity_and_declared_observation_window(self):
        policy = ImpactPolicy("Argo", "http", "canary", 2, 10, 1.0)
        metadata = {"uid": "run", "annotations": {"adl/revision": "sha", "adl/deployment": "deploy"}}
        measurements = [{"startedAt": "2026-01-01T00:00:00Z",
                         "finishedAt": f"2026-01-01T00:00:{end}Z", "phase": "Successful"} for end in (10, 20)]
        run = {"kind": "AnalysisRun", "metadata": metadata, "status": {"phase": "Successful",
               "metricResults": [{"name": "http", "measurements": measurements}]}}
        self.assertEqual(analysis_observation(run, policy, "sha", "deploy", uid="run")["verdict"], "verified")
        self.assertEqual(analysis_observation(run, policy, "other", "deploy", uid="run")["verdict"],
                         "inconclusive")

    def test_benchmark_pins_six_issue_cases_and_requires_replication(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(dataset(root), json.loads((root / "evals/frozen.json").read_text()))
        rows = []
        for round in ("first", "repeat"):
            for variant, seconds in (("baseline", 100), ("candidate", 75)):
                rows.append({"round": round, "case": "fixture", "variant": variant, "seconds": seconds,
                             "tokens": 100, "verified": True, "interventions": 0})
        self.assertFalse(promotion(["fixture"], rows[:2])["promote"])
        self.assertTrue(promotion(["fixture"], rows)["promote"])
        rows[-1]["verified"] = False
        self.assertFalse(promotion(["fixture"], rows)["promote"])

    def test_intake_records_duplicate_and_planning_blockers(self):
        self.assertEqual(intake({"state": "OPEN", "duplicate": True})["reason"], "existing_fix")
        self.assertEqual(intake({"state": "OPEN", "policy_checked": True})["route"], "plan")
