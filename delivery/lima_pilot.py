"""Verify exact product sources in a dedicated Docker-free Lima VM."""
from base64 import b64decode
from hashlib import sha256
from io import BytesIO
import json
import re
import subprocess
import tarfile
from uuid import uuid4

from .revisions import FULL_REVISION, git
from .factory_definition import running_definition
from .run_state import lock, record
from .runtime_checks import (CONTRACT, PYTHON, REDIS_DIGEST, ROOT, RUNTIME_ERRORS,
                             assess_cleanup, assess_observation)
from .verify import Contract


INSTANCE = "adl-runtime"
REDIS = f"docker.io/library/redis@{REDIS_DIGEST}"
BROWSER = "mcr.microsoft.com/playwright@sha256:2f05f8a734509a7b3f26a912639488ee08f58a7b292d14d62271bcff9038768f"
PROJECT = re.compile(r"adl-local-[a-f0-9]{16}")

PROBE = """\
import json, socket, sys, time
from pathlib import Path
from delivery.verify import Contract, fetch, verify

revision, deployment, source, port, mode = sys.argv[1:]
interfaces = [name for _, name in socket.if_nameindex()]
if interfaces != ["lo"]:
    raise SystemExit(f"unexpected interfaces in the pilot network: {interfaces}")
origin = f"http://127.0.0.1:{port}"
for _ in range(20):
    if fetch(origin, "/_revision" if mode == "product" else "/health").get("status") == 200:
        break
    time.sleep(0.5)
contract_path = Path("/judge/contract.json")
contract = Contract.read(contract_path, product=True) if mode == "product" else Contract.read(contract_path)
result = verify(contract, origin, revision, deployment, {
    "status": "passed", "source": "lima_exact_source", "revision": revision,
    "deployment": deployment, "artifact_sha256": source,
})
print(json.dumps({**result, "network_interfaces": interfaces}))
"""


def command(argv, *, payload=None, timeout=30):
    options = {"input": payload} if payload is not None else {"stdin": subprocess.DEVNULL}
    result = subprocess.run(argv, **options, capture_output=True, timeout=timeout)
    if result.returncode:
        raise ValueError(result.stderr.decode(errors="replace").strip()[-3000:])
    return result.stdout.decode().strip()


class Lima:
    def __init__(self):
        instance = json.loads(command(["limactl", "list", INSTANCE, "--json"]))
        config = instance["config"]
        if (instance["name"] != INSTANCE or instance["status"] != "Running"
                or config.get("mounts") or config["ssh"]["forwardAgent"]
                or config["ssh"]["forwardX11"] or not config["containerd"]["user"]):
            raise ValueError("start the dedicated adl-runtime VM with no mounts or SSH forwarding")
        self.machine = self.guest("cat", "/etc/machine-id")
        if not re.fullmatch(r"[0-9a-f]{32}", self.machine):
            raise ValueError("Lima did not report a machine identity")
        self.version = self.nerdctl("--version")

    def guest(self, *argv, payload=None, timeout=30):
        return command(["limactl", "shell", "--preserve-env=false", "--tty=false",
                        "--workdir", "/tmp", INSTANCE, *argv], payload=payload, timeout=timeout)

    def nerdctl(self, *argv, timeout=30):
        return self.guest("nerdctl", *argv, timeout=timeout)

    def resources(self, project):
        return self.nerdctl("ps", "-aq", "--filter", f"label=adl.run={project}").splitlines()

    def cleanup(self, receipt):
        project = receipt["deployment"]
        if not PROJECT.fullmatch(project) or self.guest("cat", "/etc/machine-id") != receipt["machine"]:
            raise ValueError("Lima target changed")
        ids = self.resources(project)
        if ids:
            self.nerdctl("rm", "-f", *ids)
        folder = f"/tmp/{project}"
        self.guest("sh", "-ec", '''
          if [ -e "$1" ] || [ -L "$1" ]; then
            test ! -L "$1"
            test "$(cat "$1/.owner")" = "$2"
            rm -rf -- "$1"
          fi
        ''', "sh", folder, project)
        if self.resources(project) or self.guest("sh", "-c", 'test ! -e "$1" && echo absent',
                                                "sh", folder) != "absent":
            raise ValueError("Lima pilot resources remain")
        return {"status": "confirmed"}


def payload(source, revision, browser=False, contract_bytes=None):
    if contract_bytes is None:
        contract_bytes = git("show", f"{revision}:contracts/compose-pilot.json", cwd=ROOT)
    files = {"service.py": source, "judge/check.py": PROBE.encode(),
             "judge/contract.json": contract_bytes}
    for name in ("__init__.py", "verify.py", "impact.py", "scenario.py"):
        files[f"judge/delivery/{name}"] = git("show", f"{revision}:delivery/{name}", cwd=ROOT)
    if browser:
        for name in ("lima-job-worker.py", "lima-job-browser.mjs"):
            files[f"judge/{name}"] = git("show", f"{revision}:verification/{name}", cwd=ROOT)
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, contents in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(contents)
            member.mode = 0o644
            archive.addfile(member, BytesIO(contents))
    return buffer.getvalue()


def cleanup(lima, receipt):
    try:
        return lima.cleanup(receipt)
    except RUNTIME_ERRORS as exc:
        return {"status": "unconfirmed", "error": str(exc)}


def browser_probe(lima, state, receipt, folder, shared, same_network, redis):
    revision, project = receipt["revision"], receipt["deployment"]
    packages = lima.guest("sh", "-ec", 'test -f "$HOME/.local/share/adl/playwright-core-1.64.1/index.mjs"; '
                          'printf %s "$HOME/.local/share/adl/playwright-core-1.64.1"')
    worker = f"{project}-worker"
    lima.nerdctl("run", "-d", "--name", worker, *shared, *same_network,
                 "--read-only", "--user", "65534:65534", "--memory", "96m",
                 "-v", f"{folder}/data:/data:rw", "-v", f"{folder}/judge:/judge:ro",
                 PYTHON, "python", "-B", "/judge/lima-job-worker.py")
    result = json.loads(lima.nerdctl(
        "run", "--rm", "--name", f"{project}-browser", *shared, *same_network,
        "--user", "1000:1000", "--memory", "640m", "--shm-size", "128m",
        "--env", "HOME=/tmp", "-v", f"{folder}/judge:/judge:ro", "-v", f"{packages}:/playwright:ro",
        BROWSER, "node", "/judge/lima-job-browser.mjs", revision, project, timeout=180,
    ))
    screenshot = b64decode(result.pop("screenshot"), validate=True)
    if not screenshot.startswith(b"\x89PNG\r\n\x1a\n") or len(screenshot) > 2 * 1024 * 1024:
        raise ValueError("browser did not return a bounded PNG")
    (state / "browser.png").write_bytes(screenshot)
    if result["revision"] != revision or result["deployment"] != project:
        raise ValueError("browser evidence belongs to another deployment")
    if result["passed"]:
        query = ("import sqlite3,sys; "
                 "db=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True); "
                 "row=db.execute('SELECT status FROM jobs WHERE id=?',(sys.argv[2],)).fetchone(); "
                 "print(row[0] if row else '')")
        db_status = lima.guest("python3", "-c", query, f"{folder}/data/jobs.sqlite3", result["job"])
        result["sqlite_status"] = db_status
        result["queue_remaining"] = lima.nerdctl("exec", redis, "redis-cli", "--raw", "LLEN", "adl:jobs")
        result["passed"] = db_status == "completed" and result["queue_remaining"] == "0"
    return {**result, "screenshot": "browser.png", "screenshot_sha256": sha256(screenshot).hexdigest()}


def run(state, revision=None, *, cleanup_only=False, browser=False, product=None):
    with lock(state):
        path = state / "runtime.json"
        if cleanup_only:
            receipt = json.loads(path.read_text())
            if receipt["cleanup"]["status"] != "confirmed":
                receipt["cleanup"] = cleanup(Lima(), receipt)
                record(path, receipt)
            return receipt
        lima = Lima()
        if product is not None:
            if revision is not None and revision != product.revision:
                raise ValueError("candidate differs from the selected product revision")
            if browser:
                raise ValueError("the browser job probe requires the owned pilot")
            revision = product.revision
        if path.exists() or not revision or not FULL_REVISION.fullmatch(revision):
            raise ValueError("provide an exact candidate and a fresh state directory")
        policy = running_definition(ROOT)
        if product is None:
            source = git("show", f"{revision}:pilot/service.py", cwd=ROOT)
            contract = Contract.read(CONTRACT)
            contract_bytes = None
            redis_required, port = True, 8080
            app_limits = ["--memory", "96m"]
        else:
            source = product.source
            contract = product.contract
            contract_bytes = product.contract_path.read_bytes()
            if sha256(contract_bytes).hexdigest() != contract.digest:
                raise ValueError("product contract changed after selection")
            redis_required, port = product.redis, product.port
            app_limits = ["--memory", f"{product.memory_mb}m", "--cpus", str(product.cpu_limit)]
        compile(source, product.source_path if product is not None else "pilot/service.py", "exec")
        project = f"adl-local-{uuid4().hex[:16]}"
        folder = f"/tmp/{project}"
        redis, api, judge = (f"{project}-{name}" for name in ("redis", "api", "judge"))
        source_sha = sha256(source).hexdigest()
        receipt = {"revision": revision, "policy_revision": policy["revision"],
                   "policy_sha256": policy["sha256"], "deployment": project,
                   "machine": lima.machine, "runtime": lima.version, "source_sha256": source_sha,
                   "contract_sha256": contract.digest, "api_base_image": PYTHON,
                   "verdict": "inconclusive", "reason": "interrupted", "cleanup": {"status": "pending"}}
        if redis_required:
            receipt["redis_image"] = REDIS
        if product is not None:
            receipt["product"] = product.identity
        if lima.resources(project):
            raise ValueError("Lima project already exists")
        # Reserve before the first write in the VM so an interruption can be reconciled.
        record(path, receipt)
        shared = ["--label", f"adl.run={project}", "--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
        try:
            lima.guest("sh", "-ec", 'mkdir -m 755 -- "$1"; printf %s "$2" > "$1/.owner"',
                       "sh", folder, project)
            lima.guest("tar", "-xf", "-", "-C", folder, payload=payload(source, policy["revision"], browser, contract_bytes))
            if lima.guest("sha256sum", f"{folder}/service.py").split()[0] != source_sha:
                raise ValueError("transferred candidate differs from Git")
            app_network = ["--network", "none"]
            redis_env = []
            if redis_required:
                receipt["redis_container"] = lima.nerdctl(
                    "run", "-d", "--name", redis, *shared, "--network", "none", "--memory", "64m",
                    "--user", "999:999",
                    "--pids-limit", "32", "--tmpfs", "/data:size=16m", REDIS,
                    "redis-server", "--save", "", "--appendonly", "no", timeout=180,
                )
                app_network = ["--network", f"container:{redis}"]
                redis_env = ["--env", "ADL_REDIS_HOST=127.0.0.1"]
            restricted = ["--read-only", "--user", "65534:65534", "--pids-limit", "64"]
            port_env = (["--env", f"PORT={port}", "--env", f"ADL_PORT={port}",
                         "--env", "ADL_HOST=127.0.0.1", "--env", "HOST=127.0.0.1"]
                        if product is not None else [])
            job_args = []
            if browser:
                lima.guest("mkdir", "-m", "777", "--", f"{folder}/data")
                job_args = ["--env", "ADL_JOB_DB=/data/jobs.sqlite3", "-v", f"{folder}/data:/data:ro"]
            receipt["api_container"] = lima.nerdctl(
                "run", "-d", "--name", api, *shared, *app_network, *restricted, *app_limits,
                "--env", f"ADL_REVISION={revision}", "--env", f"ADL_DEPLOYMENT={project}",
                *redis_env, *port_env, "-v", f"{folder}/service.py:/service.py:ro",
                *job_args,
                PYTHON, "python", "-I", "-B", "/service.py", timeout=180,
            )
            same_network = ["--network", f"container:{redis if redis_required else api}"]
            observed = json.loads(lima.nerdctl(
                "run", "--rm", "--name", judge, *shared, *same_network, *restricted, "--memory", "96m",
                "-v", f"{folder}/judge:/judge:ro", "-w", "/judge", PYTHON,
                "python", "-B", "check.py", revision, project, source_sha, str(port),
                "product" if product is not None else "pilot", timeout=35,
            ))

            def read_counter():
                return lima.nerdctl("exec", redis, "redis-cli", "--raw", "GET", "adl:counter")

            assess_observation(receipt, observed, read_counter if redis_required else None)
            if browser and receipt["verdict"] == "verified":
                receipt["browser"] = browser_probe(lima, state, receipt, folder, shared, same_network, redis)
                if not receipt["browser"]["passed"]:
                    receipt.update(verdict="failed", reason="browser_job_failed")
        except RUNTIME_ERRORS as exc:
            receipt.update(verdict="inconclusive", reason="runtime_unavailable", error=str(exc))
        finally:
            if "api_container" in receipt:
                try:
                    receipt["logs"] = lima.guest("sh", "-c", 'exec nerdctl logs --tail 20 "$1" 2>&1',
                                                  "sh", api)[-16000:]
                except RUNTIME_ERRORS as exc:
                    receipt["diagnostics_error"] = str(exc)
            assess_cleanup(receipt, cleanup(lima, receipt))
            record(path, receipt)
        return receipt
