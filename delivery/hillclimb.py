"""Compare two runtime-verifier refinements against the live staging baseline."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from statistics import median
from threading import Thread
from time import monotonic
from unittest.mock import patch

from . import stage, verify

THRESHOLD = 15


def parallel_observations(contract, origin):
    initial_fetch = verify.fetch
    results = None

    def fetch(url, path):
        nonlocal results
        if path == "/_revision":
            return initial_fetch(url, path)
        if results is None:
            with ThreadPoolExecutor(max_workers=min(4, len(contract.probes))) as pool:
                results = iter(pool.map(lambda probe: initial_fetch(origin, probe.path), contract.probes))
        return next(results)

    return fetch


def cached_identity():
    initial_fetch = verify.fetch
    identity = None

    def fetch(origin, path):
        nonlocal identity
        if path != "/_revision":
            return initial_fetch(origin, path)
        if identity is None:
            identity = initial_fetch(origin, path)
        return identity

    return fetch


def run_checks(variant, contract, origin, revision, deployment, ci, repairs_used=0, impact_evidence=None):
    if variant == "baseline":
        return verify.verify(contract, origin, revision, deployment, ci, repairs_used, impact_evidence)
    fetch = cached_identity() if variant == "cached-identity" else parallel_observations(contract, origin)
    with patch.object(verify, "fetch", fetch):
        return verify.verify(contract, origin, revision, deployment, ci, repairs_used, impact_evidence)


@contextmanager
def rollout_control(contract, revision, deployment, mode):
    expected = {probe.path: probe.expect for probe in contract.probes}
    reads = 0

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            nonlocal reads
            if self.path == "/_revision":
                reads += 1
                body = {"revision": revision, "deployment": deployment}
                if mode == "wrong-deployment" or (mode == "rollout-drift" and reads > 1):
                    body["deployment"] = "different"
            elif mode == "bad-behavior":
                body = {"wrong": True}
            else:
                body = expected[self.path]
            payload = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join()


def measure(contract_path, bundle, repetitions):
    receipt_path = bundle / "ci.json"
    ci = json.loads(receipt_path.read_text())
    revision, deployment = ci["revision"], ci["deployment"]
    contract = verify.Contract.read(contract_path)
    variants = ["baseline", "parallel-probes", "cached-identity"]
    desired = {"healthy": "verified", "bad-behavior": "failed",
               "wrong-deployment": "inconclusive", "rollout-drift": "inconclusive"}
    controls = {}
    for variant in variants:
        controls[variant] = {}
        for mode in desired:
            with rollout_control(contract, revision, deployment, mode) as origin:
                report = run_checks(variant, contract, origin, revision, deployment, ci)
                controls[variant][mode] = report["verdict"]

    timings = {variant: [] for variant in variants}
    accepted = {variant: True for variant in variants}
    for iteration in range(repetitions):
        start = iteration % len(variants)
        for variant in variants[start:] + variants[:start]:
            def adapter(*args):
                return run_checks(variant, *args)

            with patch.object(stage, "verify", adapter):
                before = monotonic()
                report = stage.stage(contract_path, bundle / "pilot.tar", receipt_path,
                                     revision, deployment, quiet=True)
                timings[variant].append(round((monotonic() - before) * 1000, 3))
                accepted[variant] &= report["verdict"] == "verified"

    results = []
    for variant in variants:
        gains = [100 * (base - trial) / base
                 for base, trial in zip(timings["baseline"], timings[variant])]
        change = round(median(gains), 2)
        parity = controls[variant] == desired and accepted[variant]
        results.append({"variant": variant, "controls": controls[variant],
                        "all_stage_checks_passed": accepted[variant],
                        "median_stage_ms": round(median(timings[variant]), 3),
                        "median_paired_gain_pct": change, "preserved_gates": parity,
                        "promote": parity and change >= THRESHOLD,
                        "stage_ms": timings[variant]})
    if controls["baseline"] != desired or not accepted["baseline"]:
        raise RuntimeError("the benchmark baseline failed its controls")
    return {"revision": revision, "repetitions": repetitions, "threshold_pct": THRESHOLD,
            "expected_controls": desired, "variants": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=18)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("at least one repetition is required")
    result = measure(args.contract, args.bundle, args.repetitions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    for row in result["variants"]:
        print(row["variant"], row["median_stage_ms"], row["median_paired_gain_pct"], row["promote"])


if __name__ == "__main__":
    main()
