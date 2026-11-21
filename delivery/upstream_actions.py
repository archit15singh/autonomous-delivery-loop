"""Durable follow-up claims and push receipts. GitHub access here is read-only."""
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time

from .upstream_ci import FAILED, PR_URL, gh_json


SECOND = 10**9
MAX_OBSERVATION_AGE = 15 * 60 * SECOND
REPAIR_LIMIT = 2
SHA = re.compile(r"[0-9a-f]{40}")
REPAIR_KEY = re.compile(r"[a-z0-9][a-z0-9._:-]{0,119}", re.ASCII)

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    pr TEXT PRIMARY KEY,
    scan INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
    id TEXT PRIMARY KEY,
    pr TEXT NOT NULL REFERENCES observations(pr),
    head TEXT NOT NULL,
    base TEXT NOT NULL,
    scan INTEGER NOT NULL,
    kind TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    evidence TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    lease TEXT,
    expires INTEGER
);
CREATE INDEX IF NOT EXISTS actions_pr ON actions(pr);
CREATE TABLE IF NOT EXISTS pushes (
    lease TEXT PRIMARY KEY,
    action_id TEXT NOT NULL REFERENCES actions(id),
    pr TEXT NOT NULL,
    failure_key TEXT NOT NULL,
    candidate TEXT NOT NULL,
    repository TEXT NOT NULL,
    branch TEXT NOT NULL,
    reserved INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'unconfirmed'
);
CREATE INDEX IF NOT EXISTS pushes_pr ON pushes(pr, failure_key);
"""


def digest(value):
    return sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def followups(record):
    """Pick actionable CI and review signals independently of passive gates."""
    review = record.get("review", {})
    if (record.get("state") != "OPEN" or record.get("draft")
            or record["action"] == "lookup_failed" or review.get("action") == "lookup_failed"):
        return
    if record["action"] == "investigate_failure":
        signals = [item for item in record["signals"] if item["state"] in FAILED]
        if signals:
            names = sorted({item["name"] for item in signals})
            yield "investigate_failure", names, signals
    kind = review.get("action")
    if kind in {"resolve_conflicts", "check_branch_update"}:
        yield kind, [record["base_branch"]], {"base_branch": record["base_branch"]}
    if kind == "inspect_review_feedback":
        links = {
            item["url"] for item in review["unresolved_threads"]
            if item["participant"] == "human" and not item["outdated"] and item.get("url")
        }
        links.update(item["url"] for item in review["reviews"]
                     if item["participant"] == "human" and item["state"] == "CHANGES_REQUESTED")
        identity = sorted(links) or [review["decision"]]
        yield kind, identity, {"links": sorted(links), "decision": review["decision"]}


def live_pr(url):
    repo, number = PR_URL.fullmatch(url).groups()
    return gh_json("pr", "view", number, "--repo", repo, "--json",
                   "state,isDraft,headRefOid,baseRefOid,headRefName,headRepository")


def is_ancestor(repo, candidate, head):
    comparison = gh_json("api", f"repos/{repo}/compare/{candidate}...{head}", "--jq", "{status,behind_by}")
    return comparison["status"] == "ahead" and comparison["behind_by"] == 0


class ActionLedger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def _connection(self, *, write=False):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys = ON")
            with db:
                if write:
                    db.execute("BEGIN IMMEDIATE")
                yield db
        finally:
            db.close()

    def observe(self, records, scan):
        result = {"observed": 0, "planned": 0, "ignored_older": 0, "reconciled": 0}
        with self._connection(write=True) as db:
            for record in records:
                url = record["url"].lower()
                if not PR_URL.fullmatch(url):
                    raise ValueError("expected a GitHub pull request URL")
                updated = db.execute(
                    """INSERT INTO observations VALUES (?, ?)
                    ON CONFLICT(pr) DO UPDATE SET scan=excluded.scan
                    WHERE excluded.scan > observations.scan""", (url, scan),
                ).rowcount
                if not updated:
                    result["ignored_older"] += 1
                    continue
                result["observed"] += 1
                head, base = record.get("head"), record.get("base")
                if not SHA.fullmatch(head or "") or not SHA.fullmatch(base or ""):
                    continue
                result["reconciled"] += self._mark_applied(db, url, head, scan)
                for kind, identity, evidence in followups(record):
                    fingerprint = digest([kind, identity])
                    action_id = digest([url, head, base, fingerprint])
                    result["planned"] += db.execute(
                        """INSERT OR IGNORE INTO actions
                        (id, pr, head, base, scan, kind, fingerprint, evidence)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (action_id, url, head, base, scan, kind, fingerprint, json.dumps(evidence)),
                    ).rowcount
                    db.execute("UPDATE actions SET scan=?, evidence=? WHERE id=?",
                               (scan, json.dumps(evidence), action_id))
        return result

    @staticmethod
    def _mark_applied(db, url, head, checked_after):
        matched = db.execute(
            """SELECT lease, action_id FROM pushes WHERE pr=? AND candidate=?
            AND state='unconfirmed' AND reserved<?""",
            (url, head, checked_after),
        ).fetchall()
        for push in matched:
            db.execute("UPDATE pushes SET state='applied' WHERE lease=?", (push["lease"],))
            db.execute("UPDATE actions SET done=1, lease=NULL, expires=NULL WHERE id=?", (push["action_id"],))
        return len(matched)

    @staticmethod
    def _action(db, action_id):
        row = db.execute(
            """SELECT a.*, o.scan AS latest FROM actions a
            JOIN observations o ON o.pr=a.pr WHERE a.id=?""", (action_id,),
        ).fetchone()
        if row is None:
            raise ValueError("unknown action")
        return row

    @staticmethod
    def _require_current(row, now):
        if row["done"] or row["scan"] != row["latest"] or not 0 <= now - row["scan"] <= MAX_OBSERVATION_AGE:
            raise ValueError("action is complete or stale; refresh upstream CI and review")

    @staticmethod
    def _require_lease(row, lease, now):
        if not row["lease"] or row["lease"] != lease or row["expires"] <= now:
            raise ValueError("action lease is missing, expired, or held by another worker")

    def claim(self, action_id, *, seconds=900):
        if not 1 <= seconds <= 1800:
            raise ValueError("lease must last 1–1800 seconds")
        with self._connection(write=True) as db:
            now = time.time_ns()
            row = self._action(db, action_id)
            self._require_current(row, now)
            if db.execute("SELECT 1 FROM pushes WHERE pr=? AND state='unconfirmed'", (row["pr"],)).fetchone():
                raise ValueError("PR has an unconfirmed push; reconcile it before claiming more work")
            if db.execute(
                "SELECT 1 FROM actions WHERE pr=? AND lease IS NOT NULL AND expires>?",
                (row["pr"], now),
            ).fetchone():
                raise ValueError("PR already has an active lease")
            lease = secrets.token_hex(16)
            db.execute("UPDATE actions SET lease=?, expires=? WHERE id=?",
                       (lease, now + seconds * SECOND, action_id))
            return {"id": action_id, "pr": row["pr"], "head": row["head"], "base": row["base"],
                    "kind": row["kind"], "lease": lease}

    def finish(self, action_id, lease):
        """Close an investigated action that did not reserve a push."""
        with self._connection(write=True) as db:
            row = self._action(db, action_id)
            self._require_lease(row, lease, time.time_ns())
            if db.execute("SELECT 1 FROM pushes WHERE lease=?", (lease,)).fetchone():
                raise ValueError("reconcile the registered push first")
            db.execute("UPDATE actions SET done=1, lease=NULL, expires=NULL WHERE id=?", (action_id,))
        return {"id": action_id, "state": "done"}

    def reserve_push(self, action_id, lease, failure_key, receipt):
        candidate = receipt.get("candidate")
        readiness = receipt.get("readiness") or {}
        if (receipt.get("verdict") != "verified" or (readiness.get("suite") or {}).get("passed") is not True
                or not SHA.fullmatch(candidate or "")):
            raise ValueError("a verified upstream-prepare receipt with the exact candidate is required")
        if not REPAIR_KEY.fullmatch(failure_key):
            raise ValueError("use a stable lowercase repair key for this failure across heads")
        with self._connection() as db:
            original = self._action(db, action_id)
        remote = live_pr(original["pr"])
        with self._connection(write=True) as db:
            row = self._action(db, action_id)
            now = time.time_ns()
            self._require_current(row, now)
            self._require_lease(row, lease, now)
            if (remote["state"] != "OPEN" or remote["isDraft"] or remote["headRefOid"] != row["head"]
                    or remote["baseRefOid"] != row["base"] or not remote["headRepository"]
                    or not remote["headRefName"] or candidate == row["head"]):
                raise ValueError("GitHub head, base, or PR state changed; refresh before reserving a push")
            if db.execute("SELECT 1 FROM pushes WHERE pr=? AND state='unconfirmed'", (row["pr"],)).fetchone():
                raise ValueError("PR has an unconfirmed push; reconcile it before reserving another")
            if db.execute(
                """SELECT 1 FROM pushes p JOIN actions a ON p.action_id=a.id
                WHERE p.pr=? AND a.fingerprint=? AND p.failure_key<>?""",
                (row["pr"], row["fingerprint"], failure_key),
            ).fetchone():
                raise ValueError("this signal already has a repair key; keep it across heads")
            count = db.execute("SELECT count(*) FROM pushes WHERE pr=? AND failure_key=?",
                               (row["pr"], failure_key)).fetchone()[0]
            if count >= REPAIR_LIMIT:
                raise ValueError("repair budget exhausted for this PR and failure")
            repository, branch = remote["headRepository"]["nameWithOwner"], remote["headRefName"]
            db.execute("""INSERT INTO pushes
                       (lease, action_id, pr, failure_key, candidate, repository, branch, reserved)
                       VALUES (?,?,?,?,?,?,?,?)""",
                       (lease, action_id, row["pr"], failure_key, candidate, repository, branch, now))
            return {"id": action_id, "state": "unconfirmed", "candidate": candidate,
                    "expected_head": row["head"], "head_repository": repository,
                    "head_ref": branch, "attempt": count + 1}

    def reconcile(self, action_id, *, confirmed_not_sent=False):
        with self._connection() as db:
            row = self._action(db, action_id)
            push = db.execute("SELECT * FROM pushes WHERE action_id=? ORDER BY rowid DESC LIMIT 1",
                              (action_id,)).fetchone()
        if push is None:
            raise ValueError("action has no registered push")
        if push["state"] != "unconfirmed":
            return {"id": action_id, "state": push["state"]}
        checked_after = time.time_ns()
        remote = live_pr(row["pr"])
        remote_head = remote["headRefOid"]
        if not SHA.fullmatch(remote_head or ""):
            raise ValueError("GitHub did not return the current PR head")
        reached = remote_head == push["candidate"]
        if (not reached and not confirmed_not_sent and remote_head != row["head"]
                and (remote["headRepository"] or {}).get("nameWithOwner") == push["repository"]
                and remote["headRefName"] == push["branch"]):
            reached = is_ancestor(push["repository"], push["candidate"], remote_head)
        with self._connection(write=True) as db:
            state = db.execute("SELECT state FROM pushes WHERE lease=?", (push["lease"],)).fetchone()[0]
            if state == "unconfirmed":
                if reached:
                    if self._mark_applied(db, row["pr"], push["candidate"], checked_after):
                        state = "applied"
                elif confirmed_not_sent:
                    db.execute("UPDATE pushes SET state='not_sent' WHERE lease=?", (push["lease"],))
                    db.execute("UPDATE actions SET lease=NULL, expires=NULL WHERE id=?", (action_id,))
                    state = "not_sent"
            return {"id": action_id, "state": state, "observed_head": remote_head}

    def status(self):
        with self._connection() as db:
            now = time.time_ns()
            db.execute("BEGIN")
            tracked = db.execute("SELECT count(*) FROM observations").fetchone()[0]
            pending = [dict(row) for row in db.execute(
                """SELECT a.id, a.pr, a.head, a.base, a.kind, a.fingerprint, a.evidence,
                       CASE WHEN EXISTS (SELECT 1 FROM pushes p
                            WHERE p.pr=a.pr AND p.state='unconfirmed') THEN 'reconcile'
                            WHEN a.lease IS NOT NULL AND a.expires>? THEN 'leased'
                            WHEN EXISTS (SELECT 1 FROM actions l WHERE l.pr=a.pr
                                AND l.lease IS NOT NULL AND l.expires>?)
                                THEN 'wait_for_lease'
                            ELSE 'ready' END AS state
                FROM actions a JOIN observations o ON a.pr=o.pr AND a.scan=o.scan
                WHERE a.done=0 AND ? BETWEEN a.scan AND a.scan+?
                ORDER BY a.pr, a.kind, a.id""", (now, now, now, MAX_OBSERVATION_AGE),
            )]
            for action in pending:
                action["evidence"] = json.loads(action["evidence"])
            unresolved = [dict(row) for row in db.execute(
                """SELECT p.action_id AS id, p.pr, a.head AS expected_head, p.candidate, p.failure_key,
                   p.repository, p.branch
                FROM pushes p JOIN actions a ON a.id=p.action_id WHERE p.state='unconfirmed'
                ORDER BY p.pr""",
            )]
            history = [dict(row) for row in db.execute(
                "SELECT pr, failure_key, count(*) AS attempts FROM pushes GROUP BY pr, failure_key ORDER BY pr, failure_key",
            )]
            return {"tracked_prs": tracked, "pending": pending, "unconfirmed_pushes": unresolved,
                    "repair_attempts": history}
