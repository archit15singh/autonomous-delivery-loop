"""Operator-facing commands that compose factory evidence and workflow tools."""
import json
from hashlib import sha256
from pathlib import Path

from . import factory_benchmark as benchmark
from . import factory_evidence as evidence
from . import factory_learning as learning
from .factory_resume import resume
from . import factory_score, run_index, work_intake
from . import factory_publish as publication
from . import product_runtime, runtime_cli
from .revisions import FULL_REVISION, git
from .factory_definition import definition
from .factory_outcomes import outcome_report
from . import factory_issue as issue_delivery
from . import factory_feedback as feedback
from .factory_lifecycle import github_events, read_analysis_run, revert_events
from .factory_replay import replay_change
from . import factory_workflow as engine
from .upstream_ci import attach_local_replay
from .verify import Contract


def register(commands):
    root = commands.add_parser("factory", help="operate the evidence-first delivery pipeline")
    root.add_argument("--output", type=Path, default=Path("-"))
    actions = root.add_subparsers(dest="operation", required=True)
    product_runtime.register(actions)
    recovery = actions.add_parser("resume", help="recover operator notes, checkout and live PR state")
    recovery.add_argument("--workspace", type=Path, default=Path("."))
    recovery.add_argument("--state-dir", type=Path, default=Path(".adl"))
    recovery.add_argument("--note", type=Path, help="short milestone note for this task")
    recovery.add_argument("--pr", help="refresh one PR and its existing ledger entries")
    actions.add_parser("self-check")
    runtime_cli.register(actions)
    snapshot = actions.add_parser("definition")
    snapshot.add_argument("--repo", type=Path, default=Path("."))
    snapshot.add_argument("--revision", required=True)
    outcomes = actions.add_parser("outcome-report")
    outcomes.add_argument("--runs", type=Path, required=True)
    outcomes.add_argument("--ci", type=Path, required=True)
    outcomes.add_argument("--lifecycle", type=Path, required=True)
    outcomes.add_argument("--observations", type=Path)
    outcomes.add_argument("--production-environment", required=True)
    lifecycle = actions.add_parser("lifecycle")
    lifecycle.add_argument("--repository", required=True)
    lifecycle.add_argument("--environment", required=True)
    lifecycle.add_argument("--limit", type=int, default=10)
    lifecycle.add_argument("--repo", type=Path, default=Path("."))
    lifecycle.add_argument("--reverts", nargs=2, metavar=("FIRST", "LAST"))
    replay = actions.add_parser("replay-change")
    replay.add_argument("--repo", type=Path, default=Path("."))
    replay.add_argument("--baseline")
    replay.add_argument("--candidate", required=True)
    replay.add_argument("--contract", type=Path)
    replay.add_argument("--frozen", type=Path)
    replay.add_argument("--case")
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
    score = actions.add_parser("score", help="score a CI snapshot and optional pre-submission receipts")
    score.add_argument("ci", type=Path)
    score.add_argument("--runs", type=Path)
    score.add_argument("--candidate", action="append", nargs=2, metavar=("ISSUE_URL", "RECEIPT"))
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
    approve_issue = actions.add_parser("approve-issue")
    approve_issue.add_argument("issue")
    approve_issue.add_argument("spec", type=Path)
    issue_run = actions.add_parser("issue-run")
    issue_run.add_argument("issue")
    issue_run.add_argument("spec", type=Path)
    issue_run.add_argument("--approval", type=Path)
    issue_run.add_argument("--ledger", type=Path, required=True)
    issue_run.add_argument("--receipts", type=Path, required=True)
    issue_run.add_argument("--index", type=Path, help="add the verified publication to the run index")
    issue_run.add_argument("--retry-generation", type=int, metavar="ATTEMPT",
                           help="retry only this interrupted generation using the current approval")
    issue_run.add_argument("--model", default="gpt-6.2-sol")
    issue_run.add_argument("--timeout", type=int, choices=range(1, 601), default=180, metavar="SECONDS")
    cold = actions.add_parser("cold-review")
    cold.add_argument("pr")
    correct = actions.add_parser("review-correction")
    correct.add_argument("report", type=Path)
    correct.add_argument("key")
    correct.add_argument("rationale")
    compare_review = actions.add_parser("review-replay")
    for name in ("correction", "original", "control", "old_skill", "new_skill"):
        compare_review.add_argument(name, type=Path)
    for command in (cold, compare_review):
        command.add_argument("--model", default="gpt-6.2-sol")
        command.add_argument("--timeout", type=int, choices=range(1, 601), default=180, metavar="SECONDS")
    release = actions.add_parser("staging-signal")
    release.add_argument("run_id")
    release.add_argument("--ledger", type=Path, required=True)
    release.add_argument("--file-issue", action="store_true")
    release.add_argument("--drill", action="store_true", help="inspect the explicit hosted staging rehearsal")
    review = actions.add_parser("handoff")
    review.add_argument("pr", type=Path)
    review.add_argument("findings", type=Path)
    adoption = actions.add_parser("adoption")
    adoption.add_argument("events", type=Path)
    bundle = actions.add_parser("bundle")
    bundle.add_argument("receipt", type=Path)
    bundle.add_argument("artifacts", nargs="*", type=Path)
    bundle.add_argument("--compose-receipt", type=Path)
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


def benchmark_manifest(repo, frozen):
    manifest = benchmark.dataset(repo)
    if frozen and read(frozen) != manifest:
        raise ValueError("benchmark files differ from the pinned manifest")
    return manifest


def dispatch(args):
    if args.operation == "runtime":
        return product_runtime.dispatch(args)
    if hasattr(args, "runtime_handler"):
        return args.runtime_handler(args)
    op = args.operation
    if op == "self-check":
        result = evidence.self_check()
        return result, int(not result["passed"])
    if op == "definition":
        return definition(args.repo, args.revision), 0
    if op == "outcome-report":
        return outcome_report(args.runs, read(args.ci), read(args.lifecycle),
                              read(args.observations) if args.observations else [],
                              args.production_environment), 0
    if op == "lifecycle":
        result = github_events(args.repository, args.environment, args.limit)
        if args.reverts:
            result["events"].extend(revert_events(args.repo, *args.reverts))
        return result, 0
    if op == "replay-change":
        baseline, contract = args.baseline, args.contract
        if args.frozen:
            if baseline or contract or not args.case:
                raise ValueError("choose a frozen case or explicit baseline and contract")
            manifest = benchmark_manifest(args.repo, args.frozen)
            selected = next((item for item in manifest["factory_replays"] if item["id"] == args.case), None)
            if selected is None:
                raise ValueError("factory replay case is not frozen")
            baseline, contract = selected["baseline"], args.repo / selected["contract"]
        elif not baseline or not contract or args.case:
            raise ValueError("explicit replay needs a baseline and contract")
        result = replay_change(args.repo, baseline, args.candidate, contract, args.logs)
        if args.frozen:
            result["frozen_case"] = args.case
        return result, int(not result["passed"])
    if op == "benchmark":
        manifest = benchmark_manifest(args.repo, args.frozen)
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
    if op == "resume":
        return resume(args.workspace, args.state_dir, args.note, args.pr)
    if op == "score":
        records = read(args.ci)
        if args.runs:
            attach_local_replay(records, run_index.indexed_runs(args.runs))
        return factory_score.score(records, args.candidate or ()), 0
    if op == "portfolio":
        records = read(args.ci)
        attachments = read(args.evidence) if args.evidence else []
        if args.runs:
            runs = run_index.indexed_runs(args.runs)
            attach_local_replay(records, runs)
            attachments.extend(learning.pr_evidence(runs))
        report = evidence.portfolio(records, read(args.ledger), attachments)
        report["scorecard"] = factory_score.score(records)
        return report, 0
    if op == "record-run":
        return run_index.run_record(args.spec, args.runs), 0
    if op == "assess-process":
        return run_index.assess_process(read(args.facts)), 0
    if op == "measure-runs":
        return learning.measure(args.runs), 0
    if op == "mine-runs":
        if args.spool:
            run_index.index_spool(args.spool, args.runs)
        return learning.mine(args.runs, minimum=args.minimum), 0
    if op == "intake":
        facts = read(args.issue)
        return (work_intake.check_issue(args.github_issue, facts) if args.github_issue else work_intake.intake(facts)), 0
    if op == "approve-issue":
        return issue_delivery.approve(args.issue, args.spec), 0
    if op == "issue-run":
        result = issue_delivery.run_issue(Path.cwd(), args.issue, args.spec, args.approval,
                                          args.ledger, args.receipts, args.model, args.timeout, args.index,
                                          retry_generation=args.retry_generation)
        return result, 3 if result["state"] in {"generation_interrupted", "reconciliation_required"} else 0
    if op == "cold-review":
        return feedback.review(Path.cwd(), feedback.live_review_subject(args.pr),
                               Path(".agents/skills/factory-cold-review/SKILL.md"),
                               args.model, args.timeout), 0
    if op == "review-correction":
        return feedback.correction(read(args.report), args.key, args.rationale), 0
    if op == "review-replay":
        result = feedback.review_replay(Path.cwd(), read(args.correction), read(args.original),
                                        read(args.control), args.old_skill, args.new_skill,
                                        args.model, args.timeout)
        return result, int(not result["passed"])
    if op == "staging-signal":
        return feedback.signal(feedback.staging_observation(args.run_id, drill=args.drill), args.ledger, args.file_issue), 0
    if op == "handoff":
        return work_intake.review_handoff(read(args.pr), read(args.findings)), 0
    if op == "adoption":
        return evidence.adoption(read(args.events)), 0
    if op == "bundle":
        receipt = read(args.receipt)
        runtime = None
        if args.compose_receipt:
            revision = receipt["revision"]
            if not FULL_REVISION.fullmatch(revision):
                raise ValueError("bundle requires a full candidate revision")
            source = git("show", f"{revision}:pilot/service.py")
            runtime = evidence.compose_evidence(
                read(args.compose_receipt), revision, receipt["ci"]["policy_revision"],
                sha256(source).hexdigest(), Contract.read(Path("contracts/compose-pilot.json")).digest,
            )
        return evidence.bundle(receipt, args.artifacts, runtime=runtime), 0
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
    if op == "merge-preview":
        result = publication.merge_preview(args.repo, args.base, args.candidate)
        return result, int(result["verdict"] != "mergeable")
    raise ValueError(f"unsupported factory operation: {op}")
