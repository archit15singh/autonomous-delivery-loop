"""Run a local headless Codex session with a role-specific tool policy."""
import json
import os
from pathlib import Path
import signal
import subprocess
from tempfile import NamedTemporaryFile

from .codex_usage import capture_sessions
from .run_state import record

MAX_SUBAGENTS = 4
TIMEOUT_EXIT = 124

_EXTERNAL_FEATURES = (
    "apps", "plugins", "hooks", "browser_use", "browser_use_external",
    "in_app_browser", "computer_use", "image_generation", "remote_plugin",
    "workspace_dependencies", "artifact", "auth_elicitation",
)
_JUDGE_FEATURES = (
    "shell_tool", "unified_exec", "view_image", "sleep_tool", "goals",
    "js_repl", "tool_suggest", "skill_search", "undo", "code_mode", "code_mode_only",
    "default_mode_request_user_input", "request_permissions_tool",
    "agent_message_board", "agent_message_board_mcp", "send_message_to_user_async",
)


def require_success(status, timeout, events):
    if status == TIMEOUT_EXIT:
        raise TimeoutError(f"Codex exceeded the {timeout}s budget. See {events}")
    if status != 0:
        raise RuntimeError(f"Codex exited with status {status}. See {events}")


def check_local_runner(env=None):
    for settings in (os.environ, env or {}):
        if (settings.get("GITHUB_ACTIONS", "").lower() == "true"
                and settings.get("RUNNER_ENVIRONMENT") != "self-hosted"):
            raise ValueError("local Codex is disabled on GitHub-hosted Actions")


def check_subagents(subagents, role="writer"):
    if type(subagents) is not int or not 0 <= subagents <= MAX_SUBAGENTS:
        raise ValueError(f"subagents must be an integer from 0 to {MAX_SUBAGENTS}")
    if subagents and role != "writer":
        raise ValueError("only a writer can use subagents")
    return subagents


def _private_log(path):
    # Publish a fresh 0600 inode even when a prior log or a symlink exists.
    log = NamedTemporaryFile(dir=path.parent, delete=False)
    try:
        os.replace(log.name, path)
    except OSError:
        log.close()
        Path(log.name).unlink(missing_ok=True)
        raise
    return log


def _check_judge_events(events):
    with events.open(encoding="utf-8") as stream:
        for line in stream:
            event = json.loads(line)
            if (event["type"].startswith("item.")
                    and event["item"]["type"] not in {"agent_message", "reasoning"}):
                raise ValueError("judge attempted to use a tool")


def grader_permissions(protected):
    roots = {str(Path(path).resolve()): "deny" for path in protected}
    if not roots or "/" in roots:
        raise ValueError("select concrete protected grader paths")
    entries = ", ".join(f"{json.dumps(key)} = {json.dumps(value)}" for key, value in sorted(roots.items()))
    return ["-c", 'permissions.adl_eval.extends=":workspace"',
            "-c", "permissions.adl_eval.filesystem={" + entries + "}",
            "-c", "permissions.adl_eval.network.enabled=false"]


def run_codex(*, cwd, prompt, model, timeout, events, role, result=None, schema=None,
              env=None, subagents=0, launcher=None, protected=()):
    """Return the local process exit status, or 124 after killing a timed-out group."""
    check_local_runner(env)
    if role not in ("writer", "reviewer", "judge"):
        raise ValueError(f"unknown local Codex role: {role}")
    check_subagents(subagents, role)
    events = Path(events).absolute()
    stderr = events.with_suffix(".stderr")
    sessions = events.with_suffix(".sessions.json")
    paths = [events, stderr, sessions, *(Path(p).absolute() for p in (schema, result) if p is not None)]
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("Codex events, stderr, result and schema must use distinct paths")
    args = [
        "codex", "-a", "never", "exec", "--ignore-user-config",
        "--sandbox", "workspace-write" if role == "writer" else "read-only",
        "--json", "-c", 'web_search="disabled"',
        "-c", "mcp_servers={}", "-c", "agents={}",
        "-c", "sandbox_workspace_write.writable_roots=[]",
        "-c", "sandbox_workspace_write.network_access=false",
        "-c", "sandbox_workspace_write.exclude_tmpdir_env_var=true",
        "-c", "sandbox_workspace_write.exclude_slash_tmp=true",
        "-c", 'model_reasoning_effort="medium"',
        "--disable", "multi_agent_v2",
        "--enable" if subagents else "--disable", "multi_agent",
    ]
    if not subagents:
        args.append("--ephemeral")
    if model:
        args.extend(("--model", model))
    for feature in _EXTERNAL_FEATURES:
        args.extend(("--disable", feature))
    if subagents:
        prompt = ("For delegated tasks use fork_turns=none and give the child a self-contained brief. "
                  "Wait for each child before finishing.\n" + prompt)
        args.extend(("-c", "agents.max_depth=1", "-c", f"agents.max_threads={subagents}"))
    if role == "judge":
        args.extend(("--skip-git-repo-check", "-c", "project_doc_max_bytes=0"))
        for feature in _JUDGE_FEATURES:
            args.extend(("--disable", feature))
    if schema is not None:
        args.extend(("--output-schema", str(Path(schema).absolute())))
    if result is not None:
        args.extend(("--output-last-message", str(Path(result).absolute())))
    if subagents:
        record(sessions, {"status": "pending"})
    elif sessions.exists():
        raise ValueError("use a fresh transcript path for a non-delegated attempt")
    if protected:
        if role != "writer" or subagents or launcher is not None:
            raise ValueError("grader protection applies to native writer trials")
        start = args.index("--sandbox")
        del args[start:start + 2]
        args.extend(("-c", 'default_permissions="adl_eval"', *grader_permissions(protected)))
    if launcher is not None:
        if not Path(launcher).is_absolute() or role != "writer" or subagents or schema is not None or result is not None:
            raise ValueError("isolated launchers require an absolute path and a plain writer session")
        args.insert(0, str(launcher))
        env = {"PATH": os.defpath, "HOME": str(Path.home())}
    with _private_log(events) as out, _private_log(stderr) as err:
        with subprocess.Popen([*args, "-"], cwd=cwd, env=env, stdin=subprocess.PIPE,
                              stdout=out, stderr=err, start_new_session=True) as proc:
            try:
                proc.communicate(prompt.encode("utf-8"), timeout=timeout)
            except BaseException as exc:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                if isinstance(exc, subprocess.TimeoutExpired):
                    return TIMEOUT_EXIT
                raise
    if subagents:
        capture_sessions(events, env)
    if role == "judge" and proc.returncode == 0:
        _check_judge_events(events)
    return proc.returncode
