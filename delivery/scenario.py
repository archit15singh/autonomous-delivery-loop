"""Bounded, ordered HTTP and store checks from a reviewed product contract."""
from dataclasses import dataclass
import json
import re
import time
from urllib.parse import urlsplit


METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class HttpStep:
    method: str
    path: str
    status: int
    expect: dict | None
    body: dict | None


@dataclass(frozen=True)
class RedisStep:
    key: str
    expect: str | None
    wait_seconds: int


def read_steps(items):
    if not isinstance(items, list) or not 1 <= len(items) <= 20:
        raise ValueError("a scenario requires 1–20 ordered steps")
    steps = []
    for step in items:
        if not isinstance(step, dict):
            raise ValueError("each scenario step must be an object")
        kind = step.get("kind")
        fields = {key: value for key, value in step.items() if key != "kind"}
        if kind == "http":
            allowed = {"method", "path", "status", "expect", "body"}
            if not {"method", "path", "status"} <= fields.keys() <= allowed:
                raise ValueError("HTTP step needs method, path and status")
            method, path, status = (fields[key] for key in ("method", "path", "status"))
            body, expect = fields.get("body"), fields.get("expect")
            if (not isinstance(method, str) or method not in METHODS
                    or not isinstance(path, str) or not re.fullmatch(r"/[A-Za-z0-9/_?&=.%+-]{1,255}", path)
                    or path.startswith("//") or urlsplit(path).path == "/_revision"
                    or type(status) is not int or not 200 <= status <= 499
                    or (body is not None and (not isinstance(body, dict) or method == "GET"))
                    or (expect is not None and not isinstance(expect, dict))):
                raise ValueError("invalid local HTTP step")
            steps.append(HttpStep(method, path, status, expect, body))
        elif kind == "redis":
            if (fields.keys() != {"key", "expect", "wait_seconds"}
                    or not isinstance(fields["key"], str) or not re.fullmatch(r"adl:[A-Za-z0-9:_-]{1,100}", fields["key"])
                    or (fields["expect"] is not None and not isinstance(fields["expect"], str))
                    or type(fields["wait_seconds"]) is not int or not 0 <= fields["wait_seconds"] <= 5
                    or (fields["expect"] is None and fields["wait_seconds"])):
                raise ValueError("invalid bounded Redis readback")
            steps.append(RedisStep(**fields))
        else:
            raise ValueError("scenario step kind must be http or redis")
    if not any(isinstance(step, HttpStep) for step in steps):
        raise ValueError("a scenario requires an HTTP step")
    return tuple(steps)


def readback(step, reader):
    deadline = time.monotonic() + step.wait_seconds
    while True:
        value = reader(step.key)
        if value is not None and not isinstance(value, str):
            raise ValueError("Redis readback must return text or absence")
        remaining = deadline - time.monotonic()
        if value == step.expect or remaining <= 0:
            return value
        time.sleep(min(remaining, 0.1))
