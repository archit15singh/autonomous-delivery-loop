#!/usr/bin/env python3
"""Export the benchmark dimensions and aggregate results without private transcripts."""
import argparse
import json
from pathlib import Path
from statistics import median

from run import events


def paired_comparison(rows, before, after):
    def case_rows(selector):
        run_round, variant = selector
        return {row["case"]: row for row in rows
                if row["round"] == run_round and row["variant"] == variant}

    base, candidate = case_rows(before), case_rows(after)
    if not base or base.keys() != candidate.keys():
        return None
    fields = ("seconds", "uncached_input_tokens")
    reductions = {field: [] for field in fields}
    for case in sorted(base):
        for field in fields:
            initial, next_value = base[case][field], candidate[case][field]
            if initial and next_value is not None:
                reductions[field].append(round(100 * (initial - next_value) / initial, 1))
    scores = {key: median(values) if len(values) == len(base) else None
              for key, values in reductions.items()}
    quality_fields = ("stage_verified", "test_changed", "red_green_trace")
    quality = all(candidate[key]["stage_verified"] is True and candidate[key]["exit"] == 0 and all(
        not base[key][field] or candidate[key][field] for field in quality_fields
    ) for key in base)
    value = list(scores.values())
    material = quality and all(score is not None for score in value) and (
        max(value) >= 15 and min(value) >= -10
    )
    return {"before": list(before), "after": list(after), "cases": len(base),
            "quality_preserved": quality, "median_reduction_pct": scores,
            "material_gain": material}


def summarize(state, rounds):
    rows = []
    for round_name in rounds:
        for path in sorted((state / round_name).glob("*/*/result.json")):
            run = json.loads(path.read_text())
            replay_path = path.with_name("replay.json")
            replay = json.loads(replay_path.read_text()) if replay_path.exists() else {}
            usage = run["usage"]
            acceptance, regression = (run.get(key, {}) for key in ("acceptance", "regression"))
            commands, _, _ = events(path.with_name("events.jsonl"))
            test_commands = [
                cmd for cmd in commands if cmd["test_outcome"]
            ]
            saw_red = False
            red_green = False
            for attempt in test_commands:
                saw_red |= attempt["test_outcome"] == "failed"
                red_green |= saw_red and attempt["test_outcome"] == "passed"
            fresh_input = usage.get("input_tokens")
            if fresh_input is not None:
                cached = usage.get("cached_input_tokens")
                fresh_input = fresh_input - cached if cached is not None else None
            agent_exit = run["agent"]["exit"]
            stderr = path.with_name("agent.stderr")
            capacity = stderr.exists() and "Selected model is at capacity" in stderr.read_text()
            rows.append({
                "round": round_name, "case": run["case"], "variant": run["variant"],
                "model": run["model"], "solved": run["solved"],
                "acceptance_passed": acceptance.get("passed"),
                "regression_passed": regression.get("passed"),
                "scope_pass": run["scope_pass"], "test_changed": run["test_changed"],
                "stage_verified": (run["solved"] and replay.get("patch_applies")
                                   and replay.get("diff_clean") and replay.get("runtime_probe")
                                   and replay.get("candidate_tests", {}).get("exit") == 0)
                                  if replay else None,
                "artifact_sha256": replay.get("artifact_sha256"),
                "red_green_trace": red_green, "test_commands": len(test_commands),
                "command_count": len(commands), "diff_stat": run["diff_stat"],
                "exit": agent_exit, "seconds": run["agent"]["seconds"],
                "capacity_event": capacity,
                "uncached_input_tokens": fresh_input, "output_tokens": usage.get("output_tokens"),
            })
    return rows


def aggregates(rows):
    groups = sorted({(row["round"], row["variant"]) for row in rows})
    summaries = []
    for run_round, variant in groups:
        group = [r for r in rows if (r["round"], r["variant"]) == (run_round, variant)]
        metrics = {"round": run_round, "variant": variant, "cases": len(group)}
        for key in ("solved", "scope_pass", "test_changed", "red_green_trace"):
            metrics[key] = sum(r[key] for r in group)
        metrics["stage_verified"] = sum(row["stage_verified"] is True for row in group)
        for key in ("seconds", "command_count", "uncached_input_tokens", "output_tokens"):
            observed = [row[key] for row in group if row[key] is not None]
            metrics[f"median_{key}"] = median(observed) if observed else None
        summaries.append(metrics)
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("rounds", nargs="+")
    args = parser.parse_args()
    rows = summarize(args.state, args.rounds)
    if not rows:
        parser.error("no completed runs found")
    treatments = [
        (("pilot", "plain"), ("pilot", "equipped")),
        (("pilot", "equipped"), ("climb-1", "equipped-feedback")),
        (("pilot", "plain"), ("climb-1", "equipped-feedback")),
        (("climb-1", "equipped-feedback"), ("climb-2", "equipped-check")),
        (("repeat", "equipped"), ("repeat", "equipped-feedback")),
        (("repeat", "plain"), ("repeat", "equipped")),
        (("repeat", "plain"), ("repeat", "equipped-feedback")),
        (("repeat", "equipped-feedback"), ("repeat", "equipped-check")),
        (("climb-1", "equipped-feedback"), ("climb-3", "equipped-receipt")),
    ]
    comparisons = [comparison for before, after in treatments
                   if (comparison := paired_comparison(rows, before, after)) is not None]
    controls = []
    for path in sorted(args.state.glob("controls/*/*/control.json")):
        controls.append({"case": path.parent.parent.name, "revision": path.parent.name,
                         **json.loads(path.read_text())})
    runtime_path = args.state / "runtime-controls.json"
    runtime_controls = json.loads(runtime_path.read_text()) if runtime_path.exists() else []
    print(json.dumps({"controls": controls, "runtime_controls": runtime_controls,
                      "summary": aggregates(rows), "comparisons": comparisons, "trials": rows}, indent=2))


if __name__ == "__main__":
    main()
