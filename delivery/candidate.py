"""Run Codex in a disposable checkout and export a scope-checked patch."""
import json
from hashlib import sha256
from pathlib import Path
import subprocess

from .patch_checkout import write_patch
from .local_codex import check_local_runner, check_subagents
from .revisions import git
from .verify import advice

def repair_context(contract, revision, receipt):
    if receipt is None:
        return "", 0
    repairs = receipt.get("repairs_used")
    if (receipt.get("revision") != revision or receipt.get("contract_sha256") != contract.digest
            or type(repairs) is not int or repairs < 0
            or advice(receipt.get("verdict"), receipt.get("reason"), repairs,
                      contract.max_repairs) != "repair"):
        raise ValueError("evidence does not authorize a repair for this revision and contract")
    failed = [
        {"path": p["path"], "expected": p["expect"], "observed": p["observed"]}
        for p in receipt["probes"] if not p["passed"]
    ]
    return "\nTrusted verification result:\n" + json.dumps(failed, indent=2), repairs + 1


def propose(contract, output, events, model, timeout, receipt=None, *, recipe_output=None, subagents=0):
    check_local_runner()
    check_subagents(subagents)
    root = Path(git("rev-parse", "--show-toplevel").decode().strip())
    base = git("rev-parse", "HEAD", cwd=root).decode().strip()
    context, attempt = repair_context(contract, base, receipt)
    output.parent.mkdir(parents=True, exist_ok=True)
    events.parent.mkdir(parents=True, exist_ok=True)
    examples = f"Reviewed acceptance examples: {json.dumps(contract.acceptance)}\n" if contract.acceptance else ""
    prompt = (
        "Use $deliver-outcome. Implement the approved outcome in this clean Git checkout.\n"
        "The harness already confirmed the checkout and state. Use python3 -m unittest discover -s tests.\n"
        f"Approved outcome: {contract.outcome}\n"
        f"Files you may modify: {', '.join(contract.allowed_changes)}\n"
        f"Required HTTP behavior: {json.dumps([p.__dict__ for p in contract.probes])}\n"
        f"{examples}"
        f"{contract.technical_brief or ''}\n"
        "Leave changes in the working tree and report your local checks. "
        "The release operator owns GitHub and the independent verdict."
        + context
    )
    if recipe_output:
        skill = git("show", f"{base}:.agents/skills/deliver-outcome/SKILL.md", cwd=root)
        version = subprocess.check_output(["codex", "--version"], text=True, timeout=10).strip()
        recipe_output.parent.mkdir(parents=True, exist_ok=True)
        recipe_output.write_text(json.dumps({
            "revision": base, "contract_sha256": contract.digest, "skill_sha256": sha256(skill).hexdigest(),
            "codex": version, "model": model, "seconds_budget": timeout, "repair_attempt": attempt,
            "sandbox": "workspace-write", "network": False, "approval": "never",
            "subagents": subagents,
            "output": "scope-checked patch and JSONL events",
        }, indent=2) + "\n")
    output.write_bytes(write_patch(root, base, prompt, contract.allowed_changes, events=events,
                                   model=model, timeout=timeout, subagents=subagents))
    return base, attempt
