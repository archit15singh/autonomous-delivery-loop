"""Atomic publication for frozen review evidence."""
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
