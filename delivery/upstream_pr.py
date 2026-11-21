"""Prepare a PR body from a successful exact-head local replay."""
import json
import os
import shutil
from urllib.parse import urlsplit

from .revisions import git
from .factory_evidence import browser_evidence
from .upstream import replay


def markdown_text(text):
    return " ".join(text.split()).replace("|", r"\|")


def prepare(repo, contract, template, evidence_url, output, *, browser=None):
    parsed = urlsplit(evidence_url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
        or any(c.isspace() or c in "<>" for c in evidence_url)):
        raise ValueError("provide a public HTTPS location for the replay evidence")
    body = template.read_text().strip()
    if not body:
        raise ValueError("complete the upstream PR template before running the gate")
    if os.getenv("GITHUB_ACTIONS") == "true":
        raise ValueError("run upstream-prepare in the local development environment")

    # Refuse to prepare a body for a different checkout or a changed head.
    plan = json.loads(contract.read_bytes())
    candidate = plan["candidate"]
    if plan.get("readiness", {}).get("browser_required") is True and browser is None:
        raise ValueError("this UI change requires an exact-head browser receipt")
    files = []
    if browser is not None:
        passed, files = browser_evidence(browser, candidate, plan["base"])
        if not passed:
            raise ValueError("the browser primary and control checks must pass")
    head = git("rev-parse", "HEAD", cwd=repo).decode().strip()
    if head != candidate:
        raise ValueError("the local checkout must be at the proposed PR head")
    receipt = replay(repo, contract, output, require_readiness=True)
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if receipt["verdict"] != "verified":
        return receipt
    if receipt["candidate"] != head or git("rev-parse", "HEAD", cwd=repo).decode().strip() != head:
        raise ValueError("the proposed PR head changed during verification")

    if files:
        browser_output = output / "browser-evidence"
        browser_output.mkdir()
        for path in files:
            shutil.copyfile(path, browser_output / path.name)
    readiness = receipt["readiness"]
    lines = [
        body, "", "### Local verification", "",
        f"Base `{receipt['base']}` · Candidate `{head}` · {readiness['platform']}",
        "",
        "| Check | Base | Candidate |",
        "| --- | --- | --- |",
        f"| {markdown_text(readiness['live_entrypoint'])} | {markdown_text(receipt['before']['signal'])} | "
        f"{markdown_text(receipt['after']['signal'])} |",
        f"| {markdown_text(readiness['setup']['candidate']['name'])} | Passed | Passed |",
    ]
    for control in readiness["controls"]["candidate"]:
        lines.append(f"| {markdown_text(control['name'])} | Passed | Passed |")
    lines.append(f"| {markdown_text(readiness['suite']['name'])} | — | Passed |")
    if files:
        lines.append("| Browser interaction and adjacent control | Observed | Verified |")
    if readiness["exclusions"]:
        lines.extend(["", "Coverage limits"])
        for kind, reason in readiness["exclusions"].items():
            lines.append(f"- {kind.capitalize()} scenarios omitted — {markdown_text(reason)}")
    lines.extend(["", f"[Replay receipt, commands, and logs](<{evidence_url}>)", ""])
    (output / "pr.md").write_text("\n".join(lines))
    return receipt
