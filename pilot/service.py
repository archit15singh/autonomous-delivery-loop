"""Small HTTP service for exercising the delivery loop in hosted staging."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
from urllib.parse import parse_qs, urlsplit


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
    def do_GET(self):
        target = urlsplit(self.path)
        if target.path == "/_revision":
            status, document = 200, {
                "revision": self.server.revision,
                "deployment": self.server.deployment,
            }
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
        payload = json.dumps(document).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    with ThreadingHTTPServer((args.host, args.port), Handler) as server:
        server.revision = os.environ["ADL_REVISION"]
        server.deployment = os.environ["ADL_DEPLOYMENT"]
        server.redis_host = os.environ.get("ADL_REDIS_HOST")
        print(server.server_port, flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
