"""Operator-facing commands that compose factory evidence and workflow tools."""
import json
from pathlib import Path

from . import factory_benchmark as benchmark
from . import factory_evidence as evidence
from . import factory_learning as learning
from . import factory_publish as publication
from .factory_lifecycle import github_events, read_analysis_run, revert_events
from .factory_replay import replay_change
from . import factory_workflow as engine
from .verify import Contract


def register(commands):
    root = commands.add_parser("factory", help="operate the evidence-first delivery pipeline")
    root.add_argument("--output", type=Path, default=Path("-"))
    actions = root.add_subparsers(dest="operation", required=True)
    actions.add_parser("self-check")
    lifecycle = actions.add_parser("lifecycle")
    lifecycle.add_argument("--repository", required=True)
    lifecycle.add_argument("--environment", required=True)
    lifecycle.add_argument("--limit", type=int, default=10)
    lifecycle.add_argument("--repo", type=Path, default=Path("."))
    lifecycle.add_argument("--reverts", nargs=2, metavar=("FIRST", "LAST"))
    replay = actions.add_parser("replay-change")
    replay.add_argument("--repo", type=Path, default=Path("."))
    replay.add_argument("--baseline", required=True)
    replay.add_argument("--candidate", required=True)
    replay.add_argument("--contract", type=Path, required=True)
    replay.add_argument("--logs", type=Path, required=True)
    cases = actions.add_parser("benchmark")
    cases.add_argument("--repo", type=Path, default=Path("."))
    cases.add_argument("--frozen", type=Path)
    cases.add_argument("--trials", type=Path)
    cases.add_argument("--case", action="append")
    cases.add_argument("--cost-routing", action="store_true", help="compare complete billed-cost trials")
    compare = actions.add_parser("classify")
    compare.add_argument("head", type=Path)
    compare.add_argument("base", type=Path)
    portfolio = actions.add_parser("portfolio")
    portfolio.add_argument("ci", type=Path)
    portfolio.add_argument("ledger", type=Path)
    portfolio.add_argument("--evidence", type=Path)
    portfolio.add_argument("--runs", type=Path)
    run = actions.add_parser("record-run")
    run.add_argument("spec", type=Path)
    run.add_argument("--runs", type=Path, required=True)
    assess = actions.add_parser("assess-process")
    assess.add_argument("facts", type=Path)
    measure = actions.add_parser("measure-runs")
    measure.add_argument("--runs", type=Path, required=True)
    mine = actions.add_parser("mine-runs")
    mine.add_argument("--runs", type=Path, required=True)
    mine.add_argument("--minimum", type=int, default=2)
    mine.add_argument("--spool", type=Path, help="approved run specs to index before mining")
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
    rollout.add_argument("analysis_run", type=Path, nargs="?")
    rollout.add_argument("--context")
    rollout.add_argument("--namespace")
    rollout.add_argument("--name")
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
    publish.add_argument("--ledger", type=Path)
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
    if op == "lifecycle":
        result = github_events(args.repository, args.environment, args.limit)
        if args.reverts:
            result["events"].extend(revert_events(args.repo, *args.reverts))
        return result, 0
    if op == "replay-change":
        result = replay_change(args.repo, args.baseline, args.candidate, args.contract, args.logs)
        return result, int(not result["passed"])
    if op == "benchmark":
        manifest = benchmark.dataset(args.repo)
        if args.frozen and read(args.frozen) != manifest:
            raise ValueError("benchmark files differ from the pinned manifest")
        if not args.trials:
            if args.cost_routing:
                raise ValueError("cost routing requires trial receipts")
            return manifest, 0
        if not args.frozen:
            raise ValueError("rating trials requires a pinned benchmark manifest")
        ids = {case["id"] for case in manifest["cases"]}
        if args.case:
            if not set(args.case) <= ids:
                raise ValueError("selected trial case is outside the frozen manifest")
            ids = set(args.case)
        if args.cost_routing:
            return benchmark.cost_route(sorted(ids), read(args.trials)), 0
        result = benchmark.promotion(sorted(ids), read(args.trials))
        return result, int(not result["promote"])
    if op == "classify":
        return evidence.compare_failures(read(args.head), read(args.base)), 0
    if op == "portfolio":
        attachments = read(args.evidence) if args.evidence else []
        if args.runs:
            attachments.extend(learning.pr_evidence(args.runs))
        return evidence.portfolio(read(args.ci), read(args.ledger), attachments), 0
    if op == "record-run":
        return learning.run_record(args.spec, args.runs), 0
    if op == "assess-process":
        return learning.assess_process(read(args.facts)), 0
    if op == "measure-runs":
        return learning.measure(args.runs), 0
    if op == "mine-runs":
        if args.spool:
            learning.index_spool(args.spool, args.runs)
        return learning.mine(args.runs, minimum=args.minimum), 0
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
        live = [args.context, args.namespace, args.name]
        if args.analysis_run and any(live):
            raise ValueError("choose a saved AnalysisRun or a live read")
        run = read(args.analysis_run) if args.analysis_run else read_analysis_run(*live)
        result = evidence.analysis_observation(run, policy, args.revision,
                                               args.deployment, uid=args.uid)
        return result, int(result["verdict"] != "verified")
    if op == "workflow":
        result = engine.workflow(args.plan, args.repo, args.state, args.tier,
                                 read(args.approval) if args.approval else None)
        return result, int(result["status"] != "verified")
    if op == "publish":
        return publication.publish(args.repo, args.manifest, args.candidate, args.contract,
                                   apply=args.apply, ledger=args.ledger), 0
    result = publication.merge_preview(args.repo, args.base, args.candidate)
    return result, int(result["verdict"] != "mergeable")
