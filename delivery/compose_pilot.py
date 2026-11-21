"""Run the owned Redis pilot against an explicitly selected local Docker engine."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from shutil import disk_usage
import stat
import subprocess
from tempfile import TemporaryDirectory
from uuid import uuid4

from .candidate import FULL_REVISION, git
from .factory_definition import running_definition
from .factory_learning import run_record
from .factory_workflow import file_digest, lock, record
from .verify import Contract, verify

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "verification/compose-pilot.yaml"
RECIPE = ROOT / "verification/compose-pilot.Dockerfile"
CONTRACT = ROOT / "contracts/compose-pilot.json"
PROJECT = re.compile(r"adl-pilot-[a-f0-9]{16}")
DOCKER_ERRORS = (OSError, ValueError, subprocess.SubprocessError)


def now():
    return datetime.now(timezone.utc).isoformat()


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
        config = state / "docker-config"
        config.mkdir(exist_ok=True)
        self.command = ["docker", "--config", str(config), "--host", f"unix://{socket}"]
        self.env = {"PATH": os.environ["PATH"], "HOME": str(Path.home()),
                    "ADL_PROJECT": self.project, "ADL_IMAGE": self.image,
                    "ADL_REVISION": identity["revision"]}

    def docker(self, *argv, timeout=15):
        result = subprocess.run([*self.command, *argv], env=self.env, cwd=self.state,
                                capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise ValueError(f"Docker {argv[0]} failed: {result.stderr[-3000:]}")
        return result.stdout.strip()

    def compose(self, *argv, timeout=15):
        return self.docker("compose", "--env-file", os.devnull, "-f", str(self.file),
                           "-p", self.project, *argv, timeout=timeout)

    def engine(self):
        engine = self.docker("info", "--format", "{{.ID}}")
        if not engine or engine == "<no value>":
            raise ValueError("Docker did not report its engine ID")
        return engine

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
        report = verify(contract, f"http://{location}", revision, self.project, {
            "status": "passed", "source": "compose_build", "revision": revision,
            "deployment": self.project, "artifact_sha256": image_id.removeprefix("sha256:"),
        })
        self.resources()
        if self.compose("ps", "-q", "api") != container or self.compose("ps", "-q", "probe") != relay:
            raise ValueError("pilot container or probe relay changed during probes")
        return report


def run(socket, state, revision, *, retry_start=False, cleanup_only=False, index=None):
    socket, state = socket.resolve(strict=True), state.resolve()
    if not stat.S_ISSOCK(socket.stat().st_mode):
        raise ValueError("select a local Docker Unix socket")
    receipt_path = state / "runtime.json"
    with lock(state):
        if cleanup_only:
            receipt = json.loads(receipt_path.read_text())
            if receipt["socket"] != str(socket):
                raise ValueError("cleanup must use the original socket")
            if receipt["cleanup"]["status"] == "confirmed":
                return receipt
            stack = Compose(socket, state, receipt)
            receipt["cleanup"] = cleanup(stack)
            receipt["finished_at"] = now()
            if receipt["cleanup"]["status"] != "confirmed":
                receipt.update(verdict="inconclusive", reason="cleanup_unconfirmed")
            record(receipt_path, receipt)
            return receipt

        if receipt_path.exists():
            raise ValueError("use a new state directory or reconcile the existing run with --cleanup-only")
        if not revision or not FULL_REVISION.fullmatch(revision):
            raise ValueError("provide the full candidate revision")
        git("cat-file", "-e", f"{revision}^{{commit}}", cwd=ROOT)
        if disk_usage(state).free < 512 * 1024**2:
            raise ValueError("Compose pilot requires at least 512 MiB available on the runner")
        source = git("show", f"{revision}:pilot/service.py", cwd=ROOT)
        compile(source, "pilot/service.py", "exec")
        policy = running_definition(ROOT)
        contract = Contract.read(CONTRACT)
        template = TEMPLATE.read_bytes()
        (state / "compose.yaml").write_bytes(template)
        receipt = {
            "revision": revision, "deployment": f"adl-pilot-{uuid4().hex[:16]}",
            "policy_revision": policy["revision"], "policy_sha256": policy["sha256"],
            "socket": str(socket), "started_at": now(),
            "template_sha256": sha256(template).hexdigest(), "source_sha256": sha256(source).hexdigest(),
            "recipe_sha256": file_digest(RECIPE), "contract_sha256": contract.digest,
            "verdict": "inconclusive", "reason": "interrupted", "cleanup": {"status": "pending"},
            "recovery": [],
        }
        stack = Compose(socket, state, receipt)
        receipt["engine"] = stack.engine()
        stack.compose("version")
        if any(stack.resources().values()):
            raise ValueError("pilot project already exists")
        record(receipt_path, receipt)
        try:
            with TemporaryDirectory(prefix="adl-compose-build-") as folder:
                context = Path(folder)
                (context / "service.py").write_bytes(source)
                (context / "Dockerfile").write_bytes(RECIPE.read_bytes())
                stack.docker("build", "--tag", stack.image, "--label", f"adl.run={stack.project}",
                             str(context), timeout=120)
            image = stack.docker("image", "inspect", "--format", "{{.Id}}", stack.image)
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
                raise ValueError("Docker did not return the candidate image ID")
            receipt["image_id"] = image
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
            receipt.update(observation=report, verdict=report["verdict"], reason=report["reason"])
            if report["verdict"] == "verified":
                receipt["redis_counter"] = stack.compose("exec", "-T", "redis", "redis-cli", "--raw",
                                                         "GET", "adl:counter")
                if receipt["redis_counter"] != "2":
                    receipt.update(verdict="failed", reason="redis_readback_mismatch")
        except DOCKER_ERRORS as exc:
            receipt.update(verdict="inconclusive", reason="runtime_unavailable", error=str(exc))
        finally:
            try:
                save_diagnostics(stack, receipt, "final")
            except OSError as exc:
                receipt["diagnostics_error"] = str(exc)
            finally:
                receipt["cleanup"] = cleanup(stack)
            if receipt["cleanup"]["status"] != "confirmed":
                receipt.update(verdict="inconclusive", reason="cleanup_unconfirmed")
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
    except DOCKER_ERRORS as exc:
        return {"status": "unconfirmed", "error": str(exc)}


def save_diagnostics(stack, receipt, phase):
    try:
        stack.resources()
        diagnostic = stack.compose("ps", "--all", "--format", "json") + "\n"
        diagnostic += stack.compose("logs", "--no-color", "--tail", "20")
    except DOCKER_ERRORS as exc:
        diagnostic = str(exc)
    path = stack.state / f"{phase}.log"
    path.write_text(diagnostic[-16000:] + "\n")
    receipt[f"{phase}_diagnostics"] = {"file": path.name, "sha256": file_digest(path)}
