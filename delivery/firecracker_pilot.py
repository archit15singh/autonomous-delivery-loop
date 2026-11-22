"""Boot and verify one reviewed product in a disposable, offline Linux microVM."""
import fcntl
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import platform
import selectors
import shutil
import stat
import subprocess
import sys
import time
from uuid import UUID, uuid4

from .factory_definition import running_definition
from .revisions import git
from .run_state import lock, record
from .runtime_checks import ROOT, RUNTIME_ERRORS, assess_cleanup, assess_observation


# KVM_GET_API_VERSION also detects KVM devices that exist but cannot be used.
KVM_GET_API_VERSION = 0xAE00
RESULT = b"ADL_FIRECRACKER_RESULT "
MAX_SERIAL = 2 * 1024 * 1024
LAUNCH = """
import ctypes, os, signal, sys
parent = os.getppid()
if ctypes.CDLL(None).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
    sys.exit("could not set parent-death signal")
if os.read(0, 1) != b"x" or os.getppid() != parent:
    sys.exit("operator disappeared before launch")
os.execv(sys.argv[1], sys.argv[1:])
"""


def preflight(assets):
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "aarch64"}:
        raise ValueError("Firecracker requires an x86_64 or aarch64 Linux host with /dev/kvm")
    try:
        with open("/dev/kvm", "r+b", buffering=0) as device:
            if not stat.S_ISCHR(os.fstat(device.fileno()).st_mode) or fcntl.ioctl(device, KVM_GET_API_VERSION) != 12:
                raise OSError("unexpected KVM device or API version")
    except OSError as exc:
        raise ValueError(f"Firecracker requires usable read/write /dev/kvm: {exc}") from exc
    if os.geteuid() == 0:
        raise ValueError("run the Firecracker evaluator as a dedicated unprivileged user")
    if not shutil.which("mke2fs"):
        raise ValueError("install e2fsprogs on the Firecracker host")
    files = {name: (assets / name).resolve(strict=True) for name in ("firecracker", "vmlinux", "rootfs.ext4")}
    digests = {}
    for name, path in files.items():
        if not path.is_file():
            raise ValueError(f"expected regular Firecracker asset: {name}")
        with path.open("rb") as file:
            digest = sha256()
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
            digests[name] = digest.hexdigest()
    if not os.access(files["firecracker"], os.X_OK):
        raise ValueError("Firecracker executable lacks execute permission")
    return files, digests


def build_payload(scratch, product, policy, deployment):
    payload = scratch / "input"
    judge = payload / "delivery"
    judge.mkdir(parents=True)
    (payload / "service.py").write_bytes(product.source)
    raw = product.contract_path.read_bytes()
    if sha256(raw).hexdigest() != product.contract.digest:
        raise ValueError("product contract changed after selection")
    (payload / "contract.json").write_bytes(raw)
    (payload / "job.json").write_text(json.dumps({
        "revision": product.revision, "deployment": deployment, "port": product.port,
        "source_sha256": product.identity["source_sha256"], "contract_sha256": product.contract.digest,
        "memory_mb": product.memory_mb, "cpu_limit": product.cpu_limit,
    }))
    for name in ("__init__.py", "verify.py", "impact.py"):
        (judge / name).write_bytes(git("show", f"{policy}:delivery/{name}", cwd=ROOT))
    (payload / "judge.py").write_bytes(git("show", f"{policy}:verification/firecracker-judge.py", cwd=ROOT))
    image = scratch / "input.ext4"
    with image.open("wb") as file:
        file.truncate(8 * 1024 * 1024)
    subprocess.run(["mke2fs", "-q", "-F", "-t", "ext4", "-d", str(payload), str(image)],
                   check=True, timeout=15, capture_output=True)
    return image


def vm_config(files, image, product):
    console = "ttyS0" if platform.machine() == "x86_64" else "ttyAMA0"
    return {
        "boot-source": {
            "kernel_image_path": str(files["vmlinux"]),
            "boot_args": f"console={console} reboot=k panic=1 pci=off ro init=/sbin/adl-init",
        },
        "drives": [
            {"drive_id": "rootfs", "path_on_host": str(files["rootfs.ext4"]),
             "is_root_device": True, "is_read_only": True},
            {"drive_id": "input", "path_on_host": str(image),
             "is_root_device": False, "is_read_only": True},
        ],
        "machine-config": {"vcpu_count": math.ceil(product.cpu_limit), "mem_size_mib": product.memory_mb + 96},
    }


def observe(process, deadline, serial):
    pending = b""
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while time.monotonic() < deadline and selector.select(max(0, deadline - time.monotonic())):
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                raise ValueError("microVM exited before trusted guest evidence")
            if serial.tell() + len(chunk) > MAX_SERIAL:
                raise ValueError("microVM serial output exceeded the evidence limit")
            serial.write(chunk)
            lines = (pending + chunk).split(b"\n")
            pending = lines.pop()
            for line in lines:
                if line.startswith(RESULT):
                    return json.loads(line[len(RESULT):])
    raise TimeoutError("microVM did not return trusted guest evidence before the deadline")


def cleanup(state, receipt):
    marker = state / receipt["deployment"]
    pid = receipt.get("pid")
    if pid and receipt["host_boot"] == Path("/proc/sys/kernel/random/boot_id").read_text().strip():
        try:
            if os.fsencode(str(marker / "vm.json")) in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0"):
                return {"status": "unconfirmed", "error": "the owned microVM process is still active"}
        except (FileNotFoundError, ProcessLookupError):
            pass
    if marker.exists():
        shutil.rmtree(marker)
    return {"status": "confirmed"}


def run(state, *, product=None, assets=None, cleanup_only=False):
    path = state / "runtime.json"
    if cleanup_only:
        with lock(state):
            receipt = json.loads(path.read_text())
            if receipt["cleanup"]["status"] != "confirmed":
                deployment = receipt["deployment"]
                try:
                    if str(UUID(deployment)) != deployment:
                        raise ValueError("invalid Firecracker deployment identity")
                    receipt["cleanup"] = cleanup(state, receipt)
                except RUNTIME_ERRORS as exc:
                    receipt["cleanup"] = {"status": "unconfirmed", "error": str(exc)}
                record(path, receipt)
            return receipt

    files, digests = preflight(assets)
    policy = running_definition(ROOT)
    with lock(state):
        if path.exists():
            raise ValueError("provide a fresh state directory for each Firecracker run")
        started = time.monotonic()
        deployment = str(uuid4())
        scratch = state / deployment
        receipt = {
            "product": product.identity, "revision": product.revision, "deployment": deployment,
            "policy_revision": policy["revision"], "policy_sha256": policy["sha256"],
            "assets_sha256": digests, "host_boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "verdict": "inconclusive", "reason": "interrupted", "cleanup": {"status": "pending"},
        }
        record(path, receipt)
        process = None
        timing = receipt["timing_ms"] = {}
        try:
            scratch.mkdir(mode=0o700)
            image = build_payload(scratch, product, policy["revision"], deployment)
            config = scratch / "vm.json"
            config.write_text(json.dumps(vm_config(files, image, product)))
            boot = time.monotonic()
            timing["prepare"] = round(1000 * (boot - started))
            process = subprocess.Popen([sys.executable, "-c", LAUNCH, str(files["firecracker"]),
                                        "--no-api", "--config-file", str(config)],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       env={"PATH": "/usr/bin:/bin", "LANG": "C"})
            receipt["pid"] = process.pid
            record(path, receipt)
            process.stdin.write(b"x")
            process.stdin.close()
            with (state / "serial.log").open("wb") as serial:
                observation = observe(process, boot + 45, serial)
            timing["boot_and_verify"] = round(1000 * (time.monotonic() - boot))
            if (not isinstance(observation, dict) or observation.get("revision") != product.revision
                    or observation.get("deployment") != deployment
                    or observation.get("contract_sha256") != product.contract.digest
                    or observation.get("ci", {}).get("artifact_sha256") != product.identity["source_sha256"]
                    or observation.get("verdict") not in {"verified", "failed", "inconclusive"}
                    or not isinstance(observation.get("reason"), str)):
                raise ValueError("guest result does not match the reviewed product inputs")
            assess_observation(receipt, observation)
        except RUNTIME_ERRORS as exc:
            reason = "runtime_timeout" if isinstance(exc, TimeoutError) else "runtime_error"
            receipt.update(reason=reason, error=str(exc))
        finally:
            teardown = time.monotonic()
            try:
                if process is not None:
                    if process.stdin and not process.stdin.closed:
                        process.stdin.close()
                    process.kill()
                    process.wait(timeout=5)
                    process.stdout.close()
                result = cleanup(state, receipt)
            except RUNTIME_ERRORS as exc:
                result = {"status": "unconfirmed", "error": str(exc)}
            assess_cleanup(receipt, result)
            timing.update(cleanup=round(1000 * (time.monotonic() - teardown)),
                          total=round(1000 * (time.monotonic() - started)))
            record(path, receipt)
        return receipt
