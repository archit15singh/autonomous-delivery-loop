"""Pin real issue replays and compare repeated, paired Codex experiments."""
from hashlib import sha256
import json
from math import isfinite
from statistics import median


def dataset(root):
    primary = root / "evals/cases.json"
    cases = [{"id": row["instance_id"], "base": row["base_commit"], "tests": row["acceptance"],
              "grader": "codex_issue_eval"} for row in json.loads(primary.read_text())]
    files = [primary, root / "evals/requirements.txt", root / "evals/run.py", root / "evals/replay.py"]
    for path in sorted((root / "contracts/upstream").glob("*.json")):
        contract = json.loads(path.read_text())
        cases.append({"id": path.stem, "base": contract["base"], "candidate": contract["candidate"],
                      "tests": contract["command"], "grader": "upstream_replay"})
        files.append(path)
    return {"version": 1, "cases": cases,
            "files": {path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest() for path in files}}


def promotion(dataset_ids, rows):
    """Require exact case coverage twice, with quality preserved in both rounds."""
    trials = {}
    for row in rows:
        key = (row["round"], row["case"], row["variant"])
        if key in trials or row["variant"] not in {"baseline", "candidate"}:
            raise ValueError("paired inputs have a duplicate or unsupported variant")
        if row["case"] not in dataset_ids:
            raise ValueError("trial is outside the frozen cohort")
        if type(row["verified"]) is not bool or not all(
            type(row[name]) in (int, float) and isfinite(row[name]) and row[name] >= 0
            for name in ("seconds", "tokens", "interventions")
        ) or row["seconds"] == 0:
            raise ValueError("trial requires a verdict, elapsed time, tokens and interventions")
        trials[key] = row
    rounds = []
    for name in sorted({key[0] for key in trials}):
        if any((name, case, variant) not in trials for case in dataset_ids
               for variant in ("baseline", "candidate")):
            raise ValueError("each round needs both variants for every selected case")
        pairs = [(trials[name, case, "baseline"], trials[name, case, "candidate"]) for case in dataset_ids]
        gains = {}
        for field in ("seconds", "tokens"):
            values = [(before[field] - after[field]) / before[field]
                      for before, after in pairs if before[field] > 0]
            gains[field] = round(100 * median(values), 2) if values else None
        quality = all(after["verified"] is True for _, after in pairs)
        assistance = sum(after["interventions"] - before["interventions"] for before, after in pairs)
        observed = [value for value in gains.values() if value is not None]
        rounds.append({"round": name, "quality_preserved": quality, "interventions_delta": assistance,
                       "median_reduction_pct": gains, "material_gain": quality and assistance <= 0
                       and len(observed) == 2 and max(observed) >= 15 and min(observed) >= -10})
    return {"promote": len(rounds) >= 2 and all(item["material_gain"] for item in rounds),
            "cases": len(dataset_ids), "rounds": rounds}
