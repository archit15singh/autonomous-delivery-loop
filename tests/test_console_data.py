from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from delivery.console_data import snapshot, trace


HEAD = "a" * 40
BASE = "b" * 40
PR = "https://github.com/owner/repo/pull/12"
OTHER_PR = "https://github.com/another/repo/pull/12"
FINISHED = "2026-11-22T08:00:00+05:30"


def pr(url=PR, **fields):
    return {"url": url, "state": "OPEN", "action": "wait_for_ci", "head": HEAD,
            "base": BASE, "signals": [], **fields}


def event(kind, **fields):
    return {"type": kind, **fields}


class ConsoleDataTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.adl = self.root / ".adl"

    def write(self, path, value, *, at=None):
        destination = self.adl / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(value if isinstance(value, str) else json.dumps(value))
        if at is not None:
            os.utime(destination, (at, at))
        return destination

    def write_events(self, path, events):
        return self.write(path, "\n".join(json.dumps(row) for row in events) + "\n")

    def test_selects_complete_pr_snapshot_by_freshness(self):
        self.write("upstream-ci/round100.json", [pr(title="Older high number")], at=100)
        same_pr = "https://github.com/OWNER/REPO/pull/12"
        self.write("upstream-ci/round9.json", [pr(), pr(OTHER_PR), pr(same_pr)], at=110)
        self.write("upstream-ci/current.json", [pr(title="Fresh current")], at=120)
        self.write("upstream-ci/round101.json", "[{", at=130)
        self.write("upstream-ci/round102.json", [pr(), {"url": OTHER_PR, "action": "lookup_failed"}], at=140)
        self.write("upstream-ci/round103.json", [pr(), False], at=150)
        self.write("upstream-ci/round104.json", [pr(base=None)], at=155)
        self.write("upstream-ci/score-round999.json", [pr(title="Report")], at=160)
        self.write("upstream-ci/merge-precedents.json", {
            "branches": [{"sample": [{"url": PR, "title": "Cached PR title"},
                                     {"url": "https://github.com/third/repo/pull/12", "title": "Wrong PR"}]}],
        })

        visible = snapshot(self.root)
        self.assertEqual(set(visible), {"prs", "runs", "traces", "as_of"})
        self.assertEqual(visible["as_of"], datetime.fromtimestamp(120, timezone.utc).isoformat())
        self.assertEqual([p["title"] for p in visible["prs"]], ["Fresh current"])
        replacement = self.write("upstream-ci/replacement.json", [], at=170)
        replacement.replace(self.adl / "upstream-ci/current.json")
        visible = snapshot(self.root)
        self.assertEqual(visible["as_of"], datetime.fromtimestamp(110, timezone.utc).isoformat())
        self.assertEqual([(p["id"], p["title"]) for p in visible["prs"]],
                         [(PR, "Cached PR title"), (OTHER_PR, "another/repo #12")])

    def test_projects_safe_review_and_check_fields(self):
        self.write("upstream-ci/current.json", [pr(
            signals=[None, {"name": "Tests", "state": "success",
                            "url": "https://ci.example/check/42?token=secret#private", "stderr": "hidden"},
                     {"name": "Invalid link", "state": ["bad"], "url": "javascript:alert(1)"},
                     {"name": "Userinfo", "url": "https://user:password@ci.example/"}],
            review={"action": "inspect_review_feedback", "decision": "CHANGES_REQUESTED",
                    "reviews": [{"body": "hidden"}], "error": "hidden"},
        )])
        self.assertEqual(snapshot(self.root)["prs"], [{
            "id": PR, "url": PR, "repo": "owner/repo", "number": 12, "title": "owner/repo #12",
            "state": "OPEN", "action": "wait_for_ci", "head": HEAD, "base": BASE,
            "review": {"action": "inspect_review_feedback", "decision": "CHANGES_REQUESTED"},
            "checks": [{"name": "Tests", "state": "success", "url": "https://ci.example/check/42"},
                       {"name": "Invalid link", "state": "unknown", "url": None},
                       {"name": "Userinfo", "state": "unknown", "url": None}],
        }])

    def test_runs_keep_repeated_attempts_and_attach_scores_by_identity(self):
        self.write("upstream-ci/round1.json", [pr()])
        self.write("upstream-ci/score-round1.json", {"rows": [
            {"subject": PR, "head": HEAD, "score": 20, "points": {"verified_fix": 20},
             "evidence": {"replay": "run-1"}},
            {"subject": OTHER_PR, "head": HEAD, "score": 10, "points": {"green_ci": 10},
             "evidence": {"replay": "run-2"}},
            {"subject": PR, "head": BASE, "score": 10, "points": {"green_ci": 10},
             "evidence": {"replay": "run-2"}},
        ]})
        row = {"pr": PR, "head": HEAD, "base": BASE, "finished_at": FINISHED, "factory_revision": BASE,
               "outcome": {"readiness": "verified", "assessment": {"skill_adherence": "passed", "raw": "hidden"}},
               "metrics": {"tokens": 100, "wall_seconds": 3.5, "human_interventions": 0},
               "receipts": {"spec": {"file": "spec.json", "sha256": "hidden"},
                            "trace": {"file": "../../private.json"}, "invalid": []},
               "retries": {"infrastructure": 1},
               "findings": [{"dimension": "retry_efficiency", "reason": "retry",
                             "category": "factory", "output": "hidden"}, None],
               "stderr": "hidden", "env": {"API_KEY": "hidden"}}
        self.write("factory-runs/run-1.json", {**row, "id": "run-1"})
        self.write("factory-runs/run-2.json", {**row, "id": "run-2", "finished_at": "2026-11-22T03:00:00Z",
                                             "outcome": {"readiness": "failed"},
                                             "metrics": {"tokens": float("nan"), "wall_seconds": -1,
                                                         "human_interventions": False}})
        self.write("factory-runs/corrupt.json", "{")
        self.write("factory-runs/aliased.json", {**row, "id": "run-1"})
        self.write("factory-runs/no-date.json", {**row, "id": "no-date", "finished_at": "2026-11-22"})

        newer, older = snapshot(self.root)["runs"]
        self.assertEqual(newer["id"], "run-2")
        self.assertEqual(newer["outcome"], "failed")
        self.assertEqual(newer["scores"], {})
        self.assertTrue(all(newer[k] is None for k in ("tokens", "seconds", "interventions")))
        self.assertEqual(older["finished_at"], "2026-11-22T02:30:00+00:00")
        self.assertEqual(older["outcome"], "verified")
        self.assertEqual(older["scores"], {"skill_adherence": "passed", "score": 20,
                                          "points": {"verified_fix": 20}})
        self.assertEqual(older["receipts"], ["spec.json"])
        self.assertEqual((older["tokens"], older["seconds"], older["interventions"]), (100, 3.5, 0))
        self.assertEqual(older["details"]["retries"]["infrastructure"], 1)
        self.assertNotIn("hidden", json.dumps([newer, older], allow_nan=False))

    def test_trace_detail_preserves_order_and_redacts_messages(self):
        message = ("The replay passed. Authorization: Bearer bearer-canary\n"
                   "client_secret = \"secret-canary\"\nCookie: a=cookie-canary; b=extra-cookie-canary\n"
                   "Link https://example.test/proof?x=link-canary\n"
                   "Try --token flag-canary\n"
                   "```sh\nraw-shell-canary\n```\n"
                   "See ghp_credentialCanary1234")
        rows = [
            event("thread.started", thread_id="private-thread"),
            event("turn.started"),
            event("item.started", item={"type": "command_execution", "id": "item_0",
                                        "command": "command-canary", "env": "env-canary"}),
            event("item.completed", item={"type": "command_execution", "id": "item_0", "exit_code": 3,
                                          "status": "completed", "aggregated_output": "output-canary"}),
            event("item.completed", item={"type": "agent_message", "id": "item_1", "text": message}),
            event("item.completed", item={"type": "reasoning", "text": "hidden-reasoning"}),
            event("turn.completed", usage={"input_tokens": 11, "cached_input_tokens": 5, "output_tokens": 2}),
        ]
        path = "review-transcripts/reviewer-1/events.jsonl"
        self.write(path, "\n".join(["corrupt line", *map(json.dumps, rows), '{"type": []}']))
        self.write_events("review-transcripts/judge-1/events.jsonl", rows[:2])
        self.write_events("unrelated/checkout/events.jsonl", rows)
        summaries = snapshot(self.root)["traces"]
        self.assertEqual(len(summaries), 2)
        self.assertEqual(len({r["id"] for r in summaries}), 2)
        self.assertNotIn("The replay passed", json.dumps(summaries))
        entry = next(r for r in summaries if r["label"] == path)
        self.assertEqual((entry["turns"], entry["tokens"], entry["events_count"]), (1, 13, 7))
        self.assertIsNone(next(r for r in summaries if r != entry)["tokens"])
        metadata = trace(self.root, entry["id"], include_messages=False)
        self.assertTrue(metadata["events"][4]["item"]["has_text"])
        self.assertNotIn("text", metadata["events"][4])
        view = trace(self.root, entry["id"])
        self.assertEqual([e["line"] for e in view["events"]], list(range(2, 9)))
        self.assertEqual(view["skipped_events"], 2)
        self.assertFalse(view["truncated"])
        self.assertTrue(view["messages_included"])
        self.assertEqual(view["events"][3]["item"], {"type": "command_execution", "id": "item_0",
                                                     "status": "completed", "exit_code": 3})
        self.assertIn("The replay passed.", view["events"][4]["text"])
        self.assertIn("https://example.test/proof", view["events"][4]["text"])
        for excluded in ("canary", "Canary", "private-thread", "hidden-reasoning"):
            self.assertNotIn(excluded, json.dumps(view, allow_nan=False))

    def test_trace_discloses_event_byte_and_message_limits(self):
        body = event("item.completed", item={"type": "agent_message", "text": "a" * 2100})
        rows = [event("turn.started"), body, event("error"), event("turn.completed")]
        self.write_events("events.jsonl", rows)
        trace_id = snapshot(self.root)["traces"][0]["id"]
        with patch("delivery.console_data._EVENT_LIMIT", 2):
            view = trace(self.root, trace_id)
        self.assertEqual(view["events_count"], 4)
        self.assertTrue(view["truncated"])
        self.assertFalse(view["counts_truncated"])
        self.assertEqual([e["line"] for e in view["events"]], [1, 2])
        self.assertEqual(len(view["events"][1]["text"]), 2000)
        self.assertTrue(view["events"][1]["text_truncated"])
        with patch("delivery.console_data._TRACE_BYTES", 64):
            view = trace(self.root, trace_id)
        self.assertEqual(view["events_count"], 1)
        self.assertTrue(view["truncated"])
        self.assertTrue(view["counts_truncated"])
        self.assertEqual(view["skipped_events"], 0)

    def test_rejects_symlinks_special_files_and_unlisted_ids(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "events.jsonl").write_text(json.dumps(event("turn.started")))
        (outside / "round.json").write_text(json.dumps([pr()]))
        self.adl.symlink_to(outside, target_is_directory=True)
        self.assertEqual(snapshot(self.root), {"prs": [], "runs": [], "traces": [], "as_of": None})
        self.adl.unlink()
        self.adl.mkdir()
        (self.adl / "events.jsonl").symlink_to(outside / "events.jsonl")
        (self.adl / "review-transcripts").symlink_to(outside, target_is_directory=True)
        (self.adl / "upstream-ci").mkdir()
        (self.adl / "upstream-ci/current.json").symlink_to(outside / "round.json")
        os.mkfifo(self.adl / "named-codex.jsonl")
        self.write_events("checkout/events.jsonl", [event("turn.started")])
        self.assertEqual(snapshot(self.root), {"prs": [], "runs": [], "traces": [], "as_of": None})
        for lookup in ("../outside/events.jsonl", str(outside / "events.jsonl"),
                       sha256(b"events.jsonl").hexdigest(), sha256(b"checkout/events.jsonl").hexdigest()):
            self.assertIsNone(trace(self.root, lookup))
