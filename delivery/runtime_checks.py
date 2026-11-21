"""Shared runtime verification policy for the disposable execution backends."""
from datetime import datetime, timezone
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts/compose-pilot.json"
PYTHON = "docker.io/library/python:3.12-alpine@sha256:c5ba3deef00c7758561a0f03c26f44f10589263d40e732b8748e0d1f38f6dd89"
REDIS_DIGEST = "sha256:1273af45b299d2b8b60d0e400d90aa6c2c5b1794f01d6a7ca60ff3ba6e65efb5"
RUNTIME_ERRORS = (OSError, ValueError, subprocess.SubprocessError)


def now():
    return datetime.now(timezone.utc).isoformat()


def assess_observation(receipt, observation, read_counter=None):
    """Preserve the HTTP result even when independent Redis readback fails."""
    receipt.update(observation=observation, verdict=observation["verdict"], reason=observation["reason"])
    if observation["verdict"] == "verified" and read_counter is not None:
        receipt["redis_counter"] = read_counter()
        if receipt["redis_counter"] != "2":
            receipt.update(verdict="failed", reason="redis_readback_mismatch")


def assess_cleanup(receipt, cleanup):
    receipt["cleanup"] = cleanup
    if cleanup["status"] != "confirmed":
        receipt.update(verdict="inconclusive", reason="cleanup_unconfirmed")
