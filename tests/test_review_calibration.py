import argparse
from contextlib import chdir
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from delivery import review_improvement, review_judge
from delivery.review_calibration import calibrate


class JudgeCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.dataset = json.loads(Path("evals/review-judge.json").read_text())
        self.labels = {r["findings"][0]["finding"]: r["expected_match"] for r in self.dataset["examples"]}

    def args(self):
        parser = argparse.ArgumentParser()
        review_improvement.register(parser.add_subparsers())
        return parser.parse_args(["review-loop", "calibrate", "--rounds", "2"])

    def test_complete_repeated_observations_through_cli(self):
        args = self.args()
        args.dataset = args.dataset.resolve()
        transcripts = []
        def run(*, cwd, prompt, model, timeout, events, role, result, schema):
            rubric, evidence = prompt.rsplit("\n", 1)
            self.assertEqual(rubric, review_judge.RUBRIC)
            evidence = json.loads(evidence)
            self.assertEqual(set(evidence), {"maintainer_rationale", "finding_paths", "review_findings"})
            self.assertEqual(role, "judge")
            self.assertEqual(timeout, args.timeout)
            self.assertNotEqual(cwd, events.parent)
            self.assertEqual(json.loads(schema.read_text()), review_judge.SCHEMA)
            events.write_text('{"type":"thread.started"}\n')
            transcripts.append(events)
            matched = self.labels[evidence["review_findings"][0]["finding"]]
            result.write_text(json.dumps({"matched": matched, "reason": "compared the supplied behavior"}))
            return 0
        with TemporaryDirectory() as folder, chdir(folder), patch.object(review_judge, "run_codex", side_effect=run):
            report, status = review_improvement.dispatch(args)
            self.assertEqual(len(set(transcripts)), 8)
            for path in transcripts:
                self.assertEqual(path.parent.parent, Path.cwd() / ".adl" / "review-transcripts")
                self.assertTrue(path.is_file())
        self.assertEqual(status, 0)
        self.assertTrue(report["passed"])
        self.assertEqual({(r["round"], r["id"]) for r in report["results"]},
                         {(n, case["id"]) for n in (1, 2) for case in self.dataset["examples"]})
        self.assertEqual(report["counts"], dict(true_matches=4, true_nonmatches=4, false_matches=0, missed_matches=0))

    def test_wrong_answers_fail_both_calibration_labels(self):
        def compare(evidence, model, timeout):
            return {"matched": not self.labels[evidence["review_findings"][0]["finding"]], "reason": "inverted"}
        with patch.object(review_judge, "_compare", side_effect=compare):
            report, status = review_improvement.dispatch(self.args())
        self.assertEqual(status, 1)
        self.assertEqual(report["counts"]["false_matches"], 4)
        self.assertEqual(report["counts"]["missed_matches"], 4)

    def test_invalid_datasets_rejected_before_inference(self):
        cases = self.dataset["examples"]
        duplicate = {**cases[0], "id": "renamed", "expected_match": False}
        for rows in ([], cases[:1], [*cases, cases[0]], [*cases, duplicate],
                     [*cases[:-1], {**cases[-1], "expected_match": 1}]):
            with self.subTest(rows=len(rows)), patch.object(review_judge, "_compare") as judge:
                with self.assertRaises(ValueError):
                    calibrate({"version": 1, "examples": copy.deepcopy(rows)}, "m", 30, 1)
                judge.assert_not_called()

    def test_missing_judgment_aborts_instead_of_scoring_partial_cohort(self):
        with patch.object(review_judge, "_compare", side_effect=[{"matched": True, "reason": "matched"}, None]):
            with self.assertRaises(ValueError):
                calibrate(self.dataset, "m", 30, 1)
