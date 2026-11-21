"""Capture a browser receipt and the exact screenshot bytes it verifies."""
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path


@dataclass(frozen=True)
class BrowserProof:
    passed: bool
    files: tuple[tuple[Path, bytes], ...]

    @property
    def receipt_reference(self):
        path, content = self.files[0]
        return {"file": path.name, "sha256": sha256(content).hexdigest()}

    def archive(self, directory):
        directory.mkdir()
        for path, content in self.files:
            (directory / path.name).write_bytes(content)


def capture(path, *, head, base):
    content = path.read_bytes()
    data = json.loads(content)
    if data["after"] != head or (base is not None and data["before"] != base):
        raise ValueError("browser receipt belongs to another baseline or candidate")
    outcomes = data["outcomes"]
    if set(outcomes) != {"before", "after"} or any(
        set(side) != {"primary", "control"} for side in outcomes.values()
    ):
        raise ValueError("browser receipt needs before and after primary and control checks")
    files = [(path, content)]
    checks = []
    for phase, side in outcomes.items():
        for scenario, check in side.items():
            name = check["screenshot"]
            if name != f"{phase}-{scenario}.png" or name == path.name:
                raise ValueError("unexpected browser screenshot name")
            screenshot = path.parent / name
            pixels = screenshot.read_bytes()
            if sha256(pixels).hexdigest() != check["sha256"]:
                raise ValueError("browser screenshot digest mismatch")
            files.append((screenshot, pixels))
            checks.append(check["passed"] is True and not check["errors"]
                          and check["observed"] == check["expected"])
    return BrowserProof(data["passed"] is True and all(checks), tuple(files))
