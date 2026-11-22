#!/usr/bin/env python3
"""Export the benchmark dimensions and aggregate results without private transcripts."""
import argparse
import json
from pathlib import Path
from statistics import median
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.run import ROOT, events
from delivery.factory_benchmark import promotion, cost_route


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
            commands, _, _ = events(path.with_name("events.jsonl"), native=run.get("coding_agent", "codex") == "codex")
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
                "model": run["model"], "coding_agent": run.get("coding_agent", "codex"), "solved": run["solved"],
                "grader_read_denial": run.get("grader_read_denial", False), "cost_usd": run.get("cost_usd"), "human_interventions": run.get("human_interventions"),
                "acceptance_passed": acceptance.get("passed"),
                "regression_passed": regression.get("passed"), "regression_exit": regression.get("exit"),
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


def learning_report(rows, baseline, candidate):
    """Feed completed, independently verified outcome pairs into adoption gates."""
    frozen = {row["instance_id"] for row in json.loads((ROOT / "cases.json").read_text())}
    grouped = {}
    reason = "paired_observations_missing"
    for row in rows:
        if row["variant"] not in (baseline, candidate):
            continue
        key = (row["case"], row["variant"])
        group = grouped.setdefault(row["round"], {})
        if key in group:
            raise ValueError("duplicate benchmark trial")
        group[key] = row
    completed = []
    qualifying_rounds = set()
    for name, group in grouped.items():
        if {(case, arm) for case in frozen for arm in (baseline, candidate)} != group.keys():
            continue
        if len({(row["coding_agent"], row["model"], row.get("grader_read_denial", False)) for row in group.values()}) != 1:
            continue
        for case in sorted(frozen):
            before, after = (group[case, arm] for arm in (baseline, candidate))
            if (before["coding_agent"], before["model"]) != (after["coding_agent"], after["model"]):
                break
            if any(row["uncached_input_tokens"] is None or row["human_interventions"] is None
                   or row["stage_verified"] is None for row in (before, after)):
                break
        else:
            qualifying_rounds.add(name)
            for (case, arm), row in group.items():
                completed.append({"round": name, "case": case,
                                  "variant": "baseline" if arm == baseline else "candidate",
                                  "verified": row["stage_verified"] and row["regression_exit"] == 0,
                                  "seconds": row["seconds"], "tokens": row["uncached_input_tokens"],
                                  "interventions": row["human_interventions"], "cost_usd": row["cost_usd"]})
    decision = promotion(sorted(frozen), completed)
    cost = cost_route(sorted(frozen), completed) if completed else {"recommendation": "baseline", "reason": reason}
    incomplete = sorted(grouped.keys() - qualifying_rounds)
    if incomplete:
        decision["promote"] = False
        cost = {"recommendation": "baseline", "reason": "incomplete_paired_evidence"}
    return {"decision": decision, "cost": cost, "incomplete_rounds": incomplete,
            "rounds_reviewed": len(grouped)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("rounds", nargs="+")
    parser.add_argument("--pair", nargs=2, metavar=("BASELINE", "CANDIDATE"))
    args = parser.parse_args()
    if args.pair and args.pair[0] == args.pair[1]:
        parser.error("--pair requires distinct variants")
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
    if args.pair:
        treatments.extend(((name, args.pair[0]), (name, args.pair[1])) for name in args.rounds)
    comparisons = [comparison for before, after in treatments
                   if (comparison := paired_comparison(rows, before, after)) is not None]
    controls = []
    for path in sorted(args.state.glob("controls/*/*/control.json")):
        controls.append({"case": path.parent.parent.name, "revision": path.parent.name,
                         **json.loads(path.read_text())})
    runtime_path = args.state / "runtime-controls.json"
    runtime_controls = json.loads(runtime_path.read_text()) if runtime_path.exists() else []
    print(json.dumps({"controls": controls, "runtime_controls": runtime_controls,
                      "summary": aggregates(rows), "comparisons": comparisons, "trials": rows,
                      "learning": learning_report(rows, *args.pair) if args.pair else None}, indent=2))


if __name__ == "__main__":
    main()
