"""Run an exact Git archive in an ephemeral HTTP staging environment."""
from hashlib import sha256
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory

from .verify import Contract, verify


def stage(contract_path, archive, ci_path, revision, deployment):
    contract = Contract.read(contract_path)
    ci = json.loads(ci_path.read_text())
    if not isinstance(ci, dict) or sha256(archive.read_bytes()).hexdigest() != ci.get("artifact_sha256"):
        raise ValueError("artifact digest does not match CI evidence")
    with TemporaryDirectory(prefix="adl-stage-") as folder:
        root = Path(folder)
        with tarfile.open(archive) as package:
            package.extractall(root, filter="data")
        env = {**os.environ, "ADL_REVISION": revision, "ADL_DEPLOYMENT": deployment}
        with subprocess.Popen(
            [sys.executable, "-I", str(root / "pilot/service.py"), "--port", "0"],
            cwd=root, stdout=subprocess.PIPE, text=True, env=env,
        ) as service:
            try:
                readable, _, _ = select.select([service.stdout], [], [], 5)
                port = service.stdout.readline().strip() if readable else ""
                origin = f"http://127.0.0.1:{int(port)}" if port.isdigit() else "http://127.0.0.1:1"
                return verify(contract, origin, revision, deployment, ci)
            finally:
                service.terminate()
                try:
                    service.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    service.kill()
                    service.wait()
