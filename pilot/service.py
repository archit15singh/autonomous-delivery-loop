"""Small HTTP service for exercising the delivery loop in hosted staging."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from urllib.parse import parse_qs, urlsplit


def routes(path, query=""):
    if path == "/health":
        return 200, {"ready": True}
    if path == "/greet":
        params = parse_qs(query)
        names = params.get("name")
        if not names:
            return 200, {"message": "Hello, world!"}
        name = names[0]
        if params.get("style", [""])[0] == "uppercase":
            name = name.upper()
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
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        server.revision = os.environ["ADL_REVISION"]
        server.deployment = os.environ["ADL_DEPLOYMENT"]
        print(server.server_port, flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
