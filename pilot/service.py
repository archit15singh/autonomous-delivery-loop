"""Small HTTP service for exercising the delivery loop in hosted staging."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from urllib.parse import urlsplit


def routes(path):
    if path == "/health":
        return 200, {"ready": True}
    if path == "/greet":
        return 200, {"message": "Hello, world!"}
    return 404, {"error": "not found"}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/_revision":
            status, document = 200, {
                "revision": self.server.revision,
                "deployment": self.server.deployment,
            }
        else:
            status, document = routes(path)
        payload = json.dumps(document).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        server.revision = os.environ["ADL_REVISION"]
        server.deployment = os.environ["ADL_DEPLOYMENT"]
        print(server.server_port, flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
