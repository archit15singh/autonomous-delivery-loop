"""Replay stale prompt withdrawal through a throwaway OpenCode server."""
import base64
import http.server
import json
import select
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

source, bun = map(lambda value: Path(value).resolve(), sys.argv[1:3])
mode = sys.argv[3]
assert mode in {"cancel-only", "rewind"}
auth = "Basic " + base64.b64encode(b"opencode:fixture-password").decode()
requests = []

class Fixture(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        requests.append(body["messages"])
        delta = {"role": "assistant", "content": f"FIXTURE_REPLY_{len(requests)}"}
        finish = "stop"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for choice in ({"delta": delta, "finish_reason": None}, {"delta": {}, "finish_reason": finish}):
            item = {"id": "fixture-id", "object": "chat.completion.chunk", "created": 1,
                    "model": "fixture", "choices": [{"index": 0, **choice}]}
            self.wfile.write(f"data: {json.dumps(item)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")

def request(endpoint, route, payload=None, *, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(endpoint + route, data, method=method, headers={
        "Authorization": auth, "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            result = response.read()
            return response.status, json.loads(result) if result else None
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"{route} returned {error.code}: {error.read().decode()}") from error

with tempfile.TemporaryDirectory(prefix="adl-withdraw.") as tmp,         http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fixture) as remote:
    root = Path(tmp)
    project = root / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (project / "opencode.json").write_text(json.dumps({
        "model": "loopback/fixture",
        "providers": {"loopback": {"name": "Fixture",
            "env": ["LOOPBACK_API_KEY"],
            "package": "@opencode/ai/providers/openai-compatible",
            "settings": {"baseURL": f"http://127.0.0.1:{remote.server_port}/v1"},
            "models": {"fixture": {"name": "Fixture"}}}},
    }))
    env = {
        "HOME": str(root / "home"), "PATH": f"{bun.parent}:/usr/bin:/bin:/usr/sbin:/sbin",
        "LOOPBACK_API_KEY": "fixture", "XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data"),
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
            def json_data(route, payload=None):
                _, response = request(endpoint, route, payload)
                return response["data"]

            def wait_for_reply(after=None):
                for _ in range(150):
                    history = json_data(f"{session}/message")
                    if any(
                        row["id"] != after and row["type"] == "assistant"
                        and "FIXTURE_REPLY_" in json.dumps(row) and row.get("finish") == "stop"
                        for row in history
                    ):
                        return history
                    time.sleep(0.1)
                raise TimeoutError(f"missing model reply after {after}: {history!r}; provider requests={len(requests)}")

            session_id = json_data("/api/session", {"location": {"directory": str(project)}})["id"]
            session = f"/api/session/{session_id}"

            pending = json_data(f"{session}/prompt", {"text": "PENDING_CONTROL", "resume": False})
            assert any(item["id"] == pending["id"] for item in json_data(f"{session}/inbox"))
            pending_status, _ = request(endpoint, f"{session}/inbox/{pending['id']}", method="DELETE")
            assert pending_status == 204 and json_data(f"{session}/inbox") == []
            print("pending control: cancel HTTP 204, inbox empty, no model call")

            first = json_data(f"{session}/prompt", {"text": "WITHDRAW_REPLAY"})
            first_history = wait_for_reply()
            original_reply = next(row["id"] for row in first_history if row["type"] == "assistant")
            first_status, _ = request(endpoint, f"{session}/inbox/{first['id']}", method="DELETE")
            delivered = json_data(f"{session}/message/{first['id']}")
            assert delivered["id"] == first["id"] and delivered["type"] == "user"
            assert json_data(f"{session}/inbox") == []

            if mode == "rewind":
                request(endpoint, f"{session}/interrupt", method="POST")
                request(endpoint, f"/api/experimental/session/{session_id}/wait", method="POST")
                staged = json_data(f"{session}/revert/stage", {"messageID": first["id"]})
                assert staged["messageID"] == first["id"]
                print("staged the original prompt for rewind")

            json_data(f"{session}/prompt", {"text": "WITHDRAW_REPLAY"})
            history = wait_for_reply(after=original_reply)
            user_rows = [row for row in history if row["type"] == "user"]
            assistant_rows = [row for row in history if row["type"] == "assistant"]
            expected = 1 if mode == "rewind" else 2
            assert first_status == 204 and len(user_rows) == len(assistant_rows) == expected
            copies = json.dumps(requests[-1]).count("WITHDRAW_REPLAY")
            assert copies == expected
            assert all("PENDING_CONTROL" not in json.dumps(body) for body in requests)
            revision = subprocess.check_output(["git", "-C", source, "rev-parse", "HEAD"], text=True).strip()
            print(f"revision={revision} delivered_cancel_status={first_status} message_still_exists=True")
            print(f"after resend: user_messages={len(user_rows)} replies={len(assistant_rows)} second_request_copies={copies}")
        finally:
            server.terminate()
            server.wait(timeout=12)
            remote.shutdown()
