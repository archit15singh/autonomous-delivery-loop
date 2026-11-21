"""Small HTTP service for exercising the delivery loop in hosted staging."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
import sqlite3
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4


JOB_PAGE = b"""<!doctype html><html lang="en"><meta charset="utf-8"><title>Job runner</title>
<main><h1>Job runner</h1><button id="enqueue">Run job</button>
<p id="status" role="status">Ready</p></main>
<script>
const button = document.getElementById('enqueue');
const status = document.getElementById('status');
const delay = () => new Promise(resolve => setTimeout(resolve, 100));
button.addEventListener('click', async () => {
  button.disabled = true;
  status.textContent = 'Queued';
  try {
    const response = await fetch('/jobs', {method: 'POST'});
    if (!response.ok) throw new Error('Queue rejected the job');
    const {id} = await response.json();
    status.dataset.job = id;
    for (let attempt = 0; attempt < 60; attempt++) {
      const result = await fetch('/jobs?id=' + encodeURIComponent(id));
      if (!result.ok) throw new Error('Could not read the job');
      if ((await result.json()).status === 'completed') {
        status.textContent = 'Completed';
        return;
      }
      await delay();
    }
    status.textContent = 'Timed out';
  } catch {
    status.textContent = 'Failed';
  } finally {
    button.disabled = false;
  }
});
</script></html>"""


def routes(path, query=""):
    if path == "/health":
        return 200, {"ready": True}
    if path == "/greet":
        name = parse_qs(query).get("name", ["world"])[0]
        if not name.strip():
            name = "world"
        return 200, {"message": f"Hello, {name}!"}
    return 404, {"error": "not found"}


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, payload, media_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        if self.path != "/jobs" or not self.server.job_db:
            self.reply(404, b'{"error":"not found"}')
            return
        job = uuid4().hex
        try:
            with socket.create_connection((self.server.redis_host, 6379), timeout=2) as redis:
                redis.sendall(f"*3\r\n$5\r\nLPUSH\r\n$8\r\nadl:jobs\r\n$32\r\n{job}\r\n".encode())
                with redis.makefile("rb") as response:
                    if not response.readline(64).startswith(b":"):
                        raise ValueError("queue did not confirm the job")
        except (OSError, ValueError):
            self.reply(503, b'{"error":"queue unavailable"}')
            return
        self.reply(202, json.dumps({"id": job}).encode())

    def do_GET(self):
        target = urlsplit(self.path)
        if target.path == "/_revision":
            status, document = 200, {
                "revision": self.server.revision,
                "deployment": self.server.deployment,
            }
        elif target.path == "/jobs/ui" and self.server.job_db:
            self.reply(200, JOB_PAGE, "text/html; charset=utf-8")
            return
        elif target.path == "/jobs" and self.server.job_db:
            job = parse_qs(target.query).get("id", [""])[0]
            if len(job) != 32 or any(c not in "0123456789abcdef" for c in job):
                status, document = 400, {"error": "invalid job"}
            else:
                try:
                    with sqlite3.connect(f"file:{self.server.job_db}?mode=ro", uri=True) as db:
                        row = db.execute("SELECT status FROM jobs WHERE id=?", (job,)).fetchone()
                    status, document = 200, {"status": row[0] if row else "queued"}
                except sqlite3.Error:
                    status, document = 503, {"error": "job database unavailable"}
        elif target.path == "/counter" and self.server.redis_host:
            try:
                with socket.create_connection((self.server.redis_host, 6379), timeout=2) as redis:
                    redis.sendall(b"*2\r\n$4\r\nINCR\r\n$11\r\nadl:counter\r\n")
                    with redis.makefile("rb") as response:
                        result = response.readline(64)
                if not result.startswith(b":") or not result.endswith(b"\r\n"):
                    raise ValueError("Redis did not return an integer")
                status, document = 200, {"count": int(result[1:])}
            except (OSError, ValueError):
                status, document = 503, {"error": "counter unavailable"}
        else:
            status, document = routes(target.path, target.query)
        self.reply(status, json.dumps(document).encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    with ThreadingHTTPServer((args.host, args.port), Handler) as server:
        server.revision = os.environ["ADL_REVISION"]
        server.deployment = os.environ["ADL_DEPLOYMENT"]
        server.redis_host = os.environ.get("ADL_REDIS_HOST")
        server.job_db = os.environ.get("ADL_JOB_DB")
        print(server.server_port, flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
