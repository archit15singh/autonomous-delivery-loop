"""Resolve native Codex rollouts for the descendants of one local CLI session."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3

from .run_state import record


def identifier(value):
    return isinstance(value, str) and bool(value.strip())


def native_counts(value):
    keys = ("input_tokens", "cached_input_tokens", "output_tokens")
    if not isinstance(value, dict):
        raise ValueError("missing_native_usage")
    counts = {key: value.get(key) for key in keys}
    if any(type(count) is not int or count < 0 for count in counts.values()):
        raise ValueError("missing_native_usage")
    if counts["cached_input_tokens"] > counts["input_tokens"]:
        raise ValueError("invalid_native_usage")
    return counts


def native_session(path, thread_id, parent_id):
    """Read only accounting fields from an exact, identity-checked rollout."""
    with Path(path).open(encoding="utf-8") as stream:
        first = json.loads(next(stream, "{}"))
        meta = first.get("payload")
        if first.get("type") != "session_meta" or not isinstance(meta, dict):
            raise ValueError("invalid_session_meta")
        if meta.get("id") != thread_id or meta.get("parent_thread_id") != parent_id:
            raise ValueError("session_identity_mismatch")
        if parent_id is not None:
            source = meta.get("source")
            spawn = source.get("subagent") if isinstance(source, dict) else None
            spawn = spawn.get("thread_spawn") if isinstance(spawn, dict) else None
            if not isinstance(spawn, dict) or spawn.get("parent_thread_id") != parent_id:
                raise ValueError("session_identity_mismatch")

        active = None
        turns = 0
        models = {}
        children = set()
        counts = None
        for index, line in enumerate(stream):
            event = json.loads(line)
            kind, payload = event["type"], event["payload"]
            if kind == "session_meta":
                # A full-context fork can embed the parent rollout before the
                # settings marker for this child. Its aborted turn is inherited.
                if index != 0 or not parent_id or payload.get("id") != parent_id:
                    raise ValueError("invalid_session_meta")
                for inherited in stream:
                    copied = json.loads(inherited)
                    item = copied["payload"]
                    if copied["type"] != "event_msg":
                        continue
                    if item.get("type") == "token_count" and item.get("info"):
                        raise ValueError("ambiguous_inherited_usage")
                    if item.get("type") == "thread_settings_applied" and item.get("thread_id") == thread_id:
                        break
                else:
                    raise ValueError("incomplete_fork_context")
                continue
            if kind == "turn_context":
                model, turn = payload.get("model"), payload.get("turn_id")
                if not identifier(model) or not identifier(turn):
                    raise ValueError("missing_session_model")
                models.setdefault(turn, set()).add(model)
            if kind != "event_msg":
                continue
            kind = payload.get("type")
            if kind == "item_completed":
                item = payload.get("item")
                if isinstance(item, dict) and item.get("type") == "SubAgentActivity":
                    child = item.get("agent_thread_id")
                    if not identifier(child):
                        raise ValueError("unidentified_native_child")
                    if item.get("kind") in ("started", "completed"):
                        children.add(child)
            if kind == "task_started":
                turn = payload.get("turn_id")
                if active is not None or not identifier(turn):
                    raise ValueError("incomplete_native_session")
                active, snapshot = turn, None
            elif kind == "token_count":
                if active is None:
                    raise ValueError("incomplete_native_session")
                info = payload.get("info")
                snapshot = info.get("total_token_usage") if isinstance(info, dict) else None
            elif kind == "task_complete":
                if active is None or payload.get("turn_id") != active:
                    raise ValueError("incomplete_native_session")
                if active not in models:
                    raise ValueError("missing_session_model")
                current = native_counts(snapshot)
                if counts and any(current[key] < counts[key] for key in current):
                    raise ValueError("invalid_native_usage")
                counts = current
                turns += 1
                active = None
            elif kind in {"turn_aborted", "thread_rolled_back", "error"}:
                raise ValueError("incomplete_native_session")
        if active is not None or not turns:
            raise ValueError("incomplete_native_session")
        provider = meta.get("model_provider")
        if not models or not identifier(provider):
            raise ValueError("missing_session_model")
        return {"usage": counts, "turns": turns, "models": sorted(set().union(*models.values())), "provider": provider,
                "child_thread_ids": sorted(children)}


def capture_tree(events, source, parent, env=None):
    """Write the private completion receipt for an opted-in exec log.

    The runner can mark the same path with {"status":"pending"} before launch.
    A failed capture leaves an incomplete receipt, even if exec usage exists.
    """
    events = Path(events)
    signals = set(parent.signals)
    sessions = {}
    receipt = {"version": 1, "thread_id": source.thread_id, "sha256": source.digest,
               "sessions": sessions}
    pinned = bool(source.events and source.events[0]["type"] == "thread.started"
                  and source.thread_id is not None)
    if not pinned:
        signals.add("missing_parent_thread_id")
    if not parent.cache_known:
        signals.add("missing_parent_usage")
    if pinned and not source.signals:
        environment = os.environ if env is None else env
        home = Path(environment.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
        database = (home.absolute() / "state_5.sqlite").as_uri() + "?mode=ro"
        try:
            with closing(sqlite3.connect(database, uri=True)) as ledger:
                ledger.execute("BEGIN")
                pending = [(source.thread_id, None, None)]
                while pending:
                    thread_id, parent_id, status = pending.pop()
                    if thread_id in sessions:
                        signals.add("invalid_spawn_edge")
                        continue
                    entry = sessions[thread_id] = {"parent_thread_id": parent_id, "edge_status": status,
                                                   "rollout_path": None}
                    row = ledger.execute("SELECT rollout_path FROM threads WHERE id = ?", (thread_id,)).fetchall()
                    if len(row) == 1 and identifier(row[0][0]) and Path(row[0][0]).is_absolute():
                        entry["rollout_path"] = row[0][0]
                        try:
                            entry.update(native_session(row[0][0], thread_id, parent_id))
                        except (OSError, UnicodeError, TypeError, KeyError, AttributeError, json.JSONDecodeError):
                            entry["signal"] = "unreadable_native_session"
                        except ValueError as error:
                            entry["signal"] = str(error)
                    else:
                        entry["signal"] = "missing_native_rollout"
                    if "signal" in entry:
                        signals.add(entry["signal"])
                    edges = ledger.execute(
                        "SELECT child_thread_id, status FROM thread_spawn_edges WHERE parent_thread_id = ?",
                        (thread_id,),
                    ).fetchall()
                    if set(entry.get("child_thread_ids", ())) - {edge[0] for edge in edges}:
                        signals.add("missing_child_capture")
                    for child_id, edge_status in edges:
                        if not identifier(child_id) or edge_status not in {"open", "closed"}:
                            signals.add("invalid_spawn_edge")
                            continue
                        pending.append((child_id, thread_id, edge_status))
        except (sqlite3.Error, OSError, ValueError):
            signals.add("unavailable_session_ledger")

    root = sessions.get(source.thread_id, {})
    if "usage" in root and not matches_exec(root, parent):
        signals.add("parent_usage_mismatch")
    if parent.children - (sessions.keys() - {source.thread_id}):
        signals.add("missing_child_capture")
    receipt.update(status="incomplete" if signals else "complete", signals=sorted(signals))
    target = events.with_suffix(".sessions.json")
    record(target, receipt)
    return receipt


def matches_exec(entry, usage):
    counts = usage.counts()
    return entry["turns"] == usage.turns and all(
        counts[key] == value for key, value in entry["usage"].items()
    )


def load_sessions(path, transcript, parent):
    sidecar = path.with_suffix(".sessions.json")
    try:
        with sidecar.open(encoding="utf-8") as stream:
            transcript.capture_expected = True
            receipt = json.load(stream)
    except FileNotFoundError:
        if sidecar.is_symlink():
            transcript.capture_expected = True
            transcript.signals.add("invalid_session_capture")
        return
    except (OSError, ValueError, RecursionError):
        transcript.capture_expected = True
        transcript.signals.add("invalid_session_capture")
        return
    try:
        if isinstance(receipt, dict) and receipt.get("status") == "pending":
            transcript.signals.add("pending_session_capture")
            return
        validate_sessions(receipt, transcript, parent)
    except (AttributeError, KeyError, TypeError, ValueError):
        transcript.signals.add("invalid_session_capture")
        return
    transcript.sessions = receipt
    transcript.signals.update(receipt["signals"])


def validate_sessions(receipt, transcript, parent):
    keys = {"version", "thread_id", "sha256", "status", "sessions", "signals"}
    if (not isinstance(receipt, dict) or receipt.keys() != keys
            or type(receipt["version"]) is not int or receipt["version"] != 1):
        raise ValueError
    if receipt["thread_id"] != transcript.thread_id or receipt["sha256"] != transcript.digest:
        raise ValueError
    status, sessions, signals = receipt["status"], receipt["sessions"], receipt["signals"]
    if (status not in {"complete", "incomplete"} or not isinstance(sessions, dict)
            or not isinstance(signals, list) or not all(map(identifier, signals))
            or (status == "complete") != (not signals)):
        raise ValueError
    root_id = transcript.thread_id
    if (sessions or status == "complete") and root_id not in sessions:
        raise ValueError
    for thread_id, entry in sessions.items():
        if not identifier(thread_id) or not isinstance(entry, dict):
            raise ValueError
        base_keys = {"parent_thread_id", "edge_status", "rollout_path"}
        usage_keys = {"usage", "turns", "models", "provider", "child_thread_ids"}
        if entry.keys() not in (base_keys | {"signal"}, base_keys | usage_keys):
            raise ValueError
        parent_id, edge_status, path = (entry[key] for key in ("parent_thread_id", "edge_status", "rollout_path"))
        if thread_id == root_id:
            if parent_id is not None or edge_status is not None:
                raise ValueError
        elif not identifier(parent_id) or parent_id not in sessions or edge_status not in {"open", "closed"}:
            raise ValueError
        if "signal" in entry:
            if status != "incomplete" or not identifier(entry["signal"]) or entry["signal"] not in signals:
                raise ValueError
            if path is not None and (not identifier(path) or not Path(path).is_absolute()):
                raise ValueError
            continue
        if not identifier(path) or not Path(path).is_absolute():
            raise ValueError
        counts = entry["usage"]
        if native_counts(counts) != counts or type(entry["turns"]) is not int or entry["turns"] < 1:
            raise ValueError
        models = entry["models"]
        if not isinstance(models, list) or not models or not all(map(identifier, models)):
            raise ValueError
        children = entry["child_thread_ids"]
        if not isinstance(children, list) or not all(map(identifier, children)):
            raise ValueError
        if status == "complete" and any(
            child not in sessions or sessions[child].get("parent_thread_id") != thread_id for child in children
        ):
            raise ValueError
        if not identifier(entry["provider"]):
            raise ValueError
    if status == "complete":
        if not matches_exec(sessions[root_id], parent) or parent.children - (sessions.keys() - {root_id}):
            raise ValueError
    for thread_id in sessions:
        visited = set()
        while thread_id != root_id:
            if thread_id in visited:
                raise ValueError
            visited.add(thread_id)
            thread_id = sessions[thread_id]["parent_thread_id"]
