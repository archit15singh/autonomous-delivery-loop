from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from delivery import review_improvement as loop
from delivery.upstream_actions import digest


class ReviewImprovementTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.baseline = self.root / loop.GUIDANCE
        self.baseline.parent.mkdir(parents=True)
        self.baseline.write_text("---\nname: review\n---\n\nLook for bugs.\n")
        self.candidate = self.root / "candidate.md"
        self.cases = [
            {"pr": f"https://github.com/example/project/pull/{i}", "base": "a" * 40,
             "head": str(i) * 40, "split": split, "expected": expected,
             "rationale": "private holdout" if split == "holdout" else "verify the visible result"}
            for i, (split, expected) in enumerate(
                (("development", "changes"), ("development", "ship"),
                 ("holdout", "changes"), ("holdout", "ship")), 1)]

    def test_draft_sees_only_development_disagreements(self):
        def generate(command, **kwargs):
            self.assertIn("verify the visible result", kwargs["input"])
            self.assertNotIn("private holdout", kwargs["input"])
            self.assertEqual(kwargs["cwd"].is_dir(), True)
            Path(command[command.index("--output-last-message") + 1]).write_text("Check visible behavior.")
        with patch.object(loop.factory_feedback, "review", return_value={"findings": []}) as reviewer, \
             patch.object(loop.subprocess, "run", side_effect=generate):
            result = loop.draft(self.root, self.cases, self.baseline, self.candidate, "model", 10)
        self.assertEqual(result["disagreements"], 1)
        self.assertEqual(reviewer.call_count, 2)
        self.assertEqual(self.candidate.read_text(), "---\nname: review\n---\n\nCheck visible behavior.\n")

    def test_no_error_leaves_prompt_alone(self):
        with patch.object(loop.factory_feedback, "review", return_value={"findings": []}):
            result = loop.draft(self.root, self.cases[1:2], self.baseline, self.candidate, "m", 10)
        self.assertEqual(result["status"], "no_development_disagreements")
        self.assertFalse(self.candidate.exists())

    def test_patch_requires_complete_passing_reports_and_applies_to_cold_review(self):
        self.candidate.write_text(self.baseline.read_text() + "Check visible behavior.\n")
        hashes = {"baseline": digest(self.baseline.read_text()), "candidate": digest(self.candidate.read_text())}
        receipt = {"rounds": 2, "model": "m", "version": 1, "dataset_sha256": digest(self.cases),
                   "baseline_sha256": hashes["baseline"], "candidate_sha256": hashes["candidate"], "results": []}
        for num in (1, 2):
            for variant, sha in hashes.items():
                for case in self.cases:
                    findings = [{"key": "bug", "path": "app.py", "finding": "Wrong output"}] if (
                        variant == "candidate" and case["expected"] == "changes") else []
                    report = {k: case[k] for k in ("pr", "base", "head")}
                    report.update(model="m", skill=sha, findings=findings)
                    receipt["results"].append({"round": num, "variant": variant, "report": report})
        output = self.root / "guidance.patch"
        receipt["passed"] = False
        loop.promotion_patch(self.cases, receipt, self.baseline, self.candidate, output)
        self.assertNotEqual(self.baseline.read_text(), self.candidate.read_text())
        subprocess.run(["git", "apply", str(output)], cwd=self.root, check=True)
        self.assertEqual(self.baseline.read_text(), self.candidate.read_text())
        with self.assertRaisesRegex(ValueError, "changed"):
            loop.promotion_patch(self.cases, receipt, self.baseline, self.candidate, output)

    def test_cycle_resumes_proposal_and_complete_trials(self):
        baseline = self.baseline.read_text()
        dev = [c for c in self.cases if c["split"] == "development"]

        def draft(repo, cases, guidance, output, model, timeout):
            text = guidance.read_text() + "Check visible behavior.\n"
            output.write_text(text)
            return {"status": "proposed", "candidate": str(output), "model": model,
                    "baseline_sha256": digest(baseline), "development_sha256": digest(dev),
                    "candidate_sha256": digest(text)}

        def review(repo, subject, prompt, model, timeout):
            skill = prompt.read_text()
            found = skill != baseline and subject["head"][0] in {"1", "3"}
            findings = [{"key": "bug", "path": "app.py", "finding": "Wrong output"}] if found else []
            return {**subject, "model": model, "skill": digest(skill), "findings": findings}

        with patch.object(loop.review_cases, "check_remote"), patch.object(loop.review_experiment, "check_remote"), \
             patch.object(loop, "draft", side_effect=draft) as drafter, \
             patch.object(loop.factory_feedback, "review", side_effect=review) as reviewer:
            def run():
                return loop.cycle(self.root, self.cases, self.baseline, self.root / "runs", "m", 5, 2)
            first = run()
            self.assertEqual(first["status"], "awaiting_operator_review")
            self.assertTrue(Path(first["patch"]).is_file())
            self.assertEqual(run(), first)
            drafter.assert_called_once()
            self.assertEqual(reviewer.call_count, 16)
            self.assertEqual(self.baseline.read_text(), baseline)
