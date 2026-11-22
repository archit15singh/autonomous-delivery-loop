"""Read the factory checkout's saved learning evidence for the operator console."""
from collections import Counter, defaultdict
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import re
from statistics import median

from . import console_files
from .factory_definition import POLICY_PATHS
from .factory_score import ISSUE_URL, WEIGHTS
from .github import PR_URL
from .review_experiment import decision_error, rescore
from .upstream_actions import digest
from .revisions import FULL_REVISION

READ_LIMIT = 2 * 1024 * 1024
MODEL = re.compile(r"gpt-[0-9](?:\.[0-9]+)?(?:-[a-z0-9]{1,16}){0,3}")
REVIEW_CASES = (6308, 6649, 6652, 6701)
CALIBRATION_COUNTS = ("true_matches", "true_nonmatches", "false_matches", "missed_matches")
REPLAY_SUITES = {
    "readiness-index": ("Readiness indexing", "indexed", "ordinary"),
    "workflow-identity": ("Workflow identity", "drift", "approval"),
}
SKILLS = {
    "deliver-outcome": "Implement a scoped outcome with independent verification.",
    "factory-cold-review": "Review the exact base and candidate independently.",
    "upstream-pr": "Verify an upstream fix and track its PR through review.",
}


def _read(root, relative):
    source = console_files.read(root, Path(relative).parts, READ_LIMIT)
    if source is None:
        raise ValueError("unreadable evidence file")
    return source[0]


def _json(root, relative):
    try:
        return json.loads(_read(root, relative))
    except (OSError, ValueError, RecursionError):
        return None


def _row(title, subtitle, status, evidence, *, url=None, chart=None, **fields):
    # The console reads links and chart coordinates directly from the row.
    metadata = {"url": url} if url else {}
    metadata.update(chart or {})
    return {"title": title, "subtitle": subtitle, "status": status,
            "details": {"evidence": evidence, **fields, **metadata}, **metadata}


def _missing(title, subtitle):
    return _row(title, subtitle, "missing", "No usable measurement is available.")


def _object(value):
    return value if isinstance(value, dict) else {}


def _records(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _count(value):
    return type(value) is int and 0 <= value <= 10**15


def _metric(value):
    return type(value) in (int, float) and 0 <= value <= 10**15 and isfinite(value)


def _model(value):
    return isinstance(value, str) and MODEL.fullmatch(value)


def _score(root):
    folder = (".adl", "upstream-ci")
    latest = {}
    fields = ("total", "delivered", "provisional", "subjects")
    for name in console_files.names(root, folder):
        round_name = re.fullmatch(r"score-round([0-9]{1,6})\.json", name)
        if round_name is None and not re.fullmatch(r"scorecard(?:-[0-9]{4})?\.json", name):
            continue
        source = console_files.read(root, (*folder, name), READ_LIMIT)
        if source is None:
            continue
        mtime = source[1]
        number = int(round_name[1]) if round_name else None
        kind = "round" if round_name else "scorecard"
        order = (number if round_name else mtime, mtime, name)
        if kind in latest and order <= latest[kind][0]:
            continue
        try:
            candidate = _object(json.loads(source[0]))
        except (ValueError, RecursionError):
            continue
        candidate_milestones = _object(candidate.get("by_milestone"))
        if (all(_count(candidate.get(key)) for key in fields)
                and all(_count(candidate_milestones.get(key)) for key in WEIGHTS)):
            latest[kind] = (order, number, candidate, candidate_milestones)
    if not latest:
        return [_missing("Delivery score", "Upstream outcome snapshots")]

    # A copied older round must not outrank the highest numbered legacy round.
    _, number, report, milestones = max(latest.values(), key=lambda item: item[0][1:])
    subtitle = (f"Upstream score round {number}" if number is not None
                else "Latest upstream score snapshot")

    breakdown = [f"{key.replace('_', ' ').capitalize()} · {milestones[key]} points"
                 for key in WEIGHTS]
    rows = [_row("Delivery score", subtitle, "recorded",
                 f"{report['total']} points across {report['subjects']} subjects. "
                 f"{report['delivered']} delivered points and {report['provisional']} provisional points.",
                 milestones=breakdown)]
    for subject in _records(report.get("rows")):
        url = subject.get("subject")
        score = subject.get("score")
        state = subject.get("state")
        if (isinstance(url, str) and len(url) < 180
                and (PR_URL.fullmatch(url) or ISSUE_URL.fullmatch(url)) and _count(score)
                and state in ("OPEN", "MERGED", "CLOSED", "LOCAL", "UNKNOWN")):
            points = _object(subject.get("points"))
            earned = [f"{key.replace('_', ' ').capitalize()} · {points[key]} points"
                      for key in WEIGHTS if _count(points.get(key))]
            rows.append(_row(" / ".join(url.split("/")[3:5]) + " #" + url.rsplit("/", 1)[-1],
                             state.capitalize(), "recorded", f"{score} points in this snapshot.",
                             milestones=earned, url=url))
    return rows


def _reviews(root):
    cases = [_json(root, f".adl/review-pilot/labeled/pr-{number}.json") for number in REVIEW_CASES]
    receipt = _object(_json(root, ".adl/review-pilot/merged-experiment.json"))
    missing = _missing("Reviewer guidance experiment", "Paired development and holdout reviews")
    round_count = receipt.get("rounds")
    if type(round_count) is not int or not 2 <= round_count <= 10:
        return [missing], []
    try:
        result = rescore(cases, receipt)
    except (ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError):
        return [missing], []

    rounds = []
    for number, scores in enumerate(result["summary"], 1):
        for split, comparison in scores.items():
            errors = [f"{variant} {counts['misses']} misses and {counts['false_alarms']} false alarms"
                      for variant, counts in comparison.items()]
            rounds.append(f"Round {number} {split} · " + ". ".join(errors))
    passed = result["passed"]
    summary = _row("Reviewer guidance experiment", "Paired development and holdout reviews",
                   "passed" if passed else "retained",
                   "Candidate cleared the holdout gate." if passed else "The baseline was retained.",
                   rounds=rounds)
    disagreements = []
    for number, case in zip(REVIEW_CASES, cases):
        pr = f"https://github.com/UKGovernmentBEIS/inspect_ai/pull/{number}"
        if case["pr"] != pr:
            continue
        trials = [trial for trial in receipt["results"] if trial["report"]["pr"] == pr]
        errors = Counter(decision_error(case, trial["report"]["findings"], trial.get("judgment"))
                         for trial in trials)
        if errors["misses"] or errors["false_alarms"]:
            disagreements.append(_row(f"Reference adjudication · Inspect AI #{number}", "Paired reviewer pilot",
                                      "recorded", f"The saved reference scored {errors['misses']} misses and "
                                      f"{errors['false_alarms']} false alarms across {len(trials)} trials.",
                                      url=pr))
    return [summary], disagreements


def _judges(root, disagreements):
    rows = []
    for name, subtitle, path in (
        ("Semantic judge calibration", "Frozen synthetic controls", "review-pilot/calibration-pr55.json"),
        ("Inspect AI review calibration", "Saved reviewer disagreement and independent paraphrase",
         "architecture-calibration/inspect-results.json"),
    ):
        report = _object(_json(root, f".adl/{path}"))
        cases = _records(report.get("results"))
        model = report.get("model")
        counts = Counter()
        for case in cases:
            expected, matched = case.get("expected_match"), _object(case.get("judgment")).get("matched")
            if type(expected) is bool and type(matched) is bool:
                counts[(expected, matched)] += 1
        rounds, examples = report.get("rounds"), report.get("examples")
        if (not _model(model) or not _count(rounds) or not _count(examples) or not cases
                or sum(counts.values()) != len(cases) or rounds * examples != len(cases)):
            rows.append(_missing(name, subtitle))
            continue
        counts = dict(zip(CALIBRATION_COUNTS, (counts[True, True], counts[False, False],
                                             counts[False, True], counts[True, False])))
        passed = counts["false_matches"] == counts["missed_matches"] == 0
        rows.append(_row(name, subtitle, "passed" if passed else "failed",
                         f"{model} · {examples} examples over {rounds} rounds.",
                         counts=[f"{key.replace('_', ' ').capitalize()} · {value}"
                                 for key, value in counts.items()]))

    for number in REVIEW_CASES:
        case = _object(_json(root, f".adl/review-pilot/labeled/pr-{number}.json"))
        pr = f"https://github.com/UKGovernmentBEIS/inspect_ai/pull/{number}"
        review = case.get("review_id")
        expected, split = case.get("expected"), case.get("split")
        if (case.get("pr") == pr and _count(review) and review > 0 and case.get("can_push") is True
                and expected in ("ship", "changes") and split in ("development", "holdout")
                and case.get("evidence") == f"{pr}#pullrequestreview-{review}"):
            decision = "Approved" if expected == "ship" else "Requested changes"
            rows.append(_row(f"Maintainer reference · Inspect AI #{number}", split.capitalize(),
                             "recorded", f"{decision} on the reviewed revision. "
                             "The pilot uses the recorded GitHub decision as its reference label.",
                             url=case["evidence"]))
    rows.extend(disagreements)
    rows.append(_missing("Human correction of a judge finding", "Operator correction receipt"))
    return rows


def _benchmarks(root):
    manifest = _object(_json(root, "evals/frozen.json"))
    cases = _records(manifest.get("cases"))
    counts = {grader: sum(row.get("grader") == grader for row in cases)
              for grader in ("codex_issue_eval", "upstream_replay")}
    rows = [_row("Frozen issue suite", "Pinned replay manifest", "defined",
                 f"{counts['codex_issue_eval']} Codex issue cases and "
                 f"{counts['upstream_replay']} exact upstream replays.")
            if cases else _missing("Frozen issue suite", "Pinned replay manifest")]
    for key, (title, incident, control) in REPLAY_SUITES.items():
        report = _object(_json(root, f".adl/factory-table/merged-hosted-replays/{key}.json"))
        observations = _object(report.get("cases"))
        outcomes = [_object(_object(observations.get(side)).get(case)).get("passed")
                    for side in ("baseline", "candidate") for case in (incident, control)]
        if any(type(outcome) is not bool for outcome in outcomes):
            rows.append(_missing(title, "Hosted factory replay"))
            continue
        labels = ["Baseline incident", "Baseline held-out control", "Candidate incident",
                  "Candidate held-out control"]
        rows.append(_row(title, "Hosted factory replay", "passed" if all(outcomes) else "failed",
                         "Each check compares the observed behavior with the pinned expectation.",
                         checks=[f"{label} · {'passed' if outcome else 'failed'}"
                                 for label, outcome in zip(labels, outcomes)]))

    results = _object(_json(root, "evals/results.json"))
    trials = defaultdict(list)
    for trial in _records(results.get("trials")):
        model, round_name, variant = (trial.get(key) for key in ("model", "round", "variant"))
        if (_model(model) and round_name in ("pilot", "repeat", "climb-1", "climb-2", "climb-3", "infra-retry")
                and variant in ("plain", "equipped", "equipped-feedback", "equipped-check", "equipped-receipt")
                and type(trial.get("solved")) is bool):
            trials[model, round_name, variant].append(trial)

    cohort = {row["id"] for row in cases if row.get("grader") == "codex_issue_eval"
              and isinstance(row.get("id"), str)}
    for (model, round_name, variant), group in sorted(trials.items()):
        solved = sum(trial["solved"] for trial in group)
        seconds = [trial.get("seconds") for trial in group]
        costs = [trial.get("actual_cost_usd") for trial in group]
        observed_cases = [trial.get("case") for trial in group]
        comparable = (len(group) == len(cohort) and all(isinstance(case, str) and case in cohort
                      for case in observed_cases) and len(set(observed_cases)) == len(cohort)
                      and all(trial.get("capacity_event") is False for trial in group))
        billed = all(_metric(cost) for cost in costs)
        chart = {"model": model, "quality": solved / len(group)} if comparable else {}
        if comparable and all(map(_metric, seconds)):
            chart["median_seconds"] = median(seconds)
        if comparable and billed:
            chart["cost"] = sum(costs)
        elapsed = f" Median elapsed time {median(seconds):g} s." if all(map(_metric, seconds)) else ""
        tokens = [trial.get("uncached_input_tokens") for trial in group]
        usage = f" Median uncached input {median(tokens):,.0f} tokens." if all(map(_count, tokens)) else ""
        billing = "" if billed else " Billed USD is missing for one or more trials."
        status = "partial" if not comparable else "recorded"
        rows.append(_row(f"{model} · {variant}", f"Issue eval · {round_name}", status,
                         f"{solved}/{len(group)} solved.{elapsed}{usage}{billing}", chart=chart))
    if not trials:
        rows.append(_missing("Codex issue outcomes", "Model and variant trial receipts"))
    if not any("cost" in row["details"] for row in rows):
        rows.append(_missing("Cost versus quality", "Comparable billed benchmark trials"))
    return rows


def _usage(root):
    report = _object(_json(root, ".adl/local-codex-pr57/exact-local-codex/usage.json"))
    observed = _object(report.get("observed"))
    metrics = ("uncached_input_tokens", "cached_input_tokens", "output_tokens")
    rows = []
    if any(_count(observed.get(key)) for key in metrics):
        rows.append(_row("Codex pilot usage", "Captured parent and native child sessions",
                         "recorded" if report.get("complete") is True else "partial",
                         "Observed token counts for the saved pilot.",
                         tokens=[f"{key.replace('_', ' ').capitalize()} · "
                                 + (f"{observed[key]:,}" if _count(observed.get(key)) else "missing")
                                 for key in metrics]))
    else:
        rows.append(_missing("Codex pilot usage", "Captured parent and native child sessions"))
    cost = report.get("actual_cost_usd")
    rows.append(_row("Codex pilot billing", "Actual billed usage", "recorded",
                     f"Observed bill · ${cost:g} USD.") if _metric(cost)
                else _missing("Codex pilot billing", "Actual billed usage"))
    return rows


def _workflows(root):
    try:
        raw = _read(root, ".adl/factory-audit/current-plan.json")
        plan = _object(json.loads(raw))
    except (OSError, ValueError, RecursionError):
        return [_missing("Factory workflow steps", "Saved factory plan")]
    receipt = _object(_json(root, ".adl/factory-audit/fast-plan/workflow.json"))
    identity = _object(receipt.get("identity"))
    revision = plan.get("revision")
    matched = (isinstance(revision, str) and FULL_REVISION.fullmatch(revision)
               and identity.get("revision") == revision and identity.get("tier") == "fast"
               and identity.get("plan_sha256") == sha256(raw).hexdigest())
    steps = _object(receipt.get("steps")) if matched else {}
    descriptions = {"judge-controls": "Run the factory self-check", "suite": "Run the unit suite",
                    "review": "Pause for operator approval"}
    rows = []
    for step in _records(plan.get("steps")):
        name, tier = step.get("id"), step.get("tier", "fast")
        if isinstance(name, str) and name in descriptions and tier in ("fast", "full", "deep"):
            verified = _object(steps.get(name)).get("verdict") == "verified"
            rows.append(_row(descriptions[name], f"Saved factory plan · {tier} tier",
                             "verified" if verified else "defined",
                             "Verified in the saved fast-run receipt." if verified
                             else "No verified execution in the saved fast-run receipt."))
    return rows or [_missing("Factory workflow steps", "Saved factory plan")]


def _proposals(root):
    rows = []
    for folder in (".adl/review-loop", ".adl/review-pilot/runs"):
        for name in console_files.names(root, Path(folder).parts):
            if not re.fullmatch(r"[0-9a-f]{64}", name):
                continue
            proposal = _object(_json(root, f"{folder}/{name}/proposal.json"))
            guidance = proposal.get("guidance")
            if (proposal.get("status") != "proposed" or not isinstance(guidance, str)
                    or digest(guidance) != proposal.get("candidate_sha256")):
                continue
            cases = proposal.get("examples")
            errors = proposal.get("disagreements")
            if not _count(cases) or not _count(errors):
                continue
            rows.append(_row("Revise cold-review guidance", f"Experiment {name[:10]}", "proposed",
                             f"Development disagreements · {errors} across {cases} examples."))
    return rows


def _workflow_sources(root):
    folder = ".github/workflows"
    rows = []
    for name in console_files.names(root, Path(folder).parts):
        if not re.fullmatch(r"[a-z0-9_-]+\.ya?ml", name):
            continue
        path = f"{folder}/{name}"
        try:
            raw = _read(root, path)
            title = re.search(r"^name: ([A-Za-z0-9 /&()._-]+)$", raw.decode(), re.MULTILINE)
        except (ValueError, OSError):
            continue
        rows.append(_row(title[1] if title else name, "GitHub Actions workflow", "defined",
                         path, sha256=sha256(raw).hexdigest(),
                         url=f"https://github.com/archit15singh/autonomous-delivery-loop/blob/main/{path}"))
    return rows


def learning(root: Path) -> dict:
    """Return display rows using the factory checkout and its local .adl receipts."""
    root = Path(root)
    agents = [_row("Factory definition", "Git-pinned policy", "defined",
                   "Run receipts pin the policy tree to an exact Git revision.",
                   components=list(POLICY_PATHS))]
    for role, purpose in (("Writer", "Workspace write access for implementation"),
                          ("Reviewer", "Read-only independent review"),
                          ("Judge", "Read-only semantic adjudication")):
        agents.append(_row(role, "Local Codex", "configured",
                           f"{purpose}. The factory CLI defaults to gpt-6.2-sol."))
    for skill, purpose in SKILLS.items():
        try:
            available = bool(_read(root, f".agents/skills/{skill}/SKILL.md"))
        except (OSError, ValueError):
            available = False
        if available:
            agents.append(_row(skill, "Factory skill", "configured", purpose,
                               url=f"https://github.com/archit15singh/autonomous-delivery-loop/blob/main/.agents/skills/{skill}/SKILL.md"))

    improvements, disagreements = _reviews(root)
    return {"improvements": _proposals(root) + improvements + _score(root), "benchmarks": _benchmarks(root),
            "agents": agents, "judges": _judges(root, disagreements), "usage": _usage(root),
            "workflows": _workflows(root) + _workflow_sources(root)}
