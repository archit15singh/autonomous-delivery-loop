"""Plan and apply one reviewed disposable resource with OpenTofu."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
from uuid import uuid4

from .factory_definition import running_definition
from .factory_workflow import file_digest, lock, record

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {"local": "terraform_data.pilot", "aws": "aws_ssm_parameter.pilot"}
AWS_ENV = {"AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
           "AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_ROLE_ARN", "AWS_ROLE_SESSION_NAME"}


def call(folder, *command):
    env = {key: os.environ[key] for key in {"PATH", "HOME"} | AWS_ENV if key in os.environ}
    env["TF_CLI_CONFIG_FILE"] = os.devnull
    result = subprocess.run(command, env=env, cwd=folder, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise ValueError(f"{command[0]} {command[1]} failed: {result.stderr[-3000:]}")
    return result.stdout


def verify_identity(folder, target):
    if target["backend"] == "aws":
        identity = json.loads(call(folder, "aws", "sts", "get-caller-identity", "--region",
                                   target["region"], "--output", "json", "--no-cli-pager"))
        if identity["Account"] != target["account"]:
            raise ValueError("AWS caller is outside the configured sandbox account")


def verify_inputs(folder, pending, policy):
    stack = folder / "main.tf"
    template = ROOT / f"verification/tofu/{pending['target']['backend']}.tf"
    lockfile = folder / ".terraform.lock.hcl"
    state = folder / "terraform.tfstate"
    current = {"policy": policy["sha256"], "plan": file_digest(folder / "reviewed.tfplan"),
               "config": file_digest(stack), "provider_lock": file_digest(lockfile) if lockfile.exists() else None,
               "state": file_digest(state) if state.exists() else None}
    if current != pending["inputs"] or stack.read_bytes() != template.read_bytes():
        raise ValueError("plan, configuration, policy, provider lock, or state changed")
    if {p.name for p in folder.glob("*.tf")} != {"main.tf"} or list(folder.glob("*.tf.json")):
        raise ValueError("unexpected OpenTofu configuration")
    verify_identity(folder, pending["target"])


def plan(folder, target, action, policy):
    target_path = folder / "target.json"
    config = folder / "main.tf"
    if target_path.exists():
        existing = json.loads(target_path.read_text())
        if {k: existing[k] for k in target} != target:
            raise ValueError("reuse the original target or choose a new state directory")
        target = existing
    else:
        lock_files = {"workflow.lock", "workflow.lock-journal"}
        if action == "destroy" or any(p.name not in lock_files for p in folder.iterdir()):
            raise ValueError("start in an empty state directory before provisioning")
        target = {**target, "run": f"adl-{uuid4().hex[:16]}"}
        record(target_path, target)
        config.write_bytes((ROOT / f"verification/tofu/{target['backend']}.tf").read_bytes())
    receipt_path = folder / "apply.json"
    if receipt_path.exists() and json.loads(receipt_path.read_text())["status"] == "applying":
        raise ValueError("previous apply is unresolved; inspect provider and state before proceeding")
    if (config.read_bytes() != (ROOT / f"verification/tofu/{target['backend']}.tf").read_bytes()
            or {p.name for p in folder.glob("*.tf")} != {"main.tf"} or list(folder.glob("*.tf.json"))
            or list(folder.glob("*.tfvars*"))):
        raise ValueError("sandbox configuration differs from trusted policy")
    verify_identity(folder, target)
    staged = folder / "reviewed.tfplan"
    (folder / "plan.json").unlink(missing_ok=True)
    cli = ("tofu",)
    call(folder, *cli, "init", "-input=false", "-no-color")
    args = ["-destroy"] if action == "destroy" else []
    args += ["-var", f"run={target['run']}"]
    if target["backend"] == "aws":
        args += ["-var", f"region={target['region']}", "-var", f"account={target['account']}"]
    call(folder, *cli, "plan", "-input=false", "-no-color", "-lock-timeout=10s", "-out=reviewed.tfplan", *args)
    raw = json.loads(call(folder, *cli, "show", "-json", "reviewed.tfplan"))
    changes = [(x["address"], x["change"]["actions"]) for x in raw.get("resource_changes", [])]
    expected = ["delete"] if action == "destroy" else ["create"]
    if changes != [(TARGETS[target["backend"]], expected)]:
        raise ValueError("the plan must create or delete exactly the one sandbox resource")
    state, lockfile = folder / "terraform.tfstate", folder / ".terraform.lock.hcl"
    request = {"target": target, "action": action, "changes": changes,
               "inputs": {"policy": policy["sha256"], "plan": file_digest(staged), "config": file_digest(config),
                          "provider_lock": file_digest(lockfile) if lockfile.exists() else None,
                          "state": file_digest(state) if state.exists() else None}}
    record(folder / "plan.json", request)
    return request


def manage(folder, operation, *, backend=None, account=None, region=None, approval=None):
    folder = folder.resolve()
    policy = running_definition(ROOT)
    with lock(folder):
        if operation in {"create", "destroy"}:
            if backend not in TARGETS or (backend == "aws" and (
                not re.fullmatch(r"\d{12}", account or "") or not re.fullmatch(r"[a-z]{2}-[a-z]+-\d+", region or "")
            )) or (backend == "local" and (account or region)):
                raise ValueError("choose local, or supply an explicit AWS sandbox account and region")
            return plan(folder, {"backend": backend, "account": account, "region": region}, operation, policy)
        pending = json.loads((folder / "plan.json").read_text())
        verify_inputs(folder, pending, policy)
        digest = file_digest(folder / "plan.json")
        if operation == "approve":
            if approval is None:
                raise ValueError("write approval to an operator-controlled file")
            item = {"request_sha256": digest, "approved_at": datetime.now(timezone.utc).isoformat(),
                    "state_directory": str(folder)}
            record(approval, item)
            return item
        if approval is None:
            raise ValueError("apply requires approval of the saved plan")
        item = json.loads(approval.read_text())
        age = datetime.now(timezone.utc) - datetime.fromisoformat(item["approved_at"])
        if (item["request_sha256"] != digest or item["state_directory"] != str(folder)
                or not timedelta(0) <= age <= timedelta(minutes=30)):
            raise ValueError("approval does not match the exact current plan")
        path = folder / "apply.json"
        if path.exists():
            prior = json.loads(path.read_text())
            if prior["status"] == "applying" or prior["request_sha256"] == digest:
                raise ValueError("plan already used or prior apply unresolved")
        status = {"status": "applying", "request_sha256": digest,
                  "target": pending["target"], "action": pending["action"]}
        record(path, status)
        call(folder, "tofu", "apply", "-input=false", "-no-color", "-lock-timeout=10s", "reviewed.tfplan")
        observed = call(folder, "tofu", "state", "list")
        wanted = TARGETS[pending["target"]["backend"]]
        if observed.splitlines() != ([wanted] if pending["action"] == "create" else []):
            raise ValueError("resource state did not match the applied plan")
        if pending["target"]["backend"] == "local" and pending["action"] == "create":
            values = json.loads(call(folder, "tofu", "show", "-json"))["values"]
            resources = values["root_module"]["resources"]
            if resources[0]["values"]["output"] != pending["target"]["run"]:
                raise ValueError("local resource did not return the planned value")
        if pending["target"]["backend"] == "aws":
            target = pending["target"]
            command = ("aws", "ssm", "get-parameter", "--region", target["region"], "--name",
                       f"/adl-sandbox/{target['run']}", "--output", "json", "--no-cli-pager")
            if pending["action"] == "create":
                if json.loads(call(folder, *command))["Parameter"]["Value"] != target["run"]:
                    raise ValueError("AWS did not return the planned parameter")
            else:
                try:
                    call(folder, *command)
                except ValueError as exc:
                    if "ParameterNotFound" not in str(exc):
                        raise
                else:
                    raise ValueError("AWS still returns the destroyed parameter")
        status["status"] = "verified"
        record(path, status)
        return status
