"""Paired cold-review experiments against independently labeled PR revisions."""
from itertools import product
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from . import factory_feedback as feedback
from .github import PR_URL
from .review_artifact import publish_new
from .review_cases import check_remote
from .revisions import FULL_REVISION
from .upstream_actions import digest


VARIANTS = ("baseline", "candidate")
SPLITS = ("development", "holdout")
VERDICTS = ("changes", "ship")


def _cohort(cases):
    subjects = {}
    heads = set()
    groups = set()
    repositories = set()
    for case in cases:
        pr, base, head = (case[k] for k in ("pr", "base", "head"))
        match = PR_URL.fullmatch(pr)
        if not match or not all(FULL_REVISION.fullmatch(rev) for rev in (base, head)):
            raise ValueError("review case needs a GitHub PR and exact revisions")
        repositories.add(match[1].casefold())
        if pr in subjects or head in heads or base == head:
            raise ValueError("each review case needs a distinct PR, head and nonempty revision range")
        if case["split"] not in SPLITS or case["expected"] not in VERDICTS:
            raise ValueError("unsupported review split or verdict")
        anchors = case.get("finding_paths", [])
        if (not isinstance(anchors, list) or not all(isinstance(p, str) and p.strip() for p in anchors)
                or len(set(anchors)) != len(anchors) or (anchors and case["expected"] != "changes")):
            raise ValueError("finding paths require distinct files on a changes-requested case")
        groups.add((case["split"], case["expected"]))
        subjects[pr] = case
        heads.add(head)
    if len(repositories) != 1:
        raise ValueError("a review cohort must belong to one repository")
    if groups != set(product(SPLITS, VERDICTS)):
        raise ValueError("both splits require examples of both verdicts")
    return subjects


def _check_rounds(rounds):
    if type(rounds) is not int or rounds < 2:
        raise ValueError("review experiments require at least two paired rounds")


def _checked_findings(report, subject, model, prompt_digest):
    if (any(report.get(k) != subject[k] for k in ("pr", "base", "head"))
            or report.get("model") != model or report.get("skill") != prompt_digest):
        raise ValueError("review report does not match the frozen trial")
    if not isinstance(report.get("findings"), list):
        raise ValueError("review report must contain a findings list")
    feedback.finding_keys(report)


def decision_error(case, findings):
    """Classify one PR decision using any file anchors in its human review."""
    if case["expected"] == "ship":
        return "false_alarms" if findings else None
    paths = {finding["path"] for finding in findings}
    if not findings or not paths.issuperset(case.get("finding_paths", [])):
        return "misses"
    return None


def rescore(cases, receipt):
    """Recompute the gate from raw reports, independent of a saved pass flag."""
    cohort = _cohort(cases)
    rounds = receipt["rounds"]
    _check_rounds(rounds)
    if receipt["dataset_sha256"] != digest(cases):
        raise ValueError("experiment dataset has changed")
    hashes = {v: receipt[v + "_sha256"] for v in VARIANTS}
    if len(set(hashes.values())) != 2 or not all(re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes.values()):
        raise ValueError("experiment requires two distinct prompt digests")
    if not isinstance(receipt["model"], str) or not receipt["model"].strip():
        raise ValueError("experiment model is required")
    # Count each paired observation exactly once before considering the gate.
    summary = []
    for number in range(1, rounds + 1):
        summary.append({split: {v: {"misses": 0, "false_alarms": 0} for v in VARIANTS}
                        for split in SPLITS})
    seen = set()
    for trial in receipt["results"]:
        number, variant, report = trial["round"], trial["variant"], trial["report"]
        pr = report["pr"]
        slot = (number, variant, pr)
        if (type(number) is not int or not 1 <= number <= rounds or variant not in VARIANTS
                or pr not in cohort or slot in seen):
            raise ValueError("unexpected or duplicate review trial")
        seen.add(slot)
        case = cohort[pr]
        _checked_findings(report, case, receipt["model"], hashes[variant])
        error = decision_error(case, report["findings"])
        if error:
            summary[number - 1][case["split"]][variant][error] += 1
    if len(seen) != rounds * len(VARIANTS) * len(cohort):
        raise ValueError("missing paired review results")
    passed = True
    for scores in summary:
        for split in SPLITS:
            baseline, candidate = (scores[split][v] for v in VARIANTS)
            if any(candidate[k] > baseline[k] for k in baseline):
                passed = False
            if split == "holdout" and sum(candidate.values()) >= sum(baseline.values()):
                passed = False
    return {"passed": passed, "summary": summary}


def _trial(repo, subject, prompt, model, timeout, prompt_digest, cache):
    if cache is not None and cache.exists():
        report = json.loads(cache.read_text())
    else:
        report = feedback.review(repo, subject, prompt, model, timeout)
        _checked_findings(report, subject, model, prompt_digest)
        if cache is not None:
            # Concurrent evaluators converge on the first complete report published.
            try:
                publish_new(cache, json.dumps(report))
            except FileExistsError:
                report = json.loads(cache.read_text())
    _checked_findings(report, subject, model, prompt_digest)
    return report


def evaluate(repo, cases, baseline_path, candidate_path, model, timeout, rounds=3, cache_dir=None):
    """Freeze both prompt texts and alternate execution order across paired trials."""
    _cohort(cases)
    _check_rounds(rounds)
    check_remote(repo, PR_URL.fullmatch(cases[0]["pr"])[1])
    texts = {v: Path(p).read_text() for v, p in zip(VARIANTS, (baseline_path, candidate_path))}
    if texts["baseline"] == texts["candidate"] or not all(t.strip() for t in texts.values()):
        raise ValueError("supply two distinct nonempty reviewer prompts")
    receipt = {"version": 1, "model": model, "rounds": rounds, "dataset_sha256": digest(cases),
               "baseline_sha256": digest(texts["baseline"]), "candidate_sha256": digest(texts["candidate"]),
               "results": []}
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
    experiment_id = digest(receipt)
    with TemporaryDirectory(prefix="adl-review-prompts-") as temp:
        paths = {v: Path(temp) / (v + ".md") for v in VARIANTS}
        for variant in VARIANTS:
            paths[variant].write_text(texts[variant])
        for number in range(1, rounds + 1):
            for index, case in enumerate(cases):
                subject = {k: case[k] for k in ("pr", "base", "head")}
                order = VARIANTS if (number + index) % 2 else reversed(VARIANTS)
                for variant in order:
                    cache = None
                    if cache_dir is not None:
                        key = digest([experiment_id, number, case["pr"], variant])
                        cache = cache_dir / (key + ".json")
                    report = _trial(repo, subject, paths[variant], model, timeout,
                                    receipt[variant + "_sha256"], cache)
                    receipt["results"].append({"round": number, "variant": variant, "report": report})
    return {**receipt, **rescore(cases, receipt)}
