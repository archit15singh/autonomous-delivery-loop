"""Exercise the owned Compose lifecycle on a disposable Docker runner."""
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from delivery import compose_pilot as pilot

socket = Path("/var/run/docker.sock")
revision = sys.argv[1]
root = Path(sys.argv[2]).resolve()


def run(name, **options):
    return pilot.run(socket, root / name, revision, **options)


def assert_clean(receipt):
    assert receipt["cleanup"]["status"] == "confirmed", receipt
    assert not any(receipt["cleanup"]["remaining"].values()), receipt


if len(sys.argv) > 3:
    with patch.object(pilot.Compose, "observe", side_effect=lambda *_: os._exit(76)):
        run("interrupted")
    raise AssertionError("expected an interrupted run")

# Simulate a lost reply after a real Compose start. Reissuing up must reuse the same project.
start = pilot.start
starts = []


def lose_first_reply(stack):
    start(stack)
    starts.append(stack.project)
    if len(starts) == 1:
        raise subprocess.TimeoutExpired("compose up", 45)


root.mkdir(parents=True, exist_ok=True)
with patch.object(pilot, "start", side_effect=lose_first_reply):
    ready = run("retry", retry_start=True, index=root / "index")
assert ready["verdict"] == "verified", ready
assert starts == [ready["deployment"]] * 2 and len(ready["recovery"]) == 1
assert [probe["passed"] for probe in ready["observation"]["probes"]] == [True, True, True]
assert_clean(ready)

verify = pilot.verify


def wrong_revision(contract, origin, revision, deployment, ci):
    wrong = "0" * 40
    return verify(contract, origin, wrong, deployment, {**ci, "revision": wrong})


with patch.object(pilot, "verify", side_effect=wrong_revision):
    stale = run("wrong-revision")
assert stale["reason"] == "wrong_deployment", stale
assert_clean(stale)

observe = pilot.Compose.observe


def lose_redis(stack, contract, image):
    stack.compose("stop", "redis")
    return observe(stack, contract, image)


with patch.object(pilot.Compose, "observe", lose_redis):
    failed = run("redis-unavailable", retry_start=True)
assert failed["verdict"] == "failed" and not failed["recovery"], failed
assert failed["observation"]["probes"][1]["observed"]["status"] == 503
assert_clean(failed)

with patch.object(pilot.Compose, "cleanup", side_effect=ValueError("simulated teardown interruption")):
    uncertain = run("cleanup-unconfirmed")
assert uncertain["observation"]["verdict"] == "verified"
assert uncertain["verdict"] == "inconclusive" and uncertain["reason"] == "cleanup_unconfirmed"
assert_clean(run("cleanup-unconfirmed", cleanup_only=True))

interrupted = subprocess.run([sys.executable, __file__, revision, str(root), "interrupt"])
assert interrupted.returncode == 76
state = root / "interrupted"
receipt = json.loads((state / "runtime.json").read_text())
assert receipt["reason"] == "interrupted" and receipt["cleanup"]["status"] == "pending"
stack = pilot.Compose(socket.resolve(), state, receipt)
assert len(stack.resources()["container"]) == 2
redis_image = stack.compose("config", "--images").splitlines()
redis_image = next(image for image in redis_image if image.startswith("redis@"))
neighbor = stack.docker("run", "-d", "--rm", "--tmpfs", "/data", redis_image)
try:
    reconciled = run("interrupted", cleanup_only=True)
    assert_clean(reconciled)
    assert reconciled["verdict"] == "inconclusive"
    assert stack.docker("container", "inspect", "--format", "{{.State.Running}}", neighbor) == "true"
finally:
    stack.docker("stop", neighbor)
print("Compose retry, revision, Redis outage and interrupted cleanup checks passed")
