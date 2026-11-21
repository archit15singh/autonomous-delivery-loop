import copy
from contextlib import chdir
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from textwrap import dedent
from unittest.mock import patch

from delivery import review_experiment as experiment
from delivery.upstream_actions import digest


class ReviewExperimentTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.real_compare = experiment.review_judge._compare
        judge = patch.object(experiment.review_judge, "_compare",
                             return_value={"matched": True, "reason": "Same failing behavior."})
        self.judge = judge.start()
        self.addCleanup(judge.stop)
        remote = patch.object(experiment, "check_remote")
        self.remote = remote.start()
        self.addCleanup(remote.stop)
        self.old, self.new = self.root / "old", self.root / "new"
        self.old.write_text("old")
        self.new.write_text("new")
        self.cases = [{"pr": f"https://github.com/external/project/pull/{i}",
                       "base": "a" * 40, "head": str(i) * 40, "rationale": "private adjudication",
                       "split": split, "expected": label}
                      for i, (split, label) in enumerate(
                          (("development", "changes"), ("development", "ship"),
                           ("holdout", "changes"), ("holdout", "ship")), 1)]

    def run_comparison(self, flagged):
        def reviewer(repo, subject, prompt, model, timeout):
            self.assertEqual(set(subject), {"pr", "base", "head"})
            text = prompt.read_text()
            self.new.write_text("edited mid-experiment")
            findings = [{"key": "defect", "path": "x", "finding": "broken behavior"}] if (
                text, subject["head"][0]) in flagged else []
            return {**subject, "skill": digest(text), "model": model, "findings": findings}
        with patch.object(experiment.feedback, "review", side_effect=reviewer) as review:
            result = experiment.evaluate(self.root, self.cases, self.old, self.new, "codex", 15, 2)
            self.assertEqual(review.call_count, 16)
            self.assertEqual(result["candidate_sha256"], digest("new"))
            return result

    def test_gate_checks_complete_blind_paired_reports(self):
        receipt = self.run_comparison({("new", "3")})
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["summary"][1]["holdout"]["baseline"]["misses"], 1)
        for change in ("remove", "duplicate", "wrong_prompt", "wrong_base", "missing_findings"):
            damaged = copy.deepcopy(receipt)
            rows = damaged["results"]
            if change == "remove":
                rows.pop()
            elif change == "duplicate":
                rows[-1] = rows[0]
            elif change == "wrong_prompt":
                rows[0]["report"]["skill"] = digest("other")
            elif change == "wrong_base":
                rows[0]["report"]["base"] = "f" * 40
            else:
                rows[0]["report"]["findings"] = {}
            with self.subTest(change=change), self.assertRaises(ValueError):
                experiment.rescore(self.cases, damaged)

    def test_changes_on_unrelated_file_are_still_a_miss(self):
        self.cases[2]["finding_paths"] = ["x", "other.py"]
        receipt = self.run_comparison({("new", "3")})
        self.assertFalse(receipt["passed"])
        self.assertEqual(receipt["summary"][0]["holdout"]["candidate"]["misses"], 1)

    def test_different_bug_in_same_file_does_not_match_reference(self):
        self.cases[2]["finding_paths"] = ["x"]
        self.cases[2]["rationale"] = "Retry skips previously invalidated samples."
        self.judge.return_value = {"matched": False, "reason": "The finding concerns a stale flag only."}
        receipt = self.run_comparison({("new", "3")})
        self.assertFalse(receipt["passed"])
        self.assertEqual(self.judge.call_count, 2)
        evidence, _, _ = self.judge.call_args.args
        self.assertEqual(set(evidence), {"maintainer_rationale", "finding_paths", "review_findings"})
        trial = next(t for t in receipt["results"] if t["judgment"])
        for key in ("rubric_sha256", "case_sha256", "findings_sha256", "model", "reason"):
            before = trial["judgment"][key]
            trial["judgment"][key] = ""
            with self.subTest(key=key), self.assertRaises(ValueError):
                experiment.rescore(self.cases, receipt)
            trial["judgment"][key] = before
        trial["judgment"] = None
        with self.assertRaisesRegex(ValueError, "missing semantic"):
            experiment.rescore(self.cases, receipt)

    def test_judge_rejects_tool_use_in_execution_trace(self):
        codex = self.root / "codex"
        codex.write_text(dedent("""\
            #!/bin/sh
            cat >/dev/null
            printf '%s\\n' '{"type":"item.completed","item":{"type":"command_execution"}}'
            while [ "$#" -gt 0 ]; do
                if [ "$1" = "--output-last-message" ]; then
                    printf '%s\\n' '{"matched":true,"reason":"tool-assisted answer"}' >"$2"
                    break
                fi
                shift
            done
            """))
        codex.chmod(0o700)
        with chdir(self.root), patch.dict(os.environ, {"GITHUB_ACTIONS": "false", "PATH": f"{self.root}{os.pathsep}{os.environ['PATH']}"}):
            with self.assertRaisesRegex((ValueError, RuntimeError), "tool"):
                self.real_compare({}, "codex", 10)
        events, = (self.root / ".adl" / "review-transcripts").glob("judge-*/events.jsonl")
        self.assertIn("command_execution", events.read_text())

    def test_judge_timeout_resumes_after_the_saved_review(self):
        attempts = 0
        def compare(*_):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise TimeoutError()
            return {"matched": True, "reason": "Both describe the same failure."}
        self.judge.side_effect = compare
        def review(repo, subject, prompt, model, timeout):
            return {**subject, "skill": digest(prompt.read_text()), "model": model,
                    "findings": [{"key": "bug", "path": "x", "finding": "A defect"}]}
        def run():
            return experiment.evaluate(self.root, self.cases, self.old, self.new, "m", 30, 2,
                                       cache_dir=self.root / "cache")
        with patch.object(experiment.feedback, "review", side_effect=review) as reviewer:
            with self.assertRaises(TimeoutError):
                run()
            result = run()
            self.assertEqual(run(), result)
            self.assertEqual(reviewer.call_count, 16)
            self.assertEqual(attempts, 9)

    def test_holdout_must_improve_in_each_round(self):
        receipt = self.run_comparison({("new", "3")})
        row = next(r for r in receipt["results"] if r["variant"] == "candidate"
                   and r["round"] == 2 and r["report"]["head"] == "3" * 40)
        row["report"]["findings"] = []
        row["judgment"] = None
        self.assertFalse(experiment.rescore(self.cases, receipt)["passed"])

    def test_holdout_gain_cannot_offset_development_false_alarm(self):
        self.assertFalse(self.run_comparison({("new", "2"), ("new", "3")})["passed"])

    def test_leakage_missing_classes_and_short_runs_rejected_before_review(self):
        with patch.object(experiment.feedback, "review") as review:
            for key in ("pr", "head"):
                cases = copy.deepcopy(self.cases)
                cases[-1][key] = cases[0][key]
                with self.assertRaises(ValueError):
                    experiment.evaluate(self.root, cases, self.old, self.new, "codex", 15)
            for cases, rounds in ((self.cases[1:], 3), (self.cases, 1)):
                with self.assertRaises(ValueError):
                    experiment.evaluate(self.root, cases, self.old, self.new, "codex", 15, rounds)
            review.assert_not_called()

    def test_resume_and_reject_mismatched_cache(self):
        import json
        cache = self.root / "cache"
        attempts = 0
        def review(repo, subject, prompt, model, timeout):
            nonlocal attempts
            attempts += 1
            if attempts == 4:
                raise TimeoutError("interrupted")
            return {**subject, "skill": digest(prompt.read_text()), "model": model, "findings": []}
        def evaluate():
            return experiment.evaluate(self.root, self.cases, self.old, self.new, "codex", 15, 2, cache)
        with patch.object(experiment.feedback, "review", side_effect=review):
            with self.assertRaises(TimeoutError):
                evaluate()
            self.assertEqual(len(list(cache.glob("*.json"))), 3)
            self.assertFalse(evaluate()["passed"])
            self.assertEqual(attempts, 17)
            existing = next(cache.glob("*.json"))
            report = json.loads(existing.read_text())
            report["head"] = "f" * 40
            existing.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "frozen trial"):
                evaluate()
            self.assertEqual(attempts, 17)
