"""Rehearse canary detection with real HTTP probes and a pinned Prometheus."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
from threading import Event, Lock, Thread
import time
from urllib.request import urlopen
from uuid import uuid4


IMAGE = "prom/prometheus@sha256:38c3b05c3bc744ff1b0b7b4eb82196026442845e62a1e2073795565da506d7a2"
COHORTS = {"candidate": {"revision": "a" * 40, "deployment": "candidate-1"},
           "control": {"revision": "b" * 40, "deployment": "control-1"}}


def main(folder):
    folder = folder.resolve()
    folder.mkdir(parents=True)
    counters = {key: [0, 0] for key in COHORTS}
    mutex, stop, regression = Lock(), Event(), Event()

    class Service(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/metrics":
                with mutex:
                    lines = []
                    for cohort, identity in COHORTS.items():
                        labels = f'revision="{identity["revision"]}",deployment="{identity["deployment"]}"'
                        for name, count in zip(("adl_requests_total", "adl_successes_total"), counters[cohort]):
                            lines.append(f"{name}{{{labels}}} {count}\n")
                data = "".join(lines).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_response(503 if self.path == "/candidate" and regression.is_set() else 200)
            self.end_headers()

    with ThreadingHTTPServer(("127.0.0.1", 0), Service) as server:
        Thread(target=server.serve_forever, daemon=True).start()
        local = f"127.0.0.1:{server.server_port}"
        config = folder / "prometheus.yml"
        config.write_text(f"""global:
  scrape_interval: 1s
scrape_configs:
  - job_name: independent-http
    static_configs:
      - targets: ['{local}']
""")
        name = "adl-prometheus-" + uuid4().hex[:12]
        deployed = subprocess.check_output(
            ["docker", "run", "-d", "--name", name, "--network", "host",
             "--mount", f"type=bind,src={config},dst=/etc/prometheus/prometheus.yml,readonly",
             IMAGE, "--config.file=/etc/prometheus/prometheus.yml", "--web.listen-address=127.0.0.1:19090"],
            text=True, timeout=120).strip()
        origin = "http://127.0.0.1:19090"
        client = None

        def probes():
            while not stop.is_set():
                for cohort in COHORTS:
                    try:
                        with urlopen(f"http://{local}/{cohort}", timeout=2) as response:
                            ok = response.status == 200
                    except OSError:
                        ok = False
                    with mutex:
                        counters[cohort][0] += 1
                        counters[cohort][1] += ok
                stop.wait(0.15)

        try:
            for _ in range(30):
                try:
                    with urlopen(origin + "/-/ready", timeout=2) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.3)
            else:
                raise RuntimeError("Prometheus did not become ready")
            client = Thread(target=probes, daemon=True)
            client.start()
            policy = folder / "policy.json"
            policy.write_text(json.dumps({"version": 1, "requests_metric": "adl_requests_total",
                                          "successes_metric": "adl_successes_total", "step_seconds": 1,
                                          "minimum_requests": 10, "minimum_success_rate": 0.9,
                                          "max_success_rate_drop": 0.1, **COHORTS}))
            for label, verdict, recommendation in (("passing", "verified", "review_promotion"),
                                                   ("regression", "failed", "review_rollback")):
                if label == "regression":
                    regression.set()
                time.sleep(2.1)
                start = int(time.time()) + 1
                end = start + 4
                time.sleep(end + 1 - time.time())
                receipt = folder / f"{label}.json"
                result = subprocess.run([sys.executable, "-B", "-m", "delivery", "factory", "--output", str(receipt),
                                         "canary-observe", "--policy", str(policy), "--origin", origin,
                                         "--start", str(start), "--end", str(end)], check=False)
                report = json.loads(receipt.read_text())
                assert result.returncode == int(verdict != "verified") and report["verdict"] == verdict, report
                assert report["recommendation"] == recommendation and report["operator_approval_required"], report
                assert report["candidate"]["samples"] >= 10 and report["control"]["success_rate"] == 1, report
                print(label, verdict, report["reason"], flush=True)
        finally:
            stop.set()
            if client is not None:
                client.join(timeout=5)
            server.shutdown()
            try:
                with (folder / "prometheus.log").open("w") as logs:
                    subprocess.run(["docker", "logs", deployed], check=False, timeout=15,
                                   stdout=logs, stderr=subprocess.STDOUT)
            finally:
                subprocess.run(["docker", "rm", "-fv", deployed], check=True, timeout=20, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
