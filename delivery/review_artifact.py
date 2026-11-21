"""Atomic publication for frozen review evidence."""
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def publish_new(path, text):
    """Publish a complete artifact once, including across concurrent invocations."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = NamedTemporaryFile(dir=path.parent, mode="w", delete=False)
    try:
        with temp:
            temp.write(text)
            temp.flush()
            os.fsync(temp.fileno())
        os.link(temp.name, path)
    finally:
        Path(temp.name).unlink()


def cached_json(path, create):
    """Reuse a complete JSON result. Concurrent producers accept the first publication."""
    if path is None:
        return create()
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        pass
    result = create()
    try:
        publish_new(path, json.dumps(result, indent=2) + "\n")
    except FileExistsError:
        return json.loads(path.read_text())
    return result


def retain(path, text):
    """Save replayed evidence or confirm the saved artifact still agrees."""
    try:
        publish_new(path, text)
    except FileExistsError:
        if path.read_text() != text:
            raise ValueError(f"saved artifact differs from replayed evidence: {path.name}")
