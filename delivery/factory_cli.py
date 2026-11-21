"""Operator-facing commands that compose factory evidence and workflow tools."""
import json
from hashlib import sha256
from pathlib import Path

from . import factory_benchmark as benchmark
from . import factory_evidence as evidence
from . import factory_learning as learning
from . import factory_publish as publication
from . import hosted_runtime, product_runtime
from .lima_pilot import run as lima_pilot
from .lima_repair import repair as lima_repair
from .candidate import FULL_REVISION, git
from .compose_pilot import preflight as compose_preflight, run as compose_pilot
from .cloud_pilot import manage as cloud_pilot
from .kube_pilot import Kubectl, diagnostics, run as kube_pilot
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
    actions.add_parser("self-check")
    hosted = actions.add_parser("hosted-runtime", help="dispatch or collect a disposable hosted runtime")
    hosted_actions = hosted.add_subparsers(dest="runtime_action", required=True)
    start_hosted = hosted_actions.add_parser("start")
    start_hosted.add_argument("--revision", required=True)
    start_hosted.add_argument("--contract", choices=hosted_runtime.CONTRACTS, required=True)
    collect_hosted = hosted_actions.add_parser("collect")
    for action in (start_hosted, collect_hosted):
        action.add_argument("--state", type=Path, required=True)
        action.add_argument("--repo", type=Path, default=Path("."))
    lima = actions.add_parser("lima-pilot", help="verify the owned pilot in the Docker-free Lima VM")
    lima.add_argument("--state", type=Path, required=True)
    lima.add_argument("--revision")
    lima.add_argument("--cleanup-only", action="store_true")
    lima.add_argument("--browser", action="store_true", help="verify browser to Redis worker to SQLite")
    repair = actions.add_parser("lima-repair", help="verify, repair once in guest Codex, and verify again")
    repair.add_argument("--state", type=Path, required=True)
    repair.add_argument("--revision", required=True)
    repair.add_argument("--model")
    repair.add_argument("--timeout", type=int, default=180)
    repair.add_argument("--browser", action="store_true")
    preflight = actions.add_parser("compose-preflight", help="inspect the selected Compose runner")
    preflight.add_argument("--socket", type=Path, required=True)
    preflight.add_argument("--state", type=Path, required=True)
    compose = actions.add_parser("compose-pilot", help="verify and tear down the owned Redis pilot")
    compose.add_argument("--socket", type=Path, required=True)
    compose.add_argument("--state", type=Path, required=True)
    compose.add_argument("--revision")
    compose.add_argument("--retry-start", action="store_true")
    compose.add_argument("--cleanup-only", action="store_true")
    compose.add_argument("--runs", type=Path)
    kube = actions.add_parser("kube-pilot", help="run the Redis pilot on a disposable kind cluster")
    kube.add_argument("--kubeconfig", type=Path, required=True)
    kube.add_argument("--context", required=True)
    kube.add_argument("--state", type=Path, required=True)
    kube.add_argument("--revision")
    kube.add_argument("--image")
    kube.add_argument("--retry", action="store_true")
    kube.add_argument("--cleanup-only", action="store_true")
    kube.add_argument("--rollback-revision")
    inspect_runtime = actions.add_parser("kube-diagnostics", help="read workload status, events and bounded logs")
    inspect_runtime.add_argument("--kubeconfig", type=Path, required=True)
    inspect_runtime.add_argument("--context", required=True)
    inspect_runtime.add_argument("--namespace", required=True)
    inspect_runtime.add_argument("--deployment", required=True)
    cloud = actions.add_parser("cloud-pilot", help="plan and approve a disposable OpenTofu resource")
    cloud.add_argument("action", choices=("create", "destroy", "approve", "apply", "reconcile"))
    cloud.add_argument("--state", type=Path, required=True)
    cloud.add_argument("--backend", choices=("local", "aws"))
    cloud.add_argument("--region")
    cloud.add_argument("--account")
    cloud.add_argument("--approval", type=Path)
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


def dispatch(args):
    if args.operation == "runtime":
        return product_runtime.dispatch(args)
    if args.operation == "lima-repair":
        receipt = lima_repair(args.state.resolve(), args.revision, model=args.model,
                              timeout=args.timeout, browser=args.browser)
        return receipt, int(receipt["verdict"] != "verified")
    if args.operation == "lima-pilot":
        receipt = lima_pilot(args.state.resolve(), args.revision, cleanup_only=args.cleanup_only, browser=args.browser)
        success = (receipt["cleanup"]["status"] == "confirmed" if args.cleanup_only
                   else receipt["verdict"] == "verified")
        return receipt, int(not success)
    if args.operation == "hosted-runtime":
        state = args.state.resolve()
        if args.runtime_action == "start":
            return hosted_runtime.start(args.repo, state, args.revision, args.contract), 0
        receipt = hosted_runtime.collect(args.repo, state)
        if receipt["status"] != "completed":
            return receipt, 3
        return receipt, int(receipt["verdict"] != "verified")
    if args.operation == "compose-preflight":
        report = compose_preflight(args.socket, args.state)
        return report, int(report["status"] != "ready")
    if args.operation == "compose-pilot":
        receipt = compose_pilot(args.socket, args.state, args.revision, retry_start=args.retry_start,
                                cleanup_only=args.cleanup_only, index=args.runs)
        success = (receipt["cleanup"]["status"] == "confirmed" if args.cleanup_only
                   else receipt["verdict"] == "verified")
        return receipt, int(not success)
    if args.operation == "kube-pilot":
        receipt = kube_pilot(args.kubeconfig, args.context, args.state, args.revision, args.image,
                             retry=args.retry, cleanup_only=args.cleanup_only,
                             rollback_revision=args.rollback_revision)
        success = (receipt["cleanup"]["status"] == "confirmed" if args.cleanup_only
                   else receipt["verdict"] == "verified")
        return receipt, int(not success)
    if args.operation == "kube-diagnostics":
        return diagnostics(Kubectl(args.kubeconfig, args.context), args.namespace, args.deployment), 0
    if args.operation == "cloud-pilot":
        return cloud_pilot(args.state, args.action, backend=args.backend, account=args.account,
                           region=args.region, approval=args.approval), 0
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
            manifest = benchmark.dataset(args.repo)
            if read(args.frozen) != manifest:
                raise ValueError("benchmark files differ from the pinned manifest")
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
        records = read(args.ci)
        attachments = read(args.evidence) if args.evidence else []
        if args.runs:
            runs = learning.indexed_runs(args.runs)
            attach_local_replay(records, runs)
            attachments.extend(learning.pr_evidence(runs))
        return evidence.portfolio(records, read(args.ledger), attachments), 0
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
        return engine.review_handoff(read(args.pr), read(args.findings)), 0
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
    result = publication.merge_preview(args.repo, args.base, args.candidate)
    return result, int(result["verdict"] != "mergeable")
