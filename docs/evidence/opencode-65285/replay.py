"""Send a bounded synthetic tool script via a throwaway OpenCode server."""
import base64
import http.server
import json
import os
import pty
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time
import pyte
import urllib.error
import urllib.request
from pathlib import Path

source, bun, output, capture_skill = map(lambda value: Path(value).resolve(), sys.argv[1:])
sys.path.insert(0, str(capture_skill / "scripts"))
from capture import _set_winsize, render_png

output.mkdir(parents=True, exist_ok=True)
calls = 260
auth = "Basic " + base64.b64encode(b"opencode:fixture-password").decode()
requests = []
pings = []

class Fixture(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path != "/ping":
            self.send_error(404)
            return
        pings.append(1)
        self.send_response(204)
        self.end_headers()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        offered = [tool.get("function", tool).get("name") for tool in body.get("tools", [])]
        messages = body.get("messages", [])
        tool_finished = any(message.get("role") == "tool" for message in messages)
        requests.append({"offered_execute": "execute" in offered, "tool_finished": tool_finished})
        if "execute" in offered and not tool_finished:
            url = f"http://127.0.0.1:{self.server.server_port}/ping"
            code = f'for (let i = 0; i < {calls}; i++) await fetch("{url}"); return "COMPLETED {calls}"'
            delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": "call_fixture",
                     "type": "function", "function": {"name": "execute", "arguments": json.dumps({"code": code})}}]}
            finish = "tool_calls"
        else:
            delta = {"role": "assistant", "content": "FIXTURE_COMPLETE"}
            finish = "stop"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for choice in ({"delta": delta, "finish_reason": None}, {"delta": {}, "finish_reason": finish}):
            item = {"id": "fixture-id", "object": "chat.completion.chunk", "created": 1,
                    "model": "fixture", "choices": [{"index": 0, **choice}]}
            self.wfile.write(f"data: {json.dumps(item)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")

def request(endpoint, route, payload=None, *, raw=False):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(endpoint + route, data, headers={
        "Authorization": auth, "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            result = response.read()
            return result if raw else json.loads(result)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"{route} returned {error.code}: {error.read().decode()}") from error

def capture_tui(mode, endpoint, session_id, env, project):
    from PIL import Image

    config = Path(env["XDG_CONFIG_HOME"]) / "opencode"
    config.mkdir(parents=True, exist_ok=True)
    (config / "cli.json").write_text(json.dumps({
        "session": {"verbosity": mode},
        "animations": False,
        "tabs": {"enabled": False},
    }))
    rows, cols = (155 if mode == "high" else 28), 100
    screen = pyte.Screen(cols, rows)
    stream = pyte.ByteStream(screen)
    master, slave = pty.openpty()
    _set_winsize(slave, rows, cols)
    proc = subprocess.Popen(
        [str(bun), "run", "--preload", str(source / "packages/cli/node_modules/@opentui/solid/scripts/preload.js"),
         str(source / "packages/cli/src/index.ts"), "--server", endpoint, "--session", session_id],
        cwd=project, env={**env, "TERM": "xterm-256color", "COLORTERM": "truecolor"},
        stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
    )
    os.close(slave)
    raw = bytearray()
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            sockets, _, _ = select.select([master], [], [], 0.1)
            if sockets:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    break
                if not data:
                    break
                raw.extend(data)
                stream.feed(data)
            text = "\n".join(screen.display)
            if "FIXTURE_COMPLETE" in text and (mode == "low" or "fetch" in text):
                break
        (output / f"{mode}.screen.txt").write_text(text)
        assert "FIXTURE_COMPLETE" in text, text
        assert render_png(screen, output / f"{mode}.png")
        if mode == "high":
            # Crop the captured terminal to its first thirteen lines.
            with Image.open(output / f"{mode}.png") as image:
                image.crop((0, 0, image.width, 13 * ((image.height - 16) // rows) + 16)).save(output / "high.png")
        snippet = [line.rstrip() for line in screen.display if "tools" in line or "calls omitted" in line]
        print(f"tui_{mode}={snippet}")
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=2)
        except ProcessLookupError:
            pass
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=8)
        finally:
            os.close(master)


with tempfile.TemporaryDirectory(prefix="adl-tool-rows.") as tmp,         http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fixture) as remote:
    root = Path(tmp)
    project = root / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (project / "opencode.json").write_text(json.dumps({
        "model": "loopback/fixture",
        "permission": {"webfetch": "allow"},
        "provider": {"loopback": {"npm": "@ai-sdk/openai-compatible", "name": "Fixture",
                                  "options": {"baseURL": f"http://127.0.0.1:{remote.server_port}/v1",
                                              "apiKey": "fixture"},
                                  "models": {"fixture": {"name": "Fixture",
                                             "limit": {"context": 8192, "output": 256},
                                             "tool_call": True}}}}
    }))
    env = {
        "HOME": str(root / "home"), "PATH": f"{bun.parent}:/usr/bin:/bin:/usr/sbin:/sbin",
        "XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data"),
        "XDG_STATE_HOME": str(root / "state"), "XDG_CACHE_HOME": str(root / "cache"),
        "OPENCODE_PASSWORD": "fixture-password", "OPENCODE_DISABLE_MODELS_FETCH": "1",
        "OPENCODE_DISABLE_AUTOUPDATE": "1", "OPENCODE_DISABLE_CLAUDE_CODE": "1",
        "OPENCODE_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1",
    }
    threading.Thread(target=remote.serve_forever, daemon=True).start()
    with (root / "server.log").open("wb") as error_log:
        server = subprocess.Popen(
            [str(bun), "run", "--preload", str(source / "packages/cli/node_modules/@opentui/solid/scripts/preload.js"),
             str(source / "packages/cli/src/index.ts"), "serve", "--stdio", "--port", "0"],
            env=env, cwd=project, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=error_log)
        try:
            if not select.select([server.stdout], [], [], 12)[0]:
                raise TimeoutError("OpenCode readiness")
            endpoint = json.loads(server.stdout.readline())["url"]
            session_id = request(endpoint, "/api/session", {"location": {"directory": str(project)}})["data"]["id"]
            request(endpoint, f"/api/session/{session_id}/prompt", {"text": "Run the local fixture."})
            until = time.monotonic() + 20
            while time.monotonic() < until:
                wire = request(endpoint, f"/api/session/{session_id}/message", raw=True)
                if b"FIXTURE_COMPLETE" in wire and any(item["tool_finished"] for item in requests):
                    break
                time.sleep(0.1)
            page = json.loads(wire)
            states = [
                part["state"] for message in page["data"] for part in message.get("content", [])
                if part.get("name") == "execute" and "state" in part
            ]
            assert len(states) == 1 and states[0]["status"] == "completed", (requests, wire[:2500])
            meta = states[0]["metadata"]
            observed = len(meta["toolCalls"])
            omitted = meta.get("toolCallsOmitted", 0)
            assert len(pings) == calls and f"COMPLETED {calls}".encode() in wire, (requests, len(pings), wire[:2500])
            revision = subprocess.check_output(["git", "-C", source, "rev-parse", "HEAD"], text=True).strip()
            metadata_bytes = len(json.dumps(meta, separators=(",", ":")).encode())
            print(f"revision={revision} served={len(pings)} persisted_rows={observed} "
                  f"omitted={omitted} metadata_bytes={metadata_bytes} message_page_bytes={len(wire)}")
            for mode in ("low", "high"):
                capture_tui(mode, endpoint, session_id, env, project)
        finally:
            server.terminate()
            server.wait(timeout=12)
            remote.shutdown()
