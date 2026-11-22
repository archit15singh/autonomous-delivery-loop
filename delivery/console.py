"""Serve the operator's local, read-only factory console."""
import argparse
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Lock
from time import monotonic
from urllib.parse import parse_qs, urlsplit

from .console_data import snapshot, trace
from .console_learning import learning

ASSETS = Path(__file__).with_name("console_assets")
FILES = {"/": ("index.html", "text/html"), "/style.css": ("style.css", "text/css"),
         "/app.js": ("app.js", "text/javascript")}


class Console(BaseHTTPRequestHandler):
    def __init__(self, *args, root, cache, lock, **kwargs):
        self.root, self.cache, self.lock = root, cache, lock
        super().__init__(*args, **kwargs)

    def do_GET(self):
        if self.headers.get("Host") not in {f"localhost:{self.server.server_port}",
                                           f"127.0.0.1:{self.server.server_port}"}:
            self.send_error(403)
            return
        url = urlsplit(self.path)
        try:
            if url.path in FILES:
                name, mime = FILES[url.path]
                body = (ASSETS / name).read_bytes()
            elif url.path in ("/api/snapshot", "/api/learning"):
                mime = "application/json"
                with self.lock:
                    then, body = self.cache.get(url.path, (0, None))
                    if body is None or monotonic() - then > 30:
                        loader = snapshot if url.path.endswith("snapshot") else learning
                        body = json.dumps(loader(self.root), allow_nan=False).encode()
                        self.cache[url.path] = (monotonic(), body)
            elif url.path == "/api/trace":
                mime = "application/json"
                params = parse_qs(url.query)
                data = trace(self.root, params.get("id", [""])[0],
                             include_messages=params.get("messages") == ["1"])
                if data is None:
                    self.send_error(404)
                    return
                body = json.dumps(data, allow_nan=False).encode()
            else:
                self.send_error(404)
                return
        except (LookupError, ValueError, OSError) as exc:
            self.log_error("Evidence unavailable: %s", type(exc).__name__)
            self.send_error(404 if url.path == "/api/trace" else 503)
            return
        self.send_response(200)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'")
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="factory checkout containing .adl")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    handler = partial(Console, root=args.root.resolve(), cache={}, lock=Lock())
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"Factory console at http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
