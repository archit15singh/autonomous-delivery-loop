"""Start the candidate as nobody and run the committed contract on guest loopback."""
import ctypes
from hashlib import sha256
import json
import os
from pathlib import Path
import resource
import signal
import socket
import subprocess
import sys
import time

from delivery.verify import Contract, fetch, verify


INPUT = Path("/run/input")
APP_USER = 65534
CGROUP = Path("/run/cgroup")


def app_privileges():
    # Preserve the dropped privileges across exec, including setuid programs.
    if ctypes.CDLL(None).prctl(38, 1, 0, 0, 0) != 0:
        raise OSError("cannot set no_new_privs")
    os.setgroups([])
    os.setgid(APP_USER)
    os.setuid(APP_USER)


def main():
    job = json.loads((INPUT / "job.json").read_text())
    source = INPUT / "service.py"
    contract = Contract.read(INPUT / "contract.json", product=True)
    if (sha256(source.read_bytes()).hexdigest() != job["source_sha256"]
            or contract.digest != job["contract_sha256"]):
        raise ValueError("guest inputs disagree with the host job")
    interfaces = [name for _, name in socket.if_nameindex()]
    if interfaces != ["lo"] or not os.statvfs(INPUT).f_flag & os.ST_RDONLY or not os.statvfs("/").f_flag & os.ST_RDONLY:
        raise ValueError("guest requires loopback-only networking and read-only drives")

    (CGROUP / "cgroup.subtree_control").write_text("+cpu")
    app_group = CGROUP / "app"
    app_group.mkdir()
    quota = f"{round(job['cpu_limit'] * 100000)} 100000"
    (app_group / "cpu.max").write_text(quota)

    def start_app():
        (app_group / "cgroup.procs").write_text(str(os.getpid()))
        limit = job["memory_mb"] * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
        app_privileges()

    port = str(job["port"])
    revision, deployment = job["revision"], job["deployment"]
    subprocess.Popen([sys.executable, "-IB", str(source)], preexec_fn=start_app,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     cwd="/", env={"PATH": "/usr/local/bin:/bin", "HOME": "/",
                                   "ADL_REVISION": revision, "ADL_DEPLOYMENT": deployment,
                                   "PORT": port, "ADL_PORT": port, "ADL_HOST": "127.0.0.1", "HOST": "127.0.0.1"})
    origin = f"http://127.0.0.1:{port}"
    for _ in range(30):
        if fetch(origin, "/_revision").get("status") == 200:
            break
        time.sleep(0.1)
    report = verify(contract, origin, revision, deployment, {
        "status": "passed", "source": "firecracker_exact_source", "revision": revision,
        "deployment": deployment, "artifact_sha256": job["source_sha256"],
    })
    report["guest"] = {"network_interfaces": interfaces, "read_only_drives": True, "app_uid": APP_USER,
                       "memory_mb": job["memory_mb"], "cpu_quota": (app_group / "cpu.max").read_text().strip()}
    print("ADL_FIRECRACKER_RESULT " + json.dumps(report), flush=True)
    while True:
        signal.pause()


if __name__ == "__main__":
    main()
