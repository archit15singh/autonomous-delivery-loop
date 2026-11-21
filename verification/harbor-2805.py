"""Replay retry with a stale container and an injected Compose down failure."""
import asyncio
import os
import subprocess
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


async def run(seed: bool) -> None:
    project = "adl2805-" + uuid.uuid4().hex[:12]
    stale = project + "-main-1"
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
                docker(
                    "create", "--name", stale,
                    "--label", f"com.docker.compose.project={project}",
                    "--label", "com.docker.compose.service=retired",
                    "--label", "com.docker.compose.oneoff=False",
                    image, "sleep", "3600",
                )
                os.environ[env_key] = project
            try:
                await env.start(force_build=False)
            except RuntimeError as exc:
                if not seed:
                    raise
                assert "already in use" in str(exc) and stale in str(exc), exc
                print("seeded retry: exact Docker name conflict reproduced")
            else:
                assert not seed, "seeded retry did not reproduce the issue"
                output = docker("exec", stale, "printf", "harbor-live", capture=True)
                assert output == "harbor-live", output
                print("clean control: Harbor started and executed inside live Docker")
            finally:
                os.environ.pop(env_key, None)
                await env.stop(delete=False)
    finally:
        # The fixture owns this UUID-derived name even if Compose cleanup fails.
        ids = docker("ps", "-aq", "--filter", f"name=^/{stale}$", capture=True).split()
        if ids:
            docker("rm", "-f", *ids)


async def main() -> None:
    await run(seed=False)
    await run(seed=True)


if __name__ == "__main__":
    asyncio.run(main())
