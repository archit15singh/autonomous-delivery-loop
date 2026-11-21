"""Write CLI JSON results to stdout or a selected file."""
import json
from pathlib import Path


def write(path, value):
    if path == Path("-"):
        print(json.dumps(value, indent=2))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")
