"""Measure actual PTY sizes across Herdr App stack controls in an isolated session."""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

app_binary, core_binary, expected = sys.argv[1:]
app_binary, core_binary = Path(app_binary).resolve(), Path(core_binary).resolve()

with tempfile.TemporaryDirectory(prefix="ha.", dir="/tmp") as temp:
    root = Path(temp)
    app_home = root / "app"
    (app_home / "layouts").mkdir(parents=True)
    layout = {
        "id": "dock", "type": "stack", "active": "first",
        "children": [
            {"id": "first", "type": "block", "content": {"terminal": "dock-1"}},
            {"id": "second", "type": "block", "content": {"terminal": "dock-2"}},
        ],
    }
    (app_home / "layouts/probe.json").write_text(json.dumps(layout))
    (app_home / "shared.json").write_text(json.dumps({"layout": "probe", "frame.welcomed": "probe"}))
    env = {
        "HOME": temp, "XDG_CONFIG_HOME": f"{temp}/cfg", "XDG_STATE_HOME": f"{temp}/state",
        "XDG_RUNTIME_DIR": f"{temp}/run", "HC_SESSION": "adl1263", "HC_SOCKET": f"{temp}/hc.sock",
        "HERDR_APP_HOME": str(app_home), "HERDR_CORE_DIRS": str(core_binary.parent),
        "PATH": f"{core_binary.parent}:/usr/bin:/bin:/usr/sbin:/sbin", "SHELL": "/bin/sh",
        "SSH_CONNECTION": "127.0.0.1 10022 127.0.0.1 22",
        "HERDR_TELEMETRY": "0", "DO_NOT_TRACK": "1",
    }

    if "DISPLAY" in os.environ:
        env["DISPLAY"] = os.environ["DISPLAY"]
    if "XAUTHORITY" in os.environ:
        env["XAUTHORITY"] = os.environ["XAUTHORITY"]
    env["HERDR_APP_NO_SOUND"] = "1"

    def call(binary, *args):
        result = subprocess.run([binary, *args], env=env, cwd=root, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=22)
        if result.returncode or not result.stdout.strip():
            raise RuntimeError(f"{args}: exit={result.returncode}, {result.stdout} {result.stderr}")
        return json.loads(result.stdout)

    def until(read, condition):
        until_time = time.monotonic() + 6
        while True:
            value = read()
            if condition(value):
                return value
            if time.monotonic() >= until_time:
                raise RuntimeError(f"condition not met, got {value!r}")
            time.sleep(0.1)

    def remains(name, expected_size):
        for _ in range(10):
            assert size(name) == expected_size, (name, size(name), expected_size)
            time.sleep(0.1)

    def size(name):
        result = call(core_binary, "get", name, "--json")
        return result["cols"], result["rows"]

    def control(name, **args):
        return call(app_binary, "do", name, json.dumps(args))

    with (root / "app.log").open("wb") as app_log, (root / "holder.log").open("wb") as holder_log:
        holder_socket = root / "hc.holder.fixture.sock"
        holder = subprocess.Popen([core_binary, "hold", "--socket", holder_socket], env=env, cwd=root,
                                  stdin=subprocess.DEVNULL, stdout=holder_log, stderr=holder_log,
                                  start_new_session=True)
        app = None
        try:
            until(holder_socket.exists, bool)
            call(core_binary, "server", "start")
            for name in ["dock-1", "dock-2"]:
                call(core_binary, "run", "--bg", "--name", name, "--json", "--", "/bin/sh", "-c", "sleep 120")
            headless = (200, 120)
            assert size("dock-1") == size("dock-2") == headless
            app = subprocess.Popen([app_binary], env=env, cwd=root, stdin=subprocess.DEVNULL,
                                   stdout=app_log, stderr=app_log, start_new_session=True)
            until((app_home / "herdr-app.sock").exists, bool)
            status = call(app_binary, "status")
            assert status["layout"] == "probe", status
            first_visible = until(lambda: size("dock-1"), lambda dims: dims != headless)
            print(f"initial: dock-1={first_visible}, dock-2={size('dock-2')}", flush=True)
            control("layout.select", stack="dock", child="second")
            second_visible = until(lambda: size("dock-2"), lambda dims: dims != headless)
            expected_first = headless if expected == "before" else first_visible
            until(lambda: size("dock-1"), lambda dims: dims == expected_first)
            remains("dock-1", expected_first)
            print(f"switch: dock-1={size('dock-1')}, dock-2={second_visible}", flush=True)
            control("layout.hide", id="dock")
            expected_second = headless if expected == "before" else second_visible
            until(lambda: size("dock-2"), lambda dims: dims == expected_second)
            remains("dock-1", expected_first)
            remains("dock-2", expected_second)
            print(f"hide: dock-1={size('dock-1')}, dock-2={size('dock-2')}", flush=True)
            control("layout.show", id="dock")
            until(lambda: size("dock-2"), lambda dims: dims == second_visible)
            print(f"show: dock-1={size('dock-1')}, dock-2={size('dock-2')}", flush=True)
        except Exception:
            for log in root.rglob("*.log"):
                print(f"{log.name}: {log.read_text(errors='replace')[-1200:]}", file=sys.stderr)
            raise
        finally:
            if app is not None and app.poll() is None:
                app.terminate()
                try:
                    app.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    app.kill()
                    app.wait()
            if (root / "hc.sock").exists():
                subprocess.run([core_binary, "server", "stop"], env=env, cwd=root,
                               stdin=subprocess.DEVNULL, capture_output=True, timeout=20)
            if holder.poll() is None:
                holder.terminate()
                holder.wait(timeout=5)
