import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from delivery.work_intake import rank_issues
from evals.agent_cli import run_external
from evals.run import events, permitted_diff


class EvidenceEvaluationTest(unittest.TestCase):
    def test_rank_eligibility_before_priority(self):
        common = {"state": "OPEN", "policy_checked": True, "scope_agreed": True,
                  "reproduction": "verified exact base", "acceptance": {k: "checked" for k in
                                                                       ("expected", "control", "boundary")},
                  "repository_fit": 70, "impact": 2, "effort": 1}

        def item(number, **overrides):
            return {**common, "issue": f"https://github.com/example/project/issues/{number}", **overrides}

        report = rank_issues([item(1, impact=5, duplicate=True), item(2, impact=5),
                              item(3, maintainer_requested=True), item(4, policy_checked=False)])
        self.assertTrue(report["next_issue"].endswith("/3"))
        self.assertEqual([row["reason"] for row in report["waiting_or_skipped"]],
                         ["existing_fix", "contribution_policy_unchecked"])

    def test_solver_scope_rejects_unreviewed_modes(self):
        for mode, expected in (("100644", True), ("120000", False), ("160000", False)):
            self.assertEqual(permitted_diff(f":000000 {mode} 0000000 1234567 A\0src/a.py\0", ("src/",)),
                             expected)
        self.assertFalse(permitted_diff(":000000 100644 0000000 1234567 A\0src_extra/a.py\0", ("src/",)))

    def test_external_worker_argv_and_untrusted_output(self):
        with TemporaryDirectory() as folder:
            work = Path(folder)
            launcher = work / "launcher"
            launcher.write_text(f"#!{sys.executable}\nimport json, os, sys\n"
                                "print(json.dumps({'argv': sys.argv[1:], 'seen': 'FIXTURE_SECRET' in os.environ}))\n"
                                "print('null')\n")
            launcher.chmod(0o700)
            for agent, flags in (("opencode", ("run", "--standalone")), ("claude", ("--print", "--verbose"))):
                output = work / f"{agent}.jsonl"
                with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}):
                    exit_code = run_external(agent=agent, model="test/model", launcher=launcher,
                                             prompt="- literal prompt", tree=work, events=output, timeout=5,
                                             env={"FIXTURE_SECRET": "fake"})
                row = json.loads(output.read_text().splitlines()[0])
                self.assertEqual(exit_code, 0)
                self.assertFalse(row["seen"])
                self.assertEqual((row["argv"][0], row["argv"][-1]), (agent, "- literal prompt"))
                self.assertTrue(all(flag in row["argv"] for flag in flags))
                with output.open("a") as transcript:
                    transcript.write(json.dumps({"type": "item.completed", "item": {
                        "type": "command_execution", "command": "python -m pytest",
                        "exit_code": 0, "aggregated_output": "9 passed"}}) + "\n")
                self.assertEqual(events(output, native=False), ([], "", {}))

    def test_evidence_gate_requires_complete_rounds_and_cost_coverage(self):
        from evals.summarize import ROOT, learning_report

        cases = json.loads((ROOT / "cases.json").read_text())
        rows = []
        for round_name in ("explore", "repeat"):
            for case in cases:
                for variant, seconds in (("plain", 100), ("equipped", 80)):
                    rows.append({"round": round_name, "case": case["instance_id"], "variant": variant,
                                 "coding_agent": "codex", "model": "same-model", "regression_exit": 0,
                                 "uncached_input_tokens": seconds, "stage_verified": True,
                                 "human_interventions": 0, "seconds": seconds, "cost_usd": None})
        report = learning_report(rows, "plain", "equipped")
        self.assertTrue(report["decision"]["promote"])
        self.assertEqual(report["cost"]["reason"], "billed_cost_incomplete")
        rows.append({**rows[0], "round": "incomplete"})
        report = learning_report(rows, "plain", "equipped")
        self.assertFalse(report["decision"]["promote"])
        self.assertEqual(report["incomplete_rounds"], ["incomplete"])
