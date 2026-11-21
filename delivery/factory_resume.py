"""Rebuild a small operator brief from existing factory state after a context reset."""
import time

from .revisions import git
from .run_index import indexed_runs
from .upstream_actions import ActionLedger
from .upstream_ci import attach_local_replay, inspect_prs


def resume(workspace, state_dir, note, pr=None):
    queue = state_dir / "upstream-ci"
    memory = note if note is not None else queue / "active.md"
    if note is not None or memory.exists():
        saved = memory.read_text(encoding="utf-8")
    else:
        saved = None
    brief = {
        "workspace": str(workspace.resolve()),
        "revision": git("rev-parse", "HEAD", cwd=workspace).decode().strip(),
        "changes": git("status", "--short", cwd=workspace).decode().splitlines(),
        "note_path": str(memory.resolve()), "operator_note": saved,
        "follow_up_history": str((queue / "follow-up.md").resolve()),
    }
    if pr is None:
        return brief, 0

    # A missing database in a new worktree is not evidence of an empty ledger.
    ledger_path = queue / "actions.sqlite3"
    if not ledger_path.is_file():
        raise ValueError("existing action ledger missing; select the canonical .adl with --state-dir")
    runs = indexed_runs(state_dir / "factory-runs")
    ledger = ActionLedger(ledger_path)
    scan = time.time_ns()
    record, = inspect_prs([pr], review=True)
    attach_local_replay([record], runs)
    failed = "lookup_failed" in (record["action"], record.get("review", {}).get("action"))
    superseded = False
    if not failed:
        superseded = bool(ledger.observe([record], scan)["ignored_older"])
    state = ledger.status()
    for key in ("pending", "active_leases", "unconfirmed_pushes", "repair_attempts"):
        brief[key] = [item for item in state[key] if item["pr"] == pr.lower()]
    brief["pr"] = record
    if failed or superseded:
        brief["pending"] = []
        disposition = "refresh_observation"
    elif brief["unconfirmed_pushes"]:
        disposition = "reconcile_push"
    elif brief["active_leases"]:
        disposition = "respect_existing_lease"
    elif record.get("state") in {"MERGED", "CLOSED"}:
        disposition = record["state"].lower()
    else:
        disposition = record.get("review", {}).get("action", record["action"])
    brief["disposition"] = disposition
    return brief, int(failed or superseded)
