"""Resolve operator-reviewed product inputs and drive disposable runtime verification."""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from . import compose_pilot, kube_pilot, lima_pilot
from .revisions import FULL_REVISION, check_candidate, git
from .verify import Contract, product_path


BACKENDS = ("compose", "lima", "kubernetes")


@dataclass(frozen=True)
class Product:
    source: bytes
    source_path: str
    revision: str
    contract_path: Path
    contract: Contract
    port: int
    redis: bool
    memory_mb: int
    cpu_limit: float
    identity: dict


def blob(repo, revision, path, limit):
    if not product_path(path):
        raise ValueError("expected a repository-relative product file")
    entry = git("ls-tree", "-z", revision, "--", path, cwd=repo)
    if not entry.startswith((b"100644 blob ", b"100755 blob ")):
        raise ValueError(f"expected a committed regular file at {path}")
    oid = entry.split(b"\t", 1)[0].split()[2].decode()
    if int(git("cat-file", "-s", oid, cwd=repo)) > limit:
        raise ValueError(f"product file exceeds {limit} bytes: {path}")
    return git("cat-file", "blob", oid, cwd=repo)


@contextmanager
def resolve(repo, base, revision, spec_path, backend):
    if backend not in BACKENDS:
        raise ValueError("unsupported backend")
    repo = repo.resolve(strict=True)
    if Path(git("rev-parse", "--show-toplevel", cwd=repo).decode().strip()).resolve() != repo:
        raise ValueError("--repo must select the root of a product checkout")
    for commit in (base, revision):
        if not FULL_REVISION.fullmatch(commit) or git("cat-file", "-t", commit, cwd=repo).strip() != b"commit":
            raise ValueError("supply full product commit SHAs for the reviewed base and candidate")
    raw = blob(repo, base, spec_path, 65536)
    spec = json.loads(raw)
    if (not isinstance(spec, dict) or set(spec) != {"version", "name", "build", "contract", "port",
                                                     "fixture", "limits", "cleanup"}
            or type(spec["version"]) is not int or spec["version"] != 1):
        raise ValueError("expected a version 1 product runtime specification")
    if not isinstance(spec["name"], str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", spec["name"]):
        raise ValueError("invalid product name")
    build = spec["build"]
    if (not isinstance(build, dict) or set(build) != {"kind", "source"}
            or build["kind"] != "python-stdlib" or not product_path(build["source"])
            or not build["source"].endswith(".py")):
        raise ValueError("build must select a python-stdlib source file")
    source_path = build["source"]
    contract_name = spec["contract"]
    if not product_path(contract_name) or len({source_path, spec_path, contract_name}) != 3:
        raise ValueError("source, specification and contract require distinct paths")
    port, limits = spec["port"], spec["limits"]
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("select an unprivileged application port")
    if (not isinstance(limits, dict) or set(limits) != {"memory_mb", "cpu"}
            or type(limits["memory_mb"]) is not int or not 32 <= limits["memory_mb"] <= 512
            or type(limits["cpu"]) not in (float, int) or not 0.1 <= limits["cpu"] <= 2):
        raise ValueError("select 32–512 MiB and 0.1–2 CPUs for the application")
    if spec["fixture"] not in ("none", "redis-counter") or spec["cleanup"] != "always":
        raise ValueError("supported fixtures are none and redis-counter; cleanup must be always")
    with TemporaryDirectory(prefix="adl-contract-") as folder:
        contract_path = Path(folder) / "contract.json"
        contract_path.write_bytes(blob(repo, base, contract_name, 65536))
        contract = Contract.read(contract_path, product=True)
        if contract.allowed_changes != (source_path,):
            raise ValueError("the reviewed contract must scope changes to the declared source file")
        check_candidate(revision, base, contract.allowed_changes, cwd=repo)
        source = blob(repo, revision, source_path, 256 * 1024)
        try:
            compile(source, source_path, "exec")
        except (SyntaxError, ValueError, OverflowError) as exc:
            raise ValueError(f"invalid Python source in {source_path}: {exc}") from exc
        identity = {"name": spec["name"], "backend": backend, "base": base, "revision": revision,
                    "spec_path": spec_path, "spec_sha256": sha256(raw).hexdigest(),
                    "source_path": source_path, "source_sha256": sha256(source).hexdigest(),
                    "contract_path": contract_name, "contract_sha256": contract.digest}
        yield Product(source, source_path, revision, contract_path, contract, port,
                      spec["fixture"] == "redis-counter", limits["memory_mb"], limits["cpu"], identity)


def register(actions):
    root = actions.add_parser("runtime", help="plan, verify and inspect a reviewed product runtime")
    operations = root.add_subparsers(dest="runtime_action", required=True)
    plan = operations.add_parser("plan", help="resolve exact product inputs without starting a backend")
    run = operations.add_parser("run", help="create, execute, verify and tear down the product")
    inspect = operations.add_parser("inspect", help="read the persisted backend receipt")
    cleanup = operations.add_parser("cleanup", help="reconcile an interrupted teardown")
    for action in (plan, run):
        action.add_argument("--repo", type=Path, required=True)
        action.add_argument("--base", required=True, help="operator-reviewed product policy commit")
        action.add_argument("--revision", required=True)
        action.add_argument("--spec", required=True, help="runtime JSON path in the base commit")
        action.add_argument("--backend", choices=BACKENDS, required=True)
    for action in (run, inspect, cleanup):
        action.add_argument("--state", required=True, type=Path)
    for action in (run, cleanup):
        action.add_argument("--socket", type=Path, help="local Docker socket for Compose")
        action.add_argument("--kubeconfig", type=Path)
        action.add_argument("--context", help="owned kind-adl-* context")


def invoke(backend, args, product=None):
    state = args.state.resolve()
    revision = product.revision if product else None
    options = {"product": product, "cleanup_only": product is None}
    if (backend == "compose") != (args.socket is not None):
        raise ValueError("--socket is required exclusively for Compose")
    if (backend == "kubernetes" and not (args.kubeconfig and args.context)
            or backend != "kubernetes" and (args.kubeconfig or args.context)):
        raise ValueError("--kubeconfig and --context are required exclusively for Kubernetes")
    if backend == "compose":
        return compose_pilot.run(args.socket, state, revision, **options)
    if backend == "kubernetes":
        return kube_pilot.run(args.kubeconfig, args.context, state, revision, **options)
    if backend == "lima":
        return lima_pilot.run(state, revision, **options)
    raise ValueError("unsupported backend")


def dispatch(args):
    if args.runtime_action in ("inspect", "cleanup"):
        receipt = json.loads((args.state / "runtime.json").read_text())
        backend = receipt.get("product", {}).get("backend")
        if backend not in BACKENDS:
            raise ValueError("state is missing a product runtime receipt")
        if args.runtime_action == "inspect":
            return receipt, 0
        receipt = invoke(backend, args)
        return receipt, int(receipt["cleanup"]["status"] != "confirmed")
    with resolve(args.repo, args.base, args.revision, args.spec, args.backend) as product:
        if args.runtime_action == "plan":
            return {"product": product.identity, "port": product.port,
                    "fixture": "redis-counter" if product.redis else "none",
                    "limits": {"memory_mb": product.memory_mb, "cpu": product.cpu_limit},
                    "cleanup": "always", "probes": [p.path for p in product.contract.probes]}, 0
        receipt = invoke(args.backend, args, product)
        return receipt, int(receipt["verdict"] != "verified" or receipt["cleanup"]["status"] != "confirmed")
