"""Persist run receipts and serialize access to their directory."""
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from tempfile import NamedTemporaryFile


def file_digest(path):
    return sha256(path.read_bytes()).hexdigest()


def record(path, value):
    with NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as file:
        tmp = Path(file.name)
        try:
            json.dump(value, file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


@contextmanager
def lock(folder):
    folder.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(folder / "workflow.lock", timeout=3)
    try:
        connection.execute("BEGIN EXCLUSIVE")
        yield
    finally:
        connection.close()
