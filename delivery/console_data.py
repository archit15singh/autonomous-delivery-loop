"""Read-only projections of the factory's local receipts and Codex exec logs."""

from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import stat
from urllib.parse import unquote, urlsplit, urlunsplit

from .factory_score import WEIGHTS
from .github import PR_URL
from .revisions import FULL_REVISION
from .run_index import ASSESSMENTS, KEY, MODES


_JSON_BYTES = 8 * 1024 * 1024
_TRACE_BYTES = 4 * 1024 * 1024
_EVENT_LIMIT = 250
_MESSAGE_LIMIT = 2000
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_FLAGS = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
_ROUND = re.compile(r"round([0-9]{1,12})\.json")
_SAFE_ID = re.compile(r"[a-f0-9]{64}")
_ITEM_ID = re.compile(r"item_[0-9]{1,16}")
_EVENT_TYPES = {
    "thread.started", "turn.started", "turn.completed", "turn.failed",
    "item.started", "item.updated", "item.completed", "error",
}
_ITEM_TYPES = {
    "agent_message", "reasoning", "command_execution", "file_change",
    "mcp_tool_call", "collab_tool_call", "web_search", "todo_list", "error",
}
# Probe exact receipt layouts and a few named slots. Never recurse into checkouts.
_TRACE_LAYOUTS = (
    "events.jsonl", "named-codex.jsonl", "factory-build/agent/events.jsonl",
    "owned-pilot/runs/*/codex.jsonl", "review-transcripts/*/events.jsonl",
    "local-codex-*/*/writer.jsonl", "local-codex-*/review-transcripts/*/events.jsonl",
    "local-codex-*/upstream/final/events.jsonl", "live-targets/*/proposal/events.jsonl",
    "upstream/*/proposal/events.jsonl", "lima-repair-*/events.jsonl",
)

_SECRETS = re.compile(
    r"-----BEGIN [^\n-]*PRIVATE KEY-----[\s\S]*?(?:-----END [^\n-]*PRIVATE KEY-----|\Z)"
    r"|\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/-]+=*"
    r"|\b(?:github_pat_|gh[pousr]_|sk-|xox[baprs]-)[A-Za-z0-9_-]{8,}"
    r"|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
    r"|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"
    r"|(?<=://)[^\s/@]+:[^\s/@]+(?=@)"
    r"|\b(?:set-cookie|cookie)[\"']?[ \t]*:[ \t]*[^\r\n]+"
    r"|(?<![\w.-])[\w.-]{0,64}(?:token|password|passwd|secret|credential|api[-_ ]?key|authorization|"
    r"cookie|signature|private[-_ ]?key|session[-_ ]?id)[\w.-]{0,64}[\"']?"
    r"[ \t]*[:=][ \t]*"
    r"(?:(?:Bearer|Basic)[ \t]+[A-Za-z0-9._~+/-]+=*"
    r"|\"(?:\\.|[^\"\\\n])*\"|'[^'\n]*'|[^\s,;&<>\"'`]+)"
    r"|--(?:token|password|api-key|secret)[ \t]+(?:\"[^\"\n]*\"|'[^'\n]*'|[^\s]+)",
    re.IGNORECASE,
)
_PASTED_OUTPUT = re.compile(
    r"(?m)^[ \t]*(?:```|~~~)[^\n]*\n[\s\S]*?(?:^[ \t]*(?:```|~~~)[^\n]*|\Z)"
    r"|^[ \t]*(?:(?:\$|>>>|export|stderr:)\s+|[A-Z_][A-Z0-9_]*=)[^\n]*"
)
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff]")
_MESSAGE_URL = re.compile(r"https?://[^\s<>\"'`]+")


@contextmanager
def _directory(root, parts=()):
    # Resolve each component against the open parent with O_NOFOLLOW. A concurrent
    # rename can replace a receipt but cannot redirect the open through a symlink.
    with ExitStack() as stack:
        fd = os.open(root, _DIRECTORY_FLAGS)
        stack.callback(os.close, fd)
        for part in parts:
            fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=fd)
            stack.callback(os.close, fd)
        yield fd


def _read(root, parts, limit, *, growing=False):
    try:
        with _directory(root, parts[:-1]) as parent:
            fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=parent)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode) or (not growing and before.st_size > limit):
                    return None
                with os.fdopen(fd, "rb", closefd=False) as stream:
                    data = stream.read(limit + 1)
                after = os.fstat(fd)
                if not growing and (len(data) != before.st_size or len(data) > limit
                                    or before.st_mtime_ns != after.st_mtime_ns
                                    or before.st_size != after.st_size):
                    return None
                return data, before.st_mtime_ns
            finally:
                os.close(fd)
    except OSError:
        return None


def _names(root, parts):
    try:
        with _directory(root, parts) as fd:
            return sorted(os.listdir(fd))
    except OSError:
        return []


def _parse(data):
    try:
        return json.loads(data)
    except (ValueError, RecursionError):
        return None


def _json(root, *parts):
    source = _read(root, parts, _JSON_BYTES)
    return _parse(source[0]) if source else None


def _object(value):
    return value if isinstance(value, dict) else {}


def _array(value):
    return value if isinstance(value, list) else []


def _match(pattern, value):
    return pattern.fullmatch(value) if isinstance(value, str) else None


def _code(value):
    if isinstance(value, str) and len(value) <= 80 and KEY.fullmatch(value.lower()) and not _SECRETS.search(value):
        return value
    return None


def _sha(value):
    return value if _match(FULL_REVISION, value) else None


def _pr_url(value):
    match = _match(PR_URL, value) if isinstance(value, str) and len(value) <= 512 else None
    if match and len(match[2]) <= 15 and not _SECRETS.search(match[1]):
        return value
    return None


def _display(value, limit=300):
    if not isinstance(value, str):
        return None
    text = _CONTROL.sub("", _ANSI_ESCAPE.sub("", value))
    return _SECRETS.sub("[redacted]", text).strip()[:limit] or None


def _link(value):
    if not isinstance(value, str) or len(value) > 4096:
        return None
    try:
        url = urlsplit(value)
        if url.scheme != "https" or not re.fullmatch(r"[A-Za-z0-9.-]+", url.netloc):
            return None
        if _SECRETS.search(unquote(url.netloc + url.path)) or any(c in value for c in "\\ \t\r\n"):
            return None
        return urlunsplit((url.scheme, url.netloc, url.path, "", ""))
    except ValueError:
        return None


def _date(mtime_ns):
    return datetime.fromtimestamp(mtime_ns / 1_000_000_000, timezone.utc).isoformat()


def _timestamp(value):
    if isinstance(value, str) and len(value) <= 40:
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.utcoffset() is not None:
                return parsed.astimezone(timezone.utc)
        except (ValueError, OverflowError):
            pass
    return None


def _number(value):
    if type(value) is int and 0 <= value <= 2**53 - 1:
        return value
    if type(value) is float and math.isfinite(value) and 0 <= value <= 2**53 - 1:
        return value
    return None


def _complete_round(rows):
    if not isinstance(rows, list) or not rows:
        return False
    for row in rows:
        row = _object(row)
        if _pr_url(row.get("url")) and row.get("action") == "lookup_failed":
            continue
        if (not _pr_url(row.get("url")) or _code(row.get("state")) not in {"OPEN", "CLOSED", "MERGED"}
                or not _code(row.get("action"))
                or not _sha(row.get("head")) or not _sha(row.get("base"))
                or not isinstance(row.get("signals"), list)):
            return False
    return True


def _round(root):
    candidates = []
    try:
        with _directory(root, ("upstream-ci",)) as fd:
            for name in os.listdir(fd):
                match = _ROUND.fullmatch(name)
                if name != "current.json" and not match:
                    continue
                try:
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISREG(info.st_mode):
                    candidates.append((info.st_mtime_ns, int(match[1]) if match else -1, name))
    except OSError:
        pass
    for _, _, name in sorted(candidates, reverse=True):
        source = _read(root, ("upstream-ci", name), _JSON_BYTES)
        if source and _complete_round(rows := _parse(source[0])):
            return rows, name, _date(source[1])
    return [], None, None


def _titles(root, rows):
    wanted = {row["url"].lower() for row in rows if not _display(row.get("title"))}
    titles = {}
    if not wanted:
        return titles
    authored = _object(_json(root, "upstream-ci", "requested-repositories-authored.json"))
    precedents = _object(_json(root, "upstream-ci", "merge-precedents.json"))
    groups = list(authored.values()) + [
        _object(branch).get("sample") for branch in _array(precedents.get("branches"))
    ]
    for group in groups:
        for item in _array(group):
            item = _object(item)
            url = _pr_url(item.get("url"))
            if url and url.lower() in wanted and (title := _display(item.get("title"))):
                titles.setdefault(url.lower(), title)
    return titles


def _pr_rows(rows, titles):
    result = {}
    for row in rows:
        url = row["url"]
        repo, number = PR_URL.fullmatch(url).groups()
        checks = []
        for check in _array(row.get("signals")):
            check = _object(check)
            if name := _display(check.get("name")):
                checks.append({"name": name, "state": _code(check.get("state")) or "unknown",
                               "url": _link(check.get("url"))})
        review = _object(row.get("review"))
        # Keep GitHub review decisions separate from the CI action.
        result.setdefault(url.lower(), {
            "id": url, "url": url, "repo": repo, "number": int(number),
            "created_at": row.get("created_at") if _timestamp(row.get("created_at")) else None,
            "merged_at": row.get("merged_at") if _timestamp(row.get("merged_at")) else None,
            "title": _display(row.get("title")) or titles.get(url.lower()) or f"{repo} #{number}",
            "state": "UNKNOWN" if row["action"] == "lookup_failed" else row["state"], "action": row["action"], "head": _sha(row.get("head")),
            "base": _sha(row.get("base")), "checks": checks,
            "review": {key: value for key in ("decision", "action", "merge_state", "mergeable")
                       if (value := _code(review.get(key)))},
        })
    return list(result.values())


def _round_scores(root, round_name):
    if not round_name:
        return {}
    filename = f"score-{round_name}" if _ROUND.fullmatch(round_name) else "scorecard.json"
    report = _object(_json(root, "upstream-ci", filename))
    scores = {}
    for row in _array(report.get("rows")):
        row = _object(row)
        run_id = _code(_object(row.get("evidence")).get("replay"))
        pr, head = _pr_url(row.get("subject")), _sha(row.get("head"))
        if run_id and pr and head:
            evidence = _object(row.get("points"))
            points = {key: value for key in WEIGHTS if (value := _number(evidence.get(key))) is not None}
            if points and (score := _number(row.get("score"))) == sum(points.values()):
                scores[(run_id, pr.lower(), head)] = {"score": score, "points": points}
    return scores


def _run_rows(root, scores):
    result = []
    for name in _names(root, ("factory-runs",)):
        if not name.endswith(".json") or not KEY.fullmatch(name[:-5]):
            continue
        row = _object(_json(root, "factory-runs", name))
        run_id = row.get("id")
        finished = _timestamp(row.get("finished_at"))
        head, pr = _sha(row.get("head")), _pr_url(row.get("pr"))
        if run_id != name[:-5] or not _code(run_id) or not finished or not head:
            continue
        outcome = _object(row.get("outcome"))
        states = {key: value for key in ("workflow", "readiness", "runtime", "browser", "pr", "ci", "review")
                  if (value := _code(outcome.get(key)))}
        assessment = _object(outcome.get("assessment"))
        run_scores = {key: value for key in sorted(ASSESSMENTS)
                      if (value := _code(assessment.get(key))) in MODES}
        if pr:
            run_scores.update(scores.get((run_id, pr.lower(), head), {}))
        receipts = []
        for receipt in _object(row.get("receipts")).values():
            filename = _object(receipt).get("file")
            if _match(KEY, filename):
                receipts.append(_display(filename))
        retries = _object(row.get("retries"))
        metrics = _object(row.get("metrics"))
        findings = []
        for finding in _array(row.get("findings")):
            finding = _object(finding)
            fields = ("dimension", "reason", "category")
            if all(_code(finding.get(key)) for key in fields):
                findings.append({key: _display(finding[key]) for key in fields})
        # Outcome remains a short display value. Keep the individual receipt states.
        primary = _code(row.get("outcome"))
        if not primary and states:
            primary = next((state for state in states.values()
                            if state in {"failed", "inconclusive", "blocked"}), next(iter(states.values())))
        result.append((finished, {
            "id": run_id, "pr": pr, "head": head, "finished_at": finished.isoformat(),
            "outcome": primary or "unknown", "tokens": _number(metrics.get("tokens")),
            "seconds": _number(metrics.get("wall_seconds")),
            "interventions": _number(metrics.get("human_interventions")),
            "receipts": receipts, "scores": run_scores,
            "details": {"base": _sha(row.get("base")), "factory_revision": _sha(row.get("factory_revision")),
                        "outcome": states, "retries": {key: _number(retries.get(key))
                                                       for key in ("product", "infrastructure")},
                        "findings": findings},
        }))
    result.sort(key=lambda item: (item[0], item[1]["id"]), reverse=True)
    return [row for _, row in result]


def _trace_paths(root):
    paths = set()
    for layout in _TRACE_LAYOUTS:
        prefixes = [()]
        for part in layout.split("/"):
            if "*" in part:
                prefixes = [prefix + (name,) for prefix in prefixes for name in _names(root, prefix)
                            if _match(KEY, name) and fnmatchcase(name, part)]
            else:
                prefixes = [prefix + (part,) for prefix in prefixes]
        paths.update(prefixes)
    return {sha256("/".join(parts).encode()).hexdigest(): parts for parts in sorted(paths)}


def _usage(event):
    usage = _object(event.get("usage"))
    if not all(type(value := usage.get(key)) is int and _number(value) is not None
               for key in ("input_tokens", "output_tokens")):
        return None
    return {key: usage[key] for key in ("input_tokens", "cached_input_tokens", "output_tokens")
            if type(usage.get(key)) is int and _number(usage[key]) is not None}


def _trace_event(line, event, include_messages):
    kind = event["type"]
    result = {"line": line, "type": kind}
    if kind == "turn.completed" and (usage := _usage(event)) is not None:
        result["usage"] = usage
    item = _object(event.get("item"))
    item_type = item.get("type")
    if isinstance(item_type, str) and item_type in _ITEM_TYPES:
        info = {"type": item_type}
        if _match(_ITEM_ID, item.get("id")):
            info["id"] = item["id"]
        if item_type == "command_execution":
            status = item.get("status")
            if status in ("in_progress", "completed", "failed"):
                info["status"] = status
            exit_code = item.get("exit_code")
            if type(exit_code) is int and -255 <= exit_code <= 255:
                info["exit_code"] = exit_code
        if item_type == "agent_message" and kind == "item.completed" and isinstance(item.get("text"), str):
            info["has_text"] = bool(item["text"])
            if include_messages and info["has_text"]:
                body = _PASTED_OUTPUT.sub("[redacted output]", item["text"])
                body = _MESSAGE_URL.sub(lambda match: _link(match[0]) or "[redacted URL]", body)
                message = _display(body, _TRACE_BYTES) or ""
                result["text"] = message[:_MESSAGE_LIMIT]
                if len(message) > _MESSAGE_LIMIT:
                    result["text_truncated"] = True
        result["item"] = info
    return result


def _read_trace(root, trace_id, parts, *, detail=False, include_messages=False):
    source = _read(root, parts, _TRACE_BYTES, growing=True)
    if not source:
        return None
    data, date = source
    byte_limited = len(data) > _TRACE_BYTES
    if byte_limited:
        data = data[:_TRACE_BYTES].rpartition(b"\n")[0]
    events = []
    count = turns = tokens = usage_turns = skipped = 0
    for line_number, line in enumerate(data.split(b"\n"), 1):
        if not line.strip():
            continue
        event = _object(_parse(line))
        kind = event.get("type")
        if not isinstance(kind, str) or kind not in _EVENT_TYPES:
            skipped += 1
            continue
        count += 1
        turns += kind == "turn.started"
        if kind == "turn.completed" and (usage := _usage(event)) is not None:
            tokens += usage["input_tokens"] + usage["output_tokens"]
            usage_turns += 1
        if detail and len(events) < _EVENT_LIMIT:
            events.append(_trace_event(line_number, event, include_messages))
    if not count:
        return None
    result = {"id": trace_id, "label": _display("/".join(parts)), "date": _date(date),
              "turns": turns, "tokens": tokens if usage_turns else None, "events_count": count}
    if byte_limited:
        result["counts_truncated"] = True
    if detail:
        result.update(events=events, truncated=byte_limited or count > _EVENT_LIMIT,
                      counts_truncated=byte_limited, skipped_events=skipped,
                      messages_included=include_messages)
    return result


def snapshot(root: Path) -> dict:
    """Return local PRs, indexed runs and transcript summaries.

    as_of is the selected PR receipt's UTC modification time, or None.
    Trace counts describe recognized events within the byte budget.
    """
    evidence = root / ".adl"
    rows, name, as_of = _round(evidence)
    traces = [summary for trace_id, parts in _trace_paths(evidence).items()
              if (summary := _read_trace(evidence, trace_id, parts))]
    traces.sort(key=lambda row: (row["date"], row["id"]), reverse=True)
    return {"prs": _pr_rows(rows, _titles(evidence, rows)),
            "runs": _run_rows(evidence, _round_scores(evidence, name)),
            "traces": traces, "as_of": as_of}


def trace(root: Path, id: str, *, include_messages: bool = True) -> dict | None:
    """Return at most 250 events in file order, or None for an unavailable ID.

    Call this on explicit transcript inspection. Pass include_messages=False
    for metadata only. Message text is redacted and length-limited.
    """
    if not _match(_SAFE_ID, id):
        return None
    evidence = root / ".adl"
    parts = _trace_paths(evidence).get(id)
    if parts:
        return _read_trace(evidence, id, parts, detail=True, include_messages=include_messages)
    return None
