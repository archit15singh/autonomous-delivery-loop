"""Measure the production semantic judge against frozen reference decisions."""
from . import factory_feedback, review_judge
from .upstream_actions import digest


def calibrate(dataset, model, timeout, rounds):
    if type(rounds) is not int or not 1 <= rounds <= 10:
        raise ValueError("use between one and ten calibration rounds")
    if dataset.get("version") != 1 or not isinstance(dataset.get("examples"), list):
        raise ValueError("expected a version 1 judge calibration dataset")
    examples = dataset["examples"]
    ids, classes, evidence = set(), set(), set()
    for row in examples:
        if (not isinstance(row["id"], str) or not row["id"].strip() or row["id"] in ids
                or type(row["expected_match"]) is not bool
                or not isinstance(row["rationale"], str) or not row["rationale"].strip()
                or not isinstance(row["finding_paths"], list)
                or any(not isinstance(p, str) or not p.strip() for p in row["finding_paths"])
                or not isinstance(row["findings"], list) or not factory_feedback.finding_keys(row)):
            raise ValueError("each calibration example needs a unique ID, label, rationale and findings")
        fingerprint = digest([row["rationale"], row["finding_paths"], row["findings"]])
        if fingerprint in evidence:
            raise ValueError("duplicate calibration evidence")
        evidence.add(fingerprint)
        ids.add(row["id"])
        classes.add(row["expected_match"])
    if classes != {False, True}:
        raise ValueError("include both matching and nonmatching calibration examples")

    totals = dict(true_matches=0, true_nonmatches=0, false_matches=0, missed_matches=0)
    results = []
    for number in range(1, rounds + 1):
        for row in examples:
            # Keep the expected answer and example ID out of the judge's inputs.
            case = {"expected": "changes", "rationale": row["rationale"], "finding_paths": row["finding_paths"]}
            judgment = review_judge.adjudicate(case, row["findings"], model, timeout)
            review_judge.validate(case, row["findings"], model, judgment)
            if row["expected_match"]:
                category = "true_matches" if judgment["matched"] else "missed_matches"
            else:
                category = "false_matches" if judgment["matched"] else "true_nonmatches"
            totals[category] += 1
            results.append({"round": number, "id": row["id"], "expected_match": row["expected_match"],
                            "judgment": judgment})
    return {"version": 1, "dataset_sha256": digest(dataset), "rubric_sha256": review_judge.RUBRIC_SHA256,
            "model": model, "rounds": rounds, "examples": len(examples), "counts": totals, "results": results,
            "passed": totals["false_matches"] == totals["missed_matches"] == 0}
