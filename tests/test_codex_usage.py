import json
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from delivery.codex_usage import capture_sessions, summarize
from delivery.factory_issue import index_publication


def started(thread_id):
    return {"type": "thread.started", "thread_id": thread_id}


def completed(input_tokens=100, cached=40, output=10):
    return {"type": "turn.completed", "usage": {
        "input_tokens": input_tokens, "cached_input_tokens": cached, "output_tokens": output,
    }}


def spawn(item_id, *children):
    return {"type": "item.completed" if children else "item.started", "item": {
        "type": "collab_tool_call", "id": item_id, "tool": "spawn_agent",
        "receiver_thread_ids": list(children),
    }}


RATES = {"uncached_input": 2, "cached_input": 1, "output": 4}


class CodexUsageTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def write(self, filename, *events):
        path = self.folder / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(event) + "\n" for event in events))
        return path

    def test_cli_prices_all_turns_and_charges_cached_input_once(self):
        events = self.write("events.jsonl", started("main"), completed(), completed())
        rates = self.write("rates.json", RATES)
        report = json.loads(subprocess.check_output([
            sys.executable, "-m", "delivery.codex_usage", str(events), "--rates", str(rates),
        ]))
        self.assertTrue(report["complete"])
        self.assertEqual(report["thread_ids"], ["main"])
        self.assertEqual(report["totals"], {
            "turns_with_usage": 2, "input_tokens": 200, "cached_input_tokens": 80,
            "uncached_input_tokens": 120, "output_tokens": 20, "tokens": 220,
        })
        self.assertAlmostEqual(report["estimated_cost_usd"], 0.0004)
        self.assertIsNone(report["actual_cost_usd"])

    def test_child_coverage_is_recursive_and_copies_and_prefixes_count_once(self):
        parent = self.write("parent", started("parent"), spawn("i"), spawn("i", "child"), completed())
        child_events = (started("child"), completed())
        prefix = self.write("prefix", *child_events)
        child = self.write("child", *child_events, spawn("i", "grandchild"), completed())
        copy = self.write("copy", *child_events, spawn("i", "grandchild"), completed())
        report = summarize([parent, prefix, child, copy], RATES)
        self.assertFalse(report["complete"])
        self.assertEqual(report["missing_child_thread_ids"], ["grandchild"])
        self.assertEqual(report["observed"]["tokens"], 330)
        self.assertIsNone(report["totals"])
        self.assertIsNone(report["estimated_cost_usd"])

        grandchild = self.write("grandchild", started("grandchild"), completed())
        report = summarize([parent, prefix, child, copy, grandchild, grandchild], RATES)
        self.assertTrue(report["complete"])
        self.assertEqual(report["totals"]["tokens"], 440)

    def test_failures_and_truncation_preserve_observed_usage(self):
        events = self.write("faults", started("main"), completed(), completed(cached=101),
                            spawn("unknown"), {"type": "turn.started"}, {"type": "turn.failed"},
                            {"type": "error"}, {"type": "turn.started"})
        with events.open("a") as stream:
            stream.write('{"type":')
        report = summarize([events], RATES)
        self.assertEqual(set(report["signals"]), {
            "missing_or_invalid_usage", "unidentified_child_thread", "unfinished_turn",
            "turn.failed", "error", "invalid_event",
        })
        self.assertEqual(report["observed"]["tokens"], 110)
        self.assertIsNone(report["totals"])

    def test_conflicting_thread_logs_have_no_total(self):
        first = self.write("first", started("root"), completed())
        second = self.write("second", started("root"), completed(output=20))
        report = summarize([first, second])
        self.assertEqual(report["signals"], ["conflicting_thread_transcripts"])
        self.assertIsNone(report["totals"])
        self.assertEqual(report["observed"]["turns_with_usage"], 1)

    def test_legacy_usage_and_missing_rates(self):
        legacy = self.write("legacy", {"type": "turn.completed", "usage": {
            "input_tokens": 20, "output_tokens": 3,
        }})
        report = summarize([legacy], RATES)
        self.assertEqual(report["totals"]["tokens"], 23)
        self.assertIsNone(report["totals"]["uncached_input_tokens"])
        self.assertIsNone(report["estimated_cost_usd"])
        modern = self.write("modern", started("root"), completed())
        self.assertIsNone(summarize([modern], {"output": 4})["estimated_cost_usd"])

    def test_factory_persists_explicit_estimate_and_reuses_frozen_run_spec(self):
        self.write("codex.jsonl", started("main"), spawn("i", "child"), completed(), completed())
        self.write("codex-children/child.jsonl", started("child"), completed())
        rates = self.write("codex-rates.json", RATES)
        self.write("candidate.json", {"revision": "a" * 40, "verdict": "verified"})
        self.write("recipe.json", {"revision": "b" * 40})
        self.write("candidate.patch")
        with patch("delivery.factory_issue.definition", return_value={"sha256": "definition"}), patch(
            "delivery.run_index.check_definition",
        ):
            indexed = self.index()
            rates.unlink()
            self.assertEqual(self.index(), indexed)
        spec = json.loads((self.folder / "run-spec.json").read_text())
        self.assertEqual(indexed["metrics"]["tokens"], 330)
        self.assertNotIn("cost_usd", indexed["metrics"])
        self.assertAlmostEqual(spec["codex_usage"]["estimated_cost_usd"], 0.0006)
        self.assertIsNone(spec["codex_usage"]["actual_cost_usd"])

    def test_factory_omits_incomplete_metrics_and_reuses_legacy_index(self):
        self.write("codex.jsonl", started("main"), spawn("i", "missing"), completed())
        self.write("codex-rates.json", RATES)
        with patch("delivery.factory_issue.definition", return_value={}), patch(
            "delivery.factory_issue.run_record", side_effect=lambda path, _: json.loads(path.read_text()),
        ):
            spec = self.index()
            self.assertEqual(spec["metrics"], {"wall_seconds": 5, "human_interventions": 1})
            legacy = {"metrics": {"tokens": 110}}
            self.write("run-spec.json", legacy)
            self.write("index/owned-issue-approval.json", {})
            self.assertEqual(self.index(), legacy)

    def native(self, thread, *, parent=None, child=None, complete=True, null_usage=False,
               model="model", input_tokens=100):
        def event(kind, **payload):
            return {"type": "event_msg", "payload": {"type": kind, **payload}}

        def snapshot(count):
            return event("token_count", info={"total_token_usage": completed(input_tokens=count)["usage"]})

        source = "exec" if parent is None else {"subagent": {"thread_spawn": {"parent_thread_id": parent}}}
        rows = [
            {"type": "session_meta", "payload": {"id": thread, "parent_thread_id": parent,
                                                "source": source, "model_provider": "openai"}},
            event("task_started", turn_id="turn"),
            {"type": "turn_context", "payload": {"model": model, "turn_id": "turn"}},
            snapshot(50),
            snapshot(input_tokens),
        ]
        if child:
            rows.append(event("item_completed", item={"type": "SubAgentActivity", "kind": "started", "agent_thread_id": child}))
        if null_usage:
            rows.append(event("token_count", info=None))
        if complete:
            rows.append(event("task_complete", turn_id="turn"))
        rows.append(event("test", prompt="private test prompt"))
        return self.write(f"{thread}.rollout.jsonl", *rows)

    def ledger(self, parent, child=None, *, child_path=None):
        self.env = {"CODEX_HOME": str(self.folder)}
        self.db = self.folder / "state_5.sqlite"
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT)")
            db.execute("CREATE TABLE thread_spawn_edges (parent_thread_id TEXT, child_thread_id TEXT, status TEXT)")
            db.execute("INSERT INTO threads VALUES (?, ?)", ("root", str(parent)))
            if child:
                db.execute("INSERT INTO threads VALUES (?, ?)", ("child", str(child_path or child)))
                db.execute("INSERT INTO thread_spawn_edges VALUES ('root', 'child', 'open')")
            # An unrelated row must never be followed, even if its rollout points into this run.
            db.execute("INSERT INTO threads VALUES (?, ?)", ("unrelated", str(parent)))
            db.execute("INSERT INTO thread_spawn_edges VALUES ('unrelated', 'root', 'open')")

    def test_full_context_fork_excludes_inherited_turn_and_parent_interaction(self):
        events = self.write("parent.jsonl", started("root"), completed())
        parent = self.native("root", child="child")
        child = self.native("child", parent="root", input_tokens=80)
        rows = [json.loads(line) for line in child.read_text().splitlines()]
        inherited = [
            {"type": "session_meta", "payload": {"id": "root"}},
            {"type": "event_msg", "payload": {"type": "turn_aborted", "turn_id": "parent-turn"}},
            {"type": "event_msg", "payload": {"type": "thread_settings_applied", "thread_id": "child"}},
        ]
        rows[1:1] = inherited
        rows.append({"type": "event_msg", "payload": {"type": "item_completed", "item": {
            "type": "SubAgentActivity", "kind": "interacted", "agent_thread_id": "root"}}})
        self.write(child.name, *rows)
        self.ledger(parent, child)
        self.assertEqual(capture_sessions(events, self.env)["status"], "complete")
        self.assertEqual(summarize([events])["totals"]["input_tokens"], 180)

    def test_capture_reads_only_exact_run_and_counts_final_child_snapshot_once(self):
        events = self.write("exec.jsonl", started("root"), completed())
        parent = self.native("root", child="child")
        child = self.native("child", parent="root", input_tokens=120)
        self.ledger(parent, child)
        receipt = capture_sessions(events, self.env)
        self.assertEqual(receipt["status"], "complete")
        self.assertEqual(set(receipt["sessions"]), {"root", "child"})
        sidecar = events.with_suffix(".sessions.json")
        self.assertEqual(stat.S_IMODE(sidecar.stat().st_mode), 0o600)
        self.assertNotIn("private test prompt", sidecar.read_text())
        supplied = self.write("child.jsonl", started("child"), completed(input_tokens=120))
        report = summarize([events, supplied], RATES)
        self.assertEqual(report["scope"], "codex_exec_and_native_sessions")
        self.assertEqual(report["totals"]["tokens"], 240)
        self.assertEqual(report["child_thread_ids"], ["child"])
        details = next(row for row in report["threads"] if row["thread_id"] == "child")
        self.assertEqual(details["rollout_path"], str(child))
        self.assertEqual(details["models"], ["model"])

    def test_capture_rejects_mismatched_rollout_and_mismatched_sidecar_copy(self):
        events = self.write("exec.jsonl", started("root"), completed())
        parent = self.native("root", child="child")
        child = self.native("child", parent="root")
        self.ledger(parent, child, child_path=parent)
        self.assertIn("session_identity_mismatch", capture_sessions(events, self.env)["signals"])
        self.assertIsNone(summarize([events])["totals"])

        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE threads SET rollout_path=? WHERE id='child'", (str(child),))
        self.assertEqual(capture_sessions(events, self.env)["status"], "complete")
        copy = self.write("copy.jsonl", started("root"), completed(output=20))
        copy.with_suffix(".sessions.json").write_bytes(events.with_suffix(".sessions.json").read_bytes())
        report = summarize([events, copy])
        self.assertIn("invalid_session_capture", report["signals"])
        self.assertIsNone(report["totals"])

    def test_capture_requires_native_and_exec_parent_completion(self):
        events = self.write("exec.jsonl", started("root"), completed())
        self.ledger(self.native("root", complete=False))
        self.assertIn("incomplete_native_session", capture_sessions(events, self.env)["signals"])
        self.assertIsNone(summarize([events])["totals"])

        self.native("root")
        self.write("exec.jsonl", started("root"), completed(), {"type": "turn.started"})
        self.assertIn("unfinished_turn", capture_sessions(events, self.env)["signals"])
        self.assertIsNone(summarize([events])["totals"])

    def test_missing_child_capture_and_null_usage_fail_closed(self):
        events = self.write("exec.jsonl", started("root"), completed())
        self.ledger(self.native("root", child="child"))
        capture_sessions(events, self.env)
        report = summarize([events])
        self.assertIn("missing_child_capture", report["signals"])
        self.assertEqual(report["missing_child_thread_ids"], ["child"])
        self.assertIsNone(report["totals"])

        child = self.native("child", parent="root", null_usage=True)
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO threads VALUES ('child', ?)", (str(child),))
            db.execute("INSERT INTO thread_spawn_edges VALUES ('root', 'child', 'open')")
        capture_sessions(events, self.env)
        report = summarize([events])
        self.assertIn("missing_native_usage", report["signals"])
        self.assertEqual(report["missing_child_thread_ids"], ["child"])
        self.assertIsNone(report["totals"])

    def test_pending_malformed_and_changed_ledger_fail_closed(self):
        events = self.write("exec.jsonl", started("root"), completed())
        self.write("exec.sessions.json", {"status": "pending"})
        self.assertIn("pending_session_capture", summarize([events])["signals"])
        self.write("exec.sessions.json", {"version": 1, "status": "complete"})
        self.assertIn("invalid_session_capture", summarize([events])["signals"])
        self.ledger(self.native("root"))
        with sqlite3.connect(self.db) as db:
            db.execute("ALTER TABLE thread_spawn_edges RENAME COLUMN status TO edge_state")
        self.assertIn("unavailable_session_ledger", capture_sessions(events, self.env)["signals"])
        self.assertIsNone(summarize([events])["totals"])

    def test_mixed_models_keep_token_totals_but_have_no_flat_rate_estimate(self):
        events = self.write("exec.jsonl", started("root"), completed())
        self.ledger(self.native("root", child="child"), self.native("child", parent="root", model="other"))
        capture_sessions(events, self.env)
        report = summarize([events], RATES)
        self.assertEqual(report["totals"]["tokens"], 220)
        self.assertIsNone(report["estimated_cost_usd"])

    def index(self):
        return index_publication(self.folder, self.folder, {
            "head": "a" * 40, "base": "b" * 40, "approval": "approval",
            "pr": "https://github.com/example/repo/pull/1",
            "finished_at": "2026-11-22T00:00:00+00:00", "wall_seconds": 5, "human_approvals": 1,
        }, self.folder / "index")
