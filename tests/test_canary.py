from copy import deepcopy
import unittest

from delivery.canary import observe, prometheus, read_policy


START, END = 1760000000, 1760000002
POLICY = {"version": 1, "requests_metric": "calls_total", "successes_metric": "ok_total",
          "step_seconds": 1, "minimum_requests": 10, "minimum_success_rate": 0.85,
          "max_success_rate_drop": 0.1, "candidate": {"revision": "a" * 40, "deployment": "a"},
          "control": {"revision": "b" * 40, "deployment": "b"}}


def fixture(candidate=(100, 110, 120), *, bad=None):
    def query(selector, start, end, step):
        assert "timestamp(" in selector
        metric = selector.split("{", 1)[0]
        is_candidate = 'deployment="a"' in selector
        identity = POLICY["candidate" if is_candidate else "control"]
        counts = candidate if is_candidate and metric == "ok_total" else (100, 110, 120)
        item = {"metric": {"__name__": metric, **identity},
                "values": [[i, str(value)] for i, value in zip(range(start, end + 1, step), counts)]}
        if bad is not None:
            bad(item)
        return {"status": "success", "data": {"resultType": "matrix", "result": [item]}}

    return query


class CanaryTest(unittest.TestCase):
    def setUp(self):
        self.policy = read_policy(deepcopy(POLICY), START, END)

    def test_healthy_and_bad_candidate_require_operator_review(self):
        for counts, expected in (((100, 110, 120), "review_promotion"), ((100, 101, 102), "review_rollback")):
            report = observe(self.policy, fixture(counts), START, END)
            self.assertEqual(report["recommendation"], expected)
            self.assertTrue(report["operator_approval_required"])
            self.assertEqual(report["control"]["samples"], 20)

    def test_wrong_identity_gap_and_counter_reset_each_hold(self):
        controls = (
            fixture(bad=lambda item: item["metric"].update(deployment="wrong")),
            fixture(bad=lambda item: item["values"].pop(1)),
            fixture((100, 101, 0)),
        )
        for query in controls:
            report = observe(self.policy, query, START, END)
            self.assertEqual((report["verdict"], report["recommendation"]), ("inconclusive", "hold"))

    def test_insufficient_traffic_and_unsafe_endpoint(self):
        self.policy["minimum_requests"] = 21
        self.assertEqual(observe(self.policy, fixture(), START, END)["reason"], "insufficient_requests")
        for url in ("http://monitor.example", "https://name:password@monitor.example", "file:///tmp/data"):
            with self.assertRaises(ValueError):
                prometheus(url)
