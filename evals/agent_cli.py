"""Thin adapters for operator-isolated, externally installed coding CLIs."""
import os
from pathlib import Path
import signal
import subprocess

from delivery.local_codex import TIMEOUT_EXIT, _private_log, check_local_runner


AGENTS = ("codex", "opencode", "claude")


def external_command(agent, model, prompt):
    if agent == "opencode":
        return ["opencode", "run", "--standalone", "--format", "json", "--model", model, "--", prompt]
    if agent == "claude":
        return ["claude", "--print", "--output-format", "stream-json", "--verbose",
                "--permission-mode", "acceptEdits", "--model", model, "--", prompt]
    raise ValueError("select opencode or claude for the external CLI adapter")


def run_external(*, agent, model, launcher, prompt, tree, events, timeout, env):
    check_local_runner(env)
    if launcher is None or not Path(launcher).is_absolute() or not model:
        raise ValueError("external trials require an absolute isolated-worker executable and a model ID")
    events = Path(events)
    # The operator's launcher maps the working tree into an isolated environment
    # and runs the argv. It must not expose host credentials or the verifier store.
    args = [str(launcher), *external_command(agent, model, prompt)]
    launcher_env = {"PATH": os.defpath, "HOME": str(Path.home())}
    with _private_log(events) as out, _private_log(events.with_suffix(".stderr")) as err:
        with subprocess.Popen(args, cwd=tree, env=launcher_env, stdin=subprocess.DEVNULL,
                              stdout=out, stderr=err, start_new_session=True) as proc:
            try:
                return proc.wait(timeout)
            except BaseException as exc:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                if isinstance(exc, subprocess.TimeoutExpired):
                    return TIMEOUT_EXIT
                raise
