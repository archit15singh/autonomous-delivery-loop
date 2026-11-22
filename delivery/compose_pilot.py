"""Run the owned Redis pilot against an explicitly selected local Docker engine."""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from shutil import disk_usage, which
import stat
import subprocess
from tempfile import TemporaryDirectory
from uuid import uuid4

from .revisions import FULL_REVISION, git
from .factory_definition import running_definition
from .run_index import run_record
from .run_state import file_digest, lock, record
from .runtime_checks import CONTRACT, ROOT, RUNTIME_ERRORS, assess_cleanup, assess_observation, now
from .scenario import HttpStep
from .verify import Contract, verify

TEMPLATE = ROOT / "verification/compose-pilot.yaml"
RECIPE = ROOT / "verification/compose-pilot.Dockerfile"
PRODUCT_RECIPE = ROOT / "verification/compose-product.Dockerfile"
APPLICATION_RECIPE = ROOT / "verification/compose-bottle.Dockerfile"
APPLICATION_LOCK = ROOT / "verification/compose-bottle.lock"
PROJECT = re.compile(r"adl-pilot-[a-f0-9]{16}")
MIN_FREE_BYTES = 512 * 1024**2
MIN_ENGINE_MAJOR = 28


def docker_cli(socket, config, cwd, *argv, variables=None, timeout=15):
    command = ["docker", "--config", str(config), "--host", f"unix://{socket}"]
    env = {"PATH": os.environ.get("PATH", os.defpath),
           "HOME": str(Path.home()), **(variables or {})}
    result = subprocess.run([*command, *argv], env=env, cwd=cwd,
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise ValueError(f"Docker {argv[0]} failed: {result.stderr[-3000:]}")
    return result.stdout.strip()


def engine_id(call):
    engine = call("info", "--format", "{{.ID}}")
    if not engine or engine == "<no value>":
        raise ValueError("Docker did not report its engine ID")
    return engine


def inspect_runner(call):
    version = call("version", "--format", "{{.Server.Version}}")
    major = re.match(r"([0-9]+)\.", version)
    if not major or int(major[1]) < MIN_ENGINE_MAJOR:
        raise ValueError(f"Docker Engine {MIN_ENGINE_MAJOR}+ is required; found {version!r}")
    compose = call("compose", "version", "--short")
    if not compose:
        raise ValueError("Docker Compose did not report its version")
    return {"engine": engine_id(call), "engine_version": version, "compose_version": compose}


def preflight(socket, state):
    state = state.resolve()
    folder = next(path for path in (state, *state.parents) if path.exists())
    free = disk_usage(folder).free
    tools = {name: which(name) is not None for name in ("docker", "colima")}
    blockers = []
    if not folder.is_dir():
        blockers.append("state_path_is_not_a_directory")
    if free < MIN_FREE_BYTES:
        blockers.append("insufficient_runner_disk")
    if not tools["docker"]:
        blockers.append("docker_cli_missing")
    socket = socket.resolve()
    try:
        is_socket = stat.S_ISSOCK(socket.stat().st_mode)
    except OSError:
        is_socket = False
    if not is_socket:
        blockers.append("docker_unix_socket_unavailable")
    runtime = {}
    if is_socket and tools["docker"]:
        try:
            with TemporaryDirectory(prefix="adl-docker-config-") as config:
                runtime = inspect_runner(lambda *args: docker_cli(socket, config, config, *args))
        except RUNTIME_ERRORS as exc:
            blockers.append("docker_runner_unavailable")
            runtime["error"] = str(exc)
    return {"status": "blocked" if blockers else "ready", "socket": str(socket),
            "state": str(state), "free_bytes": free, "minimum_free_bytes": MIN_FREE_BYTES,
            "tools": tools, "blockers": blockers, **runtime}


class Compose:
    def __init__(self, socket, state, identity):
        self.state = state
        self.identity = identity
        self.project = identity["deployment"]
        if not PROJECT.fullmatch(self.project):
            raise ValueError("invalid pilot project")
        self.image = f"{self.project}-api"
        self.file = state / "compose.yaml"
        if file_digest(self.file) != identity["template_sha256"]:
            raise ValueError("saved Compose template changed")
        self.socket = socket
        self.config = state / "docker-config"
        self.config.mkdir(exist_ok=True)
        # Preserve cleanup for receipts written by earlier versions of the runner.
        runtime = identity.get("compose_options", {})
        redis = runtime.get("redis", True)
        self.variables = {"COMPOSE_PROFILES": "redis" if redis else "",
                          "ADL_REDIS_HOST": "redis" if redis else "",
                          "ADL_API_PORT": str(runtime.get("port", 8080)),
                          "ADL_API_MEMORY": f"{runtime.get('memory_mb', 96)}m",
                          "ADL_API_CPUS": str(runtime.get("cpu_limit", 0.5)),
                          "ADL_HEALTH_PATH": runtime.get("health_path", "/health"),
                          "ADL_PROBE_PATHS": json.dumps(runtime.get("paths", ["/_revision", "/health", "/counter"])),
                          "ADL_PROBE_ROUTES": json.dumps(runtime.get("routes", [])),
                          "ADL_PROJECT": self.project, "ADL_IMAGE": self.image,
                          "ADL_REVISION": identity["revision"]}

    def docker(self, *argv, timeout=15):
        return docker_cli(self.socket, self.config, self.state, *argv, variables=self.variables,
                          timeout=timeout)

    def compose(self, *argv, timeout=15):
        return self.docker("compose", "--env-file", os.devnull, "-f", str(self.file),
                           "-p", self.project, *argv, timeout=timeout)

    def engine(self):
        return engine_id(self.docker)

    def resources(self):
        if self.engine() != self.identity["engine"]:
            raise ValueError("Docker engine changed")
        resources = {}
        for kind in ("container", "network", "volume"):
            args = [kind, "ls", "-q", "--filter", f"label=com.docker.compose.project={self.project}"]
            if kind == "container":
                args += ["-a", "--no-trunc"]
            found = set(self.docker(*args).splitlines())
            if found and found != set(self.docker(*args, "--filter", f"label=adl.run={self.project}").splitlines()):
                raise ValueError(f"foreign {kind} in Compose project")
            resources[kind] = sorted(found)
        images = self.docker("image", "ls", "-q", "--no-trunc", "--filter", f"reference={self.image}").splitlines()
        if images:
            owner = self.docker("image", "inspect", "--format", '{{index .Config.Labels "adl.run"}}', self.image)
            if owner != self.project:
                raise ValueError("foreign image at the pilot tag")
        resources["image"] = images
        return resources

    def cleanup(self):
        resources = self.resources()
        if any(resources[kind] for kind in ("container", "network", "volume")):
            self.compose("down", "--volumes", timeout=30)
        if resources["image"]:
            self.docker("image", "rm", self.image)
        remaining = self.resources()
        if any(remaining.values()):
            raise ValueError("project resources remain")
        return {"status": "confirmed", "remaining": remaining}

    def observe(self, contract, image_id):
        self.resources()
        container = self.compose("ps", "-q", "api")
        deployed = self.docker("container", "inspect", "--format", "{{.Image}}", container)
        if deployed != image_id:
            raise ValueError("running container does not use the candidate image")
        relay = self.compose("ps", "-q", "probe")
        location = self.compose("port", "probe", "8080")
        if not re.fullmatch(r"127\.0\.0\.1:[1-9][0-9]{0,4}", location):
            raise ValueError("pilot must publish a single loopback port")
        revision = self.identity["revision"]
        options = {"read_state": self.read_state} if contract.steps else {}
        report = verify(contract, f"http://{location}", revision, self.project, {
            "status": "passed", "source": "compose_build", "revision": revision,
            "deployment": self.project, "artifact_sha256": image_id.removeprefix("sha256:"),
        }, **options)
        deployed_after = self.docker("container", "inspect", "--format", "{{.Image}}", container)
        self.resources()
        if deployed_after != image_id or self.compose("ps", "-q", "api") != container or self.compose("ps", "-q", "probe") != relay:
            raise ValueError("pilot container or probe relay changed during probes")
        return report

    def read_state(self, key):
        return json.loads(self.compose("exec", "-T", "redis", "redis-cli", "--json", "GET", key, timeout=3))


def run(socket, state, revision, *, retry_start=False, cleanup_only=False, index=None, product=None):
    socket, state = socket.resolve(), state.resolve()
    if not cleanup_only and not stat.S_ISSOCK(socket.stat().st_mode):
        raise ValueError("select a local Docker Unix socket")
    receipt_path = state / "runtime.json"
    with lock(state):
        if cleanup_only:
            receipt = json.loads(receipt_path.read_text())
            if product is not None and receipt.get("product") != product.identity:
                raise ValueError("cleanup must use the original product identity")
            if receipt["socket"] != str(socket):
                raise ValueError("cleanup must use the original socket")
            if receipt["cleanup"]["status"] == "confirmed":
                return receipt
            if not stat.S_ISSOCK(socket.stat().st_mode):
                raise ValueError("select a local Docker Unix socket")
            stack = Compose(socket, state, receipt)
            assess_cleanup(receipt, cleanup(stack))
            receipt["finished_at"] = now()
            record(receipt_path, receipt)
            return receipt

        if receipt_path.exists():
            raise ValueError("use a new state directory or reconcile the existing run with --cleanup-only")
        if not revision or not FULL_REVISION.fullmatch(revision):
            raise ValueError("provide the full candidate revision")
        if disk_usage(state).free < MIN_FREE_BYTES:
            raise ValueError("Compose pilot requires at least 512 MiB available on the runner")
        app_files = getattr(product, "files", ())
        if product is None:
            git("cat-file", "-e", f"{revision}^{{commit}}", cwd=ROOT)
            source = git("show", f"{revision}:pilot/service.py", cwd=ROOT)
            source_path = "pilot/service.py"
            recipe = RECIPE
            contract = Contract.read(CONTRACT)
        else:
            if product.revision != revision:
                raise ValueError("product revision differs from the selected candidate")
            source, source_path = product.source, product.source_path
            recipe = APPLICATION_RECIPE if app_files else PRODUCT_RECIPE
            contract = product.contract
        compile(source, source_path, "exec")
        policy = running_definition(ROOT)
        template = TEMPLATE.read_bytes()
        (state / "compose.yaml").write_bytes(template)
        receipt = {
            "revision": revision, "deployment": f"adl-pilot-{uuid4().hex[:16]}",
            "policy_revision": policy["revision"], "policy_sha256": policy["sha256"],
            "socket": str(socket), "started_at": now(),
            "template_sha256": sha256(template).hexdigest(), "source_sha256": sha256(source).hexdigest(),
            "recipe_sha256": file_digest(recipe), "contract_sha256": contract.digest,
            "verdict": "inconclusive", "reason": "interrupted", "cleanup": {"status": "pending"},
            "recovery": [],
        }
        if product is not None:
            receipt["product"] = product.identity
            paths = {probe.path for probe in contract.probes}
            paths.add("/_revision")
            routes = [[step.method, step.path] for step in contract.steps if isinstance(step, HttpStep)]
            receipt["compose_options"] = {
                "port": product.port, "redis": product.redis, "memory_mb": product.memory_mb,
                "cpu_limit": product.cpu_limit, "health_path": "/_revision", "paths": sorted(paths), "routes": routes,
            }
        if app_files:
            receipt["dependency_lock_sha256"] = file_digest(APPLICATION_LOCK)
        stack = Compose(socket, state, receipt)
        receipt.update(inspect_runner(stack.docker))
        if any(stack.resources().values()):
            raise ValueError("pilot project already exists")
        record(receipt_path, receipt)
        try:
            with TemporaryDirectory(prefix="adl-compose-build-") as folder:
                context = Path(folder)
                if app_files:
                    (context / "adl-wheels.lock").write_bytes(APPLICATION_LOCK.read_bytes())
                    for name, contents in app_files:
                        target = context / "app" / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(contents)
                else:
                    (context / "service.py").write_bytes(source)
                (context / "Dockerfile").write_bytes(recipe.read_bytes())
                stack.docker("build", "--tag", stack.image, "--label", f"adl.run={stack.project}",
                             str(context), timeout=120)
            image = stack.docker("image", "inspect", "--format", "{{.Id}}", stack.image)
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
                raise ValueError("Docker did not return the candidate image ID")
            receipt["image_id"] = image
            if app_files:
                receipt["oci_config_digest"] = image
            record(receipt_path, receipt)
            try:
                start(stack)
            except subprocess.TimeoutExpired:
                if not retry_start:
                    raise
                receipt["recovery"].append({"reason": "compose_start_timeout", "at": now()})
                save_diagnostics(stack, receipt, "before_retry")
                record(receipt_path, receipt)
                start(stack)
            report = stack.observe(contract, image)

            def read_counter():
                return stack.compose("exec", "-T", "redis", "redis-cli", "--raw", "GET", "adl:counter")

            assess_observation(receipt, report, read_counter if product is None or (product.redis and not contract.steps) else None)
        except RUNTIME_ERRORS as exc:
            receipt.update(verdict="inconclusive", reason="runtime_unavailable", error=str(exc))
        finally:
            try:
                save_diagnostics(stack, receipt, "final")
            except OSError as exc:
                receipt["diagnostics_error"] = str(exc)
            finally:
                assess_cleanup(receipt, cleanup(stack))
            receipt["finished_at"] = now()
            record(receipt_path, receipt)
        if index is not None:
            spec = state / "run-spec.json"
            record(spec, {"id": receipt["deployment"], "head": revision, "factory_revision": policy["revision"],
                          "finished_at": receipt["finished_at"], "receipts": {"runtime": receipt_path.name}})
            run_record(spec, index)
        return receipt


def start(stack):
    stack.resources()
    stack.compose("up", "--wait", "--wait-timeout", "25", "--no-build", timeout=45)


def cleanup(stack):
    try:
        return stack.cleanup()
    except RUNTIME_ERRORS as exc:
        return {"status": "unconfirmed", "error": str(exc)}


def save_diagnostics(stack, receipt, phase):
    try:
        stack.resources()
        diagnostic = stack.compose("ps", "--all", "--format", "json") + "\n"
        diagnostic += stack.compose("logs", "--no-color", "--tail", "20")
    except RUNTIME_ERRORS as exc:
        diagnostic = str(exc)
    path = stack.state / f"{phase}.log"
    path.write_text(diagnostic[-16000:] + "\n")
    receipt[f"{phase}_diagnostics"] = {"file": path.name, "sha256": file_digest(path)}
