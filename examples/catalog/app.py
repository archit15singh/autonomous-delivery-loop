"""Example product for the disposable runtime adapters."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os


class Catalog(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/_revision":
            body = {"revision": os.environ["ADL_REVISION"], "deployment": os.environ["ADL_DEPLOYMENT"]}
        elif self.path == "/catalog":
            body = {"items": ["notebook"]}
        else:
            self.send_error(404)
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ThreadingHTTPServer((os.environ["ADL_HOST"], int(os.environ["PORT"])), Catalog).serve_forever()
