"""Operator-facing commands that compose factory evidence and workflow tools."""
import json
from pathlib import Path

from . import factory_benchmark as benchmark
from . import factory_evidence as evidence
from . import factory_publish as publication
from . import factory_workflow as engine
from .verify import Contract


def register(commands):
    root = commands.add_parser("factory", help="operate the evidence-first delivery pipeline")
    root.add_argument("--output", type=Path, default=Path("-"))
    actions = root.add_subparsers(dest="operation", required=True)
    actions.add_parser("self-check")
    cases = actions.add_parser("benchmark")
    cases.add_argument("--repo", type=Path, default=Path("."))
    cases.add_argument("--frozen", type=Path)
    cases.add_argument("--trials", type=Path)
    cases.add_argument("--case", action="append")
    compare = actions.add_parser("classify")
    compare.add_argument("head", type=Path)
    compare.add_argument("base", type=Path)
    portfolio = actions.add_parser("portfolio")
    portfolio.add_argument("ci", type=Path)
    portfolio.add_argument("ledger", type=Path)
    portfolio.add_argument("--evidence", type=Path)
    intake = actions.add_parser("intake")
    intake.add_argument("issue", type=Path)
    intake.add_argument("--github-issue")
    review = actions.add_parser("handoff")
    review.add_argument("pr", type=Path)
    review.add_argument("findings", type=Path)
    adoption = actions.add_parser("adoption")
    adoption.add_argument("events", type=Path)
    bundle = actions.add_parser("bundle")
    bundle.add_argument("receipt", type=Path)
    bundle.add_argument("artifacts", nargs="*", type=Path)
    rollout = actions.add_parser("analysis")
    rollout.add_argument("analysis_run", type=Path)
    rollout.add_argument("--contract", type=Path, required=True)
    rollout.add_argument("--revision", required=True)
    rollout.add_argument("--deployment", required=True)
    rollout.add_argument("--uid", required=True)
    workflow = actions.add_parser("workflow")
    workflow.add_argument("plan", type=Path)
    workflow.add_argument("--repo", type=Path, default=Path("."))
    workflow.add_argument("--state", type=Path, required=True)
    workflow.add_argument("--tier", choices=("fast", "full", "deep"), required=True)
    workflow.add_argument("--approval", type=Path)
    publish = actions.add_parser("publish")
    publish.add_argument("manifest", type=Path)
    publish.add_argument("--repo", type=Path, default=Path("."))
    publish.add_argument("--candidate", required=True)
    publish.add_argument("--contract", choices=("pilot", "named-greeting"), required=True)
    publish.add_argument("--apply", action="store_true")
    combine = actions.add_parser("merge-preview")
    combine.add_argument("--repo", type=Path, default=Path("."))
    combine.add_argument("--base", required=True)
    combine.add_argument("--candidate", required=True)


def read(path):
    return json.loads(path.read_text())


def dispatch(args):
    op = args.operation
    if op == "self-check":
        result = evidence.self_check()
        return result, int(not result["passed"])
    if op == "benchmark":
        manifest = benchmark.dataset(args.repo)
        if args.frozen and read(args.frozen) != manifest:
            raise ValueError("benchmark files differ from the pinned manifest")
        if not args.trials:
            return manifest, 0
        if not args.frozen:
            raise ValueError("rating trials requires a pinned benchmark manifest")
        ids = {case["id"] for case in manifest["cases"]}
        if args.case:
            if not set(args.case) <= ids:
                raise ValueError("selected trial case is outside the frozen manifest")
            ids = set(args.case)
        result = benchmark.promotion(sorted(ids), read(args.trials))
        return result, int(not result["promote"])
    if op == "classify":
        return evidence.compare_failures(read(args.head), read(args.base)), 0
    if op == "portfolio":
        return evidence.portfolio(read(args.ci), read(args.ledger),
                                  read(args.evidence) if args.evidence else []), 0
    if op == "intake":
        facts = read(args.issue)
        return (engine.check_issue(args.github_issue, facts) if args.github_issue else engine.intake(facts)), 0
    if op == "handoff":
        return engine.review_handoff(read(args.pr), read(args.findings)), 0
    if op == "adoption":
        return evidence.adoption(read(args.events)), 0
    if op == "bundle":
        return evidence.bundle(read(args.receipt), args.artifacts), 0
    if op == "analysis":
        policy = Contract.read(args.contract).impact
        if policy is None:
            raise ValueError("the reviewed contract must define an impact policy")
        result = evidence.analysis_observation(read(args.analysis_run), policy, args.revision,
                                               args.deployment, uid=args.uid)
        return result, int(result["verdict"] != "verified")
    if op == "workflow":
        result = engine.workflow(args.plan, args.repo, args.state, args.tier,
                                 read(args.approval) if args.approval else None)
        return result, int(result["status"] != "verified")
    if op == "publish":
        return publication.publish(args.repo, args.manifest, args.candidate, args.contract, apply=args.apply), 0
    result = publication.merge_preview(args.repo, args.base, args.candidate)
    return result, int(result["verdict"] != "mergeable")
