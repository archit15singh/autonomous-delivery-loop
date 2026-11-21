"""Replay an observed factory failure and a held-out control on two pinned policies."""
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from .candidate import FULL_REVISION
from .upstream import checkout, run_check, validate_command


def replay_change(repo, baseline, candidate, contract_path, output):
    if not all(FULL_REVISION.fullmatch(revision) for revision in (baseline, candidate)) or baseline == candidate:
        raise ValueError("replay needs two different full factory revisions")
    raw = contract_path.read_bytes()
    contract = json.loads(raw)
    driver = contract_path.parent / contract["driver"]
    if not driver.resolve().is_relative_to(contract_path.parent.resolve()):
        raise ValueError("replay driver must be beside the contract")
    if sha256(driver.read_bytes()).hexdigest() != contract["driver_sha256"]:
        raise ValueError("factory replay driver differs from the approved digest")
    cases = contract["cases"]
    if {case["type"] for case in cases} != {"observed", "held_out"}:
        raise ValueError("include both an observed failure and a held-out control")
    names = [case["id"] for case in cases]
    if len(names) != len(set(names)) or any(not name.isascii() or not name.isalnum() for name in names):
        raise ValueError("replay cases need distinct alphanumeric IDs")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    outcomes = {}
    with TemporaryDirectory(prefix="adl-factory-replay-") as scratch:
        for side, revision in (("baseline", baseline), ("candidate", candidate)):
            folder = Path(scratch) / side
            with checkout(repo.resolve(), folder, revision):
                reports = outcomes[side] = {}
                for case in cases:
                    argv = case["command"]
                    validate_command(argv)
                    command = [str(driver.resolve()) if arg == "{driver}" else arg for arg in argv]
                    seconds = case.get("timeout", 30)
                    expected = case[side]
                    if type(seconds) is not int or not 1 <= seconds <= 300:
                        raise ValueError("replay timeout must be 1–300")
                    if not expected.get("contains") or type(expected["exit"]) is not int:
                        raise ValueError("replay case needs an exit code and a behavior marker")
                    started = monotonic()
                    report = run_check(folder, command, seconds, expected, output / f"{side}-{case['id']}.log")
                    reports[case["id"]] = {**report, "seconds": round(monotonic() - started, 3)}
    return {"baseline": baseline, "candidate": candidate, "contract_sha256": sha256(raw).hexdigest(),
            "cases": outcomes, "passed": all(item["passed"] for reports in outcomes.values() for item in reports.values())}
