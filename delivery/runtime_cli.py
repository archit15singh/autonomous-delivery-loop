"""Argument parsing and exit codes for the factory's runtime operator commands."""
from pathlib import Path

from . import hosted_runtime
from .cloud_pilot import manage as cloud_pilot
from .compose_pilot import preflight as compose_preflight, run as compose_pilot
from .kube_pilot import Kubectl, diagnostics, run as kube_pilot
from .lima_pilot import run as lima_pilot
from .lima_repair import repair as lima_repair


def register(actions):
    hosted = actions.add_parser("hosted-runtime", help="dispatch or collect a disposable hosted runtime")
    hosted.set_defaults(runtime_handler=hosted_runtime_command)
    hosted_actions = hosted.add_subparsers(dest="runtime_action", required=True)
    start_hosted = hosted_actions.add_parser("start")
    start_hosted.add_argument("--revision", required=True)
    start_hosted.add_argument("--contract", choices=hosted_runtime.CONTRACTS, required=True)
    collect_hosted = hosted_actions.add_parser("collect")
    for action in (start_hosted, collect_hosted):
        action.add_argument("--state", type=Path, required=True)
        action.add_argument("--repo", type=Path, default=Path("."))
    lima = actions.add_parser("lima-pilot", help="verify the owned pilot in the Docker-free Lima VM")
    lima.set_defaults(runtime_handler=lima_pilot_command)
    lima.add_argument("--state", type=Path, required=True)
    lima.add_argument("--revision")
    lima.add_argument("--cleanup-only", action="store_true")
    lima.add_argument("--browser", action="store_true", help="verify browser to Redis worker to SQLite")
    repair = actions.add_parser("lima-repair", help="verify, repair once with host-local Codex, and verify again")
    repair.set_defaults(runtime_handler=lima_repair_command)
    repair.add_argument("--state", type=Path, required=True)
    repair.add_argument("--revision", required=True)
    repair.add_argument("--model")
    repair.add_argument("--timeout", type=int, default=180)
    repair.add_argument("--browser", action="store_true")
    preflight = actions.add_parser("compose-preflight", help="inspect the selected Compose runner")
    preflight.set_defaults(runtime_handler=compose_preflight_command)
    preflight.add_argument("--socket", type=Path, required=True)
    preflight.add_argument("--state", type=Path, required=True)
    compose = actions.add_parser("compose-pilot", help="verify and tear down the owned Redis pilot")
    compose.set_defaults(runtime_handler=compose_pilot_command)
    compose.add_argument("--socket", type=Path, required=True)
    compose.add_argument("--state", type=Path, required=True)
    compose.add_argument("--revision")
    compose.add_argument("--retry-start", action="store_true")
    compose.add_argument("--cleanup-only", action="store_true")
    compose.add_argument("--runs", type=Path)
    kube = actions.add_parser("kube-pilot", help="run the Redis pilot on a disposable kind cluster")
    kube.set_defaults(runtime_handler=kube_pilot_command)
    kube.add_argument("--kubeconfig", type=Path, required=True)
    kube.add_argument("--context", required=True)
    kube.add_argument("--state", type=Path, required=True)
    kube.add_argument("--revision")
    kube.add_argument("--image")
    kube.add_argument("--retry", action="store_true")
    kube.add_argument("--cleanup-only", action="store_true")
    kube.add_argument("--rollback-revision")
    inspect_runtime = actions.add_parser("kube-diagnostics", help="read workload status, events and bounded logs")
    inspect_runtime.set_defaults(runtime_handler=kube_diagnostics_command)
    inspect_runtime.add_argument("--kubeconfig", type=Path, required=True)
    inspect_runtime.add_argument("--context", required=True)
    inspect_runtime.add_argument("--namespace", required=True)
    inspect_runtime.add_argument("--deployment", required=True)
    cloud = actions.add_parser("cloud-pilot", help="plan and approve a disposable OpenTofu resource")
    cloud.set_defaults(runtime_handler=cloud_pilot_command)
    cloud.add_argument("action", choices=("create", "destroy", "approve", "apply", "reconcile"))
    cloud.add_argument("--state", type=Path, required=True)
    cloud.add_argument("--backend", choices=("local", "aws"))
    cloud.add_argument("--region")
    cloud.add_argument("--account")
    cloud.add_argument("--approval", type=Path)


def pilot_result(receipt, cleanup_only):
    if cleanup_only:
        return receipt, int(receipt["cleanup"]["status"] != "confirmed")
    return receipt, int(receipt["verdict"] != "verified")


def lima_repair_command(args):
    receipt = lima_repair(args.state.resolve(), args.revision, model=args.model,
                          timeout=args.timeout, browser=args.browser)
    return receipt, int(receipt["verdict"] != "verified")


def lima_pilot_command(args):
    receipt = lima_pilot(args.state.resolve(), args.revision, cleanup_only=args.cleanup_only, browser=args.browser)
    return pilot_result(receipt, args.cleanup_only)


def hosted_runtime_command(args):
    state = args.state.resolve()
    if args.runtime_action == "start":
        return hosted_runtime.start(args.repo, state, args.revision, args.contract), 0
    receipt = hosted_runtime.collect(args.repo, state)
    if receipt["status"] != "completed":
        return receipt, 3
    return receipt, int(receipt["verdict"] != "verified")


def compose_preflight_command(args):
    report = compose_preflight(args.socket, args.state)
    return report, int(report["status"] != "ready")


def compose_pilot_command(args):
    receipt = compose_pilot(args.socket, args.state, args.revision, retry_start=args.retry_start,
                            cleanup_only=args.cleanup_only, index=args.runs)
    return pilot_result(receipt, args.cleanup_only)


def kube_pilot_command(args):
    receipt = kube_pilot(args.kubeconfig, args.context, args.state, args.revision, args.image,
                         retry=args.retry, cleanup_only=args.cleanup_only,
                         rollback_revision=args.rollback_revision)
    return pilot_result(receipt, args.cleanup_only)


def kube_diagnostics_command(args):
    return diagnostics(Kubectl(args.kubeconfig, args.context), args.namespace, args.deployment), 0


def cloud_pilot_command(args):
    return cloud_pilot(args.state, args.action, backend=args.backend, account=args.account,
                       region=args.region, approval=args.approval), 0
