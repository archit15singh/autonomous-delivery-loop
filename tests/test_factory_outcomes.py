import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import subprocess

from delivery.factory_definition import check_definition, definition
from delivery.factory_outcomes import outcome_report


class OutcomeTests(unittest.TestCase):
    def test_definition_verifies_the_committed_policy_instead_of_local_file_state(self):
        repo = Path(__file__).resolve().parents[1]
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
        current = definition(repo, head)
        self.assertIn(".agents/skills/deliver-outcome/SKILL.md", current["files"])
        self.assertIn("contracts/pilot.json", current["files"])
        check_definition(current, head)
        with self.assertRaisesRegex(ValueError, "definition differs"):
            check_definition({**current, "files": {}}, head)

    def test_upstream_and_owned_outcomes_require_different_exact_evidence(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            change = "a" * 40
            stale = "b" * 40
            pr = "https://github.com/upstream/project/pull/1"
            run = {"pr": pr, "head": stale, "metrics": {"wall_seconds": 10},
                   "outcome": {"readiness": "verified"}}
            (root / "old.json").write_text(json.dumps(run))
            created, started, ended = [f"2026-11-21T00:00:{i:02d}+00:00" for i in (0, 1, 2)]
            prs = [{"url": pr, "head": change, "state": "MERGED", "merge_commit": "c" * 40, "merged_at": created}]
            lifecycle = {"repository": "owner/factory", "environment": "staging", "deployments": [
                {"id": "deploy-1", "revision": change, "created_at": created, "reported_state": "success"}]}
            observation = {"deployment": "deploy-1", "revision": change, "started_at": started,
                           "ended_at": ended, "verdict": "verified", "reason": "impact_threshold_passed"}
            result = outcome_report(root, prs, lifecycle, [observation], "production")
            self.assertEqual(result["upstream"]["verified_merges"], 0)
            self.assertEqual(result["owned_production"]["deployments"], [])
            (root / "new.json").write_text(json.dumps({**run, "head": change, "metrics": {}}))
            lifecycle["environment"] = "production"
            result = outcome_report(root, prs, lifecycle, [{**observation, "deployment": "other"}], "production")
            self.assertEqual(result["upstream"]["verified_merges"], 1)
            self.assertIsNone(result["upstream"]["changes"][0]["metrics"]["wall_seconds"]["total"])
            self.assertEqual(result["owned_production"]["verdicts"], {"inconclusive": 1})
            result = outcome_report(root, prs, lifecycle, [observation], "production")
            self.assertEqual(result["owned_production"]["verdicts"], {"verified": 1})
