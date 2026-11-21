"""Summarize Codex exec event logs and captured native descendant sessions."""

import argparse
from dataclasses import dataclass, field
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from sys import float_info
from .codex_sessions import capture_tree, identifier, load_sessions, matches_exec


RATE_KEYS = ("uncached_input", "cached_input", "output")


def read_rates(path):
    """Read flat USD-per-million rates. Omitted or null rates are unknown."""
    rates = json.loads(path.read_text())
    if not isinstance(rates, dict) or rates.keys() - set(RATE_KEYS):
        raise ValueError(f"rates must be a JSON object with keys {', '.join(RATE_KEYS)}")
    for key, value in rates.items():
        if value is not None and (
            type(value) not in (int, float) or not 0 <= value <= float_info.max
        ):
            raise ValueError(f"invalid USD-per-million rate for {key}")
    return rates


@dataclass
class Transcript:
    thread_id: str | None = None
    events: list = field(default_factory=list)
    signals: set = field(default_factory=set)
    digest: str | None = None
    sessions: dict | None = None
    capture_expected: bool = False


def read_transcript(path, *, read_sessions=True):
    transcript = Transcript()
    digest = sha256()
    try:
        with path.open("rb") as stream:
            for line in stream:
                digest.update(line)
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    transcript.signals.add("invalid_event")
                    continue
                if not isinstance(event, dict) or not identifier(event.get("type")):
                    transcript.signals.add("invalid_event")
                    continue
                if event["type"] == "thread.started":
                    thread = event.get("thread_id")
                    if not identifier(thread):
                        transcript.signals.add("invalid_thread_id")
                    elif transcript.thread_id is None:
                        transcript.thread_id = thread
                    else:
                        transcript.signals.add("multiple_thread_starts")
                        break
                transcript.events.append(event)
    except (OSError, UnicodeError):
        transcript.signals.add("unreadable_transcript")
    transcript.digest = digest.hexdigest()
    if read_sessions and path.with_suffix(".sessions.json").exists():
        load_sessions(path, transcript, thread_usage(transcript))
    return transcript


@dataclass
class ThreadUsage:
    turns: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    cache_known: bool = True
    children: set = field(default_factory=set)
    signals: set = field(default_factory=set)

    def add_turn(self, usage):
        if not isinstance(usage, dict):
            self.signals.add("missing_or_invalid_usage")
            return
        counts = [usage.get(key) for key in ("input_tokens", "output_tokens", "cached_input_tokens")]
        input_tokens, output_tokens, cached = counts
        if (any(type(value) is not int or value < 0 for value in counts[:2])
                or (cached is not None and (type(cached) is not int or not 0 <= cached <= input_tokens))):
            self.signals.add("missing_or_invalid_usage")
            return
        self.turns += 1
        self.input_tokens += input_tokens
        self.cached_tokens += cached or 0
        self.output_tokens += output_tokens
        self.cache_known &= cached is not None

    def add(self, other):
        self.turns += other.turns
        self.input_tokens += other.input_tokens
        self.cached_tokens += other.cached_tokens
        self.output_tokens += other.output_tokens
        self.cache_known &= other.cache_known
        self.children.update(other.children)
        self.signals.update(other.signals)

    def counts(self):
        return {
            "turns_with_usage": self.turns,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_tokens if self.cache_known else None,
            "uncached_input_tokens": self.input_tokens - self.cached_tokens if self.cache_known else None,
            "output_tokens": self.output_tokens,
            "tokens": self.input_tokens + self.output_tokens,
        }


def thread_usage(transcript):
    usage = ThreadUsage(signals=set(transcript.signals))
    open_turn = False
    spawns = {}
    for index, event in enumerate(transcript.events):
        kind = event["type"]
        if kind == "turn.started":
            if open_turn:
                usage.signals.add("unfinished_turn")
            open_turn = True
        elif kind == "turn.completed":
            open_turn = False
            usage.add_turn(event.get("usage"))
        elif kind == "turn.failed":
            open_turn = False
            usage.signals.add(kind)
        elif kind == "error":
            usage.signals.add(kind)
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "collab_tool_call":
            continue
        receivers = item.get("receiver_thread_ids")
        children = {value for value in receivers if identifier(value)} if isinstance(receivers, list) else set()
        usage.children.update(children)
        if item.get("tool") == "spawn_agent":
            item_id = item.get("id")
            key = item_id if identifier(item_id) else index
            spawns.setdefault(key, set()).update(children)
    if open_turn:
        usage.signals.add("unfinished_turn")
    if not usage.turns:
        usage.signals.add("no_completed_usage")
    if any(not children for children in spawns.values()):
        usage.signals.add("unidentified_child_thread")
    return usage


def capture_sessions(events, env=None):
    """Attach native child usage to the exact parent exec transcript."""
    source = read_transcript(events, read_sessions=False)
    return capture_tree(events, source, thread_usage(source), env)


def estimate(counts, rates):
    if counts["uncached_input_tokens"] is None or not all(rates.get(key) is not None for key in RATE_KEYS):
        return None
    try:
        cost = sum(counts[f"{key}_tokens"] * (rates[key] / 1_000_000) for key in RATE_KEYS)
    except OverflowError:
        return None
    return cost if isfinite(cost) else None


def summarize(paths, rates=None):
    """Return observed usage and full-scope totals for the supplied exec logs.

    A same-thread copy or prefix is counted once. Divergent logs for a thread
    cannot safely be added because exec events have no stable turn identifier.
    """
    rates = {} if rates is None else rates
    sources = [read_transcript(path) for path in dict.fromkeys(paths)]
    threads = {}
    anonymous = []
    signals = set()
    for source in sorted(sources, key=lambda source: len(source.events), reverse=True):
        if source.thread_id is None:
            anonymous.append(source)
            continue
        previous = threads.setdefault(source.thread_id, source)
        if source is not previous and previous.events[:len(source.events)] != source.events:
            signals.add("conflicting_thread_transcripts")

    if anonymous and len(threads) + len(anonymous) > 1:
        signals.add("ambiguous_thread_identity")
    observed = ThreadUsage()
    per_thread = []
    native = {}
    capture_expected = any(source.capture_expected for source in sources)
    for source in sources:
        if source.capture_expected:
            signals.update(source.signals)
        if source.sessions is None:
            continue
        if threads.get(source.thread_id, source).events != source.events:
            signals.add("conflicting_session_capture")
        for thread_id, entry in source.sessions["sessions"].items():
            if native.setdefault(thread_id, entry) != entry:
                signals.add("conflicting_session_capture")

    # An unidentified file could be a copy of an already counted thread.
    selected = list(threads.values()) or anonymous[:1]
    exec_usage = {source.thread_id: thread_usage(source) for source in selected}
    for thread_id in dict.fromkeys([*exec_usage, *native]):
        entry = native.get(thread_id)
        usage = exec_usage.get(thread_id, ThreadUsage())
        if entry is not None:
            observed.children.update(entry.get("child_thread_ids", ()))
            if entry["parent_thread_id"] is not None:
                observed.children.add(thread_id)
            if "usage" in entry and entry["parent_thread_id"] is not None:
                if thread_id in exec_usage and not usage.signals and not matches_exec(entry, usage):
                    signals.add("child_usage_mismatch")
                children = usage.children
                usage = ThreadUsage(children=children)
                usage.add_turn(entry["usage"])
                usage.turns = entry["turns"]
            if "signal" in entry:
                usage.signals.add(entry["signal"])
        observed.add(usage)
        detail = {"thread_id": thread_id, "observed": usage.counts() if usage.turns else None,
                  "signals": sorted(usage.signals)}
        if entry is not None:
            detail.update({key: value for key, value in entry.items()
                           if key in {"parent_thread_id", "rollout_path", "edge_status", "models", "provider"}})
        per_thread.append(detail)
    for source in anonymous:
        signals.update(source.signals)
    signals.update(observed.signals)
    covered = {detail["thread_id"] for detail in per_thread
               if detail["observed"] is not None and "signal" not in native.get(detail["thread_id"], {})}
    missing = sorted(observed.children - covered)
    if missing:
        signals.add("missing_child_transcripts")
    if not selected:
        signals.add("no_transcripts")
    complete = not signals
    counts = observed.counts()
    model_keys = {(entry["provider"], model) for entry in native.values()
                  for model in entry.get("models", [])}
    pricing_known = not capture_expected or (len(model_keys) == 1 and covered <= native.keys())
    return {
        "scope": ("codex_exec_and_native_sessions" if capture_expected
                  else "supplied_codex_exec_transcripts"),
        "complete": complete,
        "signals": sorted(signals),
        "thread_ids": sorted(threads.keys() | native.keys()),
        "child_thread_ids": sorted(observed.children),
        "missing_child_thread_ids": missing,
        "threads": per_thread,
        "observed": counts,
        "totals": counts if complete else None,
        "rates_usd_per_million": rates,
        "estimated_cost_usd": estimate(counts, rates) if complete and pricing_known else None,
        "actual_cost_usd": None,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path, nargs="+", help="parent and any child exec JSONL transcripts")
    parser.add_argument("--rates", type=Path, help=(
        "JSON USD-per-million rates with keys uncached_input, cached_input, and output"
    ))
    args = parser.parse_args(argv)
    try:
        rates = read_rates(args.rates) if args.rates else None
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(summarize(args.events, rates), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
