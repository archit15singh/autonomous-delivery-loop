"""Replay retry with a stale container and an injected Compose down failure."""
import asyncio
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from harbor.environments.docker.docker import DockerEnvironment
from harbor.models.task.config import EnvironmentConfig
from harbor.models.trial.paths import TrialPaths


def docker(*args: str, capture: bool = False) -> str:
    return subprocess.run(
        [os.environ["REAL_DOCKER"], *args], check=True, text=True,
        stdout=subprocess.PIPE if capture else None,
    ).stdout or ""


async def run(seed: bool, expect_recovery: bool) -> None:
    project = "adl2805-" + uuid.uuid4().hex[:12]
    stale = project + "-main-1"
    neighbor = project + "-neighbor-main-1"
    image = os.environ["REPLAY_IMAGE"]
    env_key = "ADL_FAIL_INITIAL_DOWN"
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env_dir = root / "environment"
            env_dir.mkdir()
            paths = TrialPaths(trial_dir=root / "trial")
            paths.mkdir()
            env = DockerEnvironment(
                environment_dir=env_dir,
                environment_name=project,
                session_id=project,
                trial_paths=paths,
                task_env_config=EnvironmentConfig(docker_image=image),
            )
            if seed:
                neighbor_id = docker(
                    "create", "--name", neighbor,
                    "--label", f"com.docker.compose.project={project}-neighbor",
                    image, "sleep", "3600", capture=True,
                ).strip()
                stale_id = docker(
                    "create", "--name", stale,
                    "--label", f"com.docker.compose.project={project}",
                    "--label", "com.docker.compose.service=retired",
                    "--label", "com.docker.compose.oneoff=False",
                    image, "sleep", "3600", capture=True,
                ).strip()
                os.environ[env_key] = project
            try:
                await env.start(force_build=False)
            except RuntimeError as exc:
                if not seed or expect_recovery:
                    raise
                assert "already in use" in str(exc) and stale in str(exc), exc
                print("seeded retry: exact Docker name conflict reproduced")
            else:
                assert not seed or expect_recovery, "seeded retry did not reproduce the issue"
                output = docker("exec", stale, "printf", "harbor-live", capture=True)
                assert output == "harbor-live", output
                if seed:
                    assert not docker("ps", "-aq", "--filter", f"id={stale_id}", capture=True)
                    print("seeded retry: stale container removed and replacement is runnable")
                else:
                    print("clean control: Harbor started and executed inside live Docker")
            finally:
                if seed:
                    surviving = docker("inspect", "--format", "{{.Id}}", neighbor, capture=True)
                    assert surviving.strip() == neighbor_id
                    print("neighbor control: different Compose project preserved")
                os.environ.pop(env_key, None)
                await env.stop(delete=False)
    finally:
        # The fixture owns both UUID-derived names even if Compose cleanup fails.
        for name in (stale, neighbor):
            ids = docker("ps", "-aq", "--filter", f"name=^/{name}$", capture=True).split()
            if ids:
                docker("rm", "-f", *ids)


async def main() -> None:
    phase = sys.argv[1]
    assert phase in {"base", "candidate"}, phase
    await run(seed=False, expect_recovery=False)
    await run(seed=True, expect_recovery=phase == "candidate")


if __name__ == "__main__":
    asyncio.run(main())
