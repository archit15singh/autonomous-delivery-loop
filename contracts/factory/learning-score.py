"""Replay score snapshot selection through the console's Learning read."""
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path.cwd()))
from delivery.console_learning import learning
from delivery.factory_score import WEIGHTS


def save(folder, name, delivered, order):
    path = folder / name
    path.write_text(json.dumps({
        "total": delivered, "delivered": delivered, "provisional": 0,
        "subjects": delivered // WEIGHTS["merged"],
        "by_milestone": {key: delivered if key == "merged" else 0 for key in WEIGHTS},
    }))
    os.utime(path, ns=(order, order))


with TemporaryDirectory() as directory:
    root = Path(directory)
    score_dir = root / ".adl/upstream-ci"
    score_dir.mkdir(parents=True)
    save(score_dir, "score-round76.json", 100, 1_000_000_000)
    if sys.argv[1] == "fresh":
        save(score_dir, "scorecard-0133.json", 200, 2_000_000_000)
        save(score_dir, "scorecard.json", 300, 3_000_000_000)
        malformed = score_dir / "scorecard-0336.json"
        malformed.write_text("{")
        os.utime(malformed, ns=(4_000_000_000, 4_000_000_000))
    elif sys.argv[1] != "legacy":
        raise ValueError("unknown replay")
    score = next(row for row in learning(root)["improvements"] if row["title"] == "Delivery score")
    evidence = score["details"]["evidence"]
    if sys.argv[1] == "legacy":
        assert "round 76" in score["subtitle"] and evidence.startswith("100 points")
        print("Numbered score round remains readable")
    elif evidence.startswith("100 points"):
        print("Learning ignored newer score snapshots")
        raise SystemExit(1)
    else:
        assert evidence.startswith("300 points")
        print("Learning chose latest valid score snapshot")
