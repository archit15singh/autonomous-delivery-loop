#!/usr/bin/env python3
"""Compare Codex with and without a delivery skill on pinned issue snapshots."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent
# Keep the documented direct script entry point alongside python -m evals.run.
if not __package__:
    sys.path.insert(0, str(ROOT.parent))

from delivery.codex_usage import summarize
from delivery.local_codex import run_codex
from evals.agent_cli import AGENTS, run_external

SKILL = ROOT.parent / ".agents/skills/deliver-outcome/SKILL.md"


def command(args, cwd, *, input_text=None, env=None, check=True):
    result = subprocess.run(args, cwd=cwd, input=input_text, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
    if check and result.returncode:
        raise RuntimeError(f"{args[0]} failed in {cwd}: {result.stdout[-2500:]}")
    return result


def git(cwd, *args, **options):
    return command(["git", *args], cwd, **options).stdout


def snapshot(case, cache):
    base = cache / case["instance_id"]
    if (base / ".git").exists():
        return base
    archive = cache / f'{case["instance_id"]}.tar.gz'
    url = f'https://codeload.github.com/{case["repo"]}/tar.gz/{case["base_commit"]}'
    command(["curl", "--retry", "2", "-fsSL", url, "-o", str(archive)], cache)
    with tarfile.open(archive) as source:
        source.extractall(cache, filter="data")
    extracted = cache / f'{case["repo"].split("/")[-1]}-{case["base_commit"]}'
    extracted.rename(base)
    git(base, "init", "-q")
    git(base, "add", "-A")
    git(base, "-c", "user.name=Eval", "-c", "user.email=eval@localhost",
        "-c", "core.hooksPath=/dev/null", "commit", "-qm", "Benchmark snapshot")
    return base


def checkout(base, dest):
    git(base.parent, "clone", "-q", str(base), str(dest))
    git(dest, "remote", "remove", "origin")
    if base.name.startswith("pytest-dev__pytest-"):
        # The source archive omits this ignored build-time setuptools_scm output.
        (dest / "src/_pytest/_version.py").write_text(
            "__version__ = version = '7.2.0'\n"
            "__version_tuple__ = version_tuple = (7, 2, 0)\n"
        )
    return dest


def test_env(case, tree):
    return {**os.environ, "PYTHONPATH": str(tree / case["import_path"]),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1"}


def test_args(case):
    args = ["-m", "pytest", "-q"]
    if case["repo"] == "psf/requests":
        args += ["-p", "pytest_httpbin"]
    return args


def regression_nodes(case):
    nodes = [case["regression"]]
    if case["selector"]:
        nodes += ["-k", case["selector"]]
    return nodes


def tests(case, python, tree, nodes, report):
    xml = report.with_suffix(".xml")
    result = command([python, *test_args(case), *nodes, "--junitxml", str(xml)],
                     tree, env=test_env(case, tree), check=False)
    report.write_text(result.stdout)
    if not xml.exists():
        return {"exit": result.returncode, "passed": 0, "failed": 0, "errors": 0}
    suites = ElementTree.parse(xml).findall(".//testsuite")
    keys = ["tests", "failures", "errors", "skipped"]
    count = {key: sum(int(s.get(key, 0)) for s in suites) for key in keys}
    return {"exit": result.returncode,
            "passed": count["tests"] - count["failures"] - count["errors"] - count["skipped"],
            "failed": count["failures"], "errors": count["errors"]}


def grade(case, python, base, run, patch):
    tree = checkout(base, run / "grade")
    if patch:
        git(tree, "apply", "-", input_text=patch)
    regression = tests(case, python, tree, regression_nodes(case), run / "regression.txt")
    git(tree, "apply", "-", input_text=case["test_patch"])
    acceptance = tests(case, python, tree, case["acceptance"], run / "acceptance.txt")
    return {"regression": regression, "acceptance": acceptance}


def control(case, python, base, state):
    for name, patch in [("broken", ""), ("upstream", case["patch"])]:
        folder = state / name
        if (folder / "control.json").exists():
            continue
        folder.mkdir(parents=True, exist_ok=True)
        if (folder / "grade").exists():
            shutil.rmtree(folder / "grade")
        result = grade(case, python, base, folder, patch)
        oracle = result["acceptance"]
        valid = (oracle["failed"] > 0 and oracle["errors"] == 0 if name == "broken"
                 else oracle["passed"] == len(case["acceptance"]) and oracle["exit"] == 0)
        if not valid or result["regression"]["exit"] != 0:
            raise RuntimeError(f"{case['instance_id']} {name} control invalid: {result}; see {folder}")
        (folder / "control.json").write_text(json.dumps(result, indent=2) + "\n")


def run_agent(case, python, model, variant, tree, run, timeout, *, agent="codex", launcher=None):
    with_skill = variant != "plain"
    if with_skill:
        skill = tree / ".agents/skills/deliver-outcome/SKILL.md"
        skill.parent.mkdir(parents=True)
        shutil.copyfile(SKILL, skill)
    launch = f"Apply $deliver-outcome at {skill.relative_to(tree)}.\n\n" if with_skill else ""
    test = [python, *test_args(case)]
    focused = regression_nodes(case)
    local = shlex.join([*test, *focused])
    if variant == "equipped-check":
        helper = tree / ".delivery-check"
        helper.write_text(
            '#!/bin/sh\nif [ "$#" -eq 0 ]; then\n'
            f'    set -- {shlex.join(focused)}\nfi\n'
            f'exec {shlex.join(test)} "$@"\n'
        )
        helper.chmod(0o700)
        local = "./.delivery-check"
    prompt = (f"{launch}Resolve this issue in the local checkout. Leave your patch in the working tree."
              f" Local test command: {local}."
              " The interpreter already has dependencies. Use only the repository and local tools."
              " Keep changes to implementation and tests. The harness handles grading and delivery."
              " Report your observed results.\n\n"
              f"{case['problem_statement']}")
    if variant in {"equipped-feedback", "equipped-check", "equipped-receipt"}:
        prompt += ("\n\nHarness preflight: the supervising Codex session already refreshed and "
                   "checked the skill catalog and reviewed project context. The runner "
                   "verified the clean pinned snapshot and its existing regression suite. "
                   "Use this handoff as preflight evidence. Read any repository instructions, "
                   "then run the narrowest applicable reproduction before changing code.")
    if variant == "equipped-check":
        prompt += " The local test command also accepts explicit pytest paths or selectors."
    schema = None
    if variant == "equipped-receipt":
        schema = run / "receipt-schema.json"
        schema.write_text(json.dumps({
            "type": "object", "additionalProperties": False,
            "properties": {field: {"type": "string"}
                           for field in ("change", "observed_checks", "pending_evidence")},
            "required": ["change", "observed_checks", "pending_evidence"],
        }))
    started = time.monotonic()
    events_path = run / "events.jsonl"
    try:
        if agent == "codex":
            exit_code = run_codex(cwd=tree, prompt=prompt, model=model, timeout=timeout,
                                  events=events_path, role="writer", schema=schema,
                                  env=test_env(case, tree), launcher=launcher)
        else:
            exit_code = run_external(agent=agent, model=model, launcher=launcher, prompt=prompt,
                                     tree=tree, events=events_path, timeout=timeout, env=test_env(case, tree))
    finally:
        stderr = events_path.with_suffix(".stderr")
        if stderr.exists():
            stderr.replace(run / "agent.stderr")
        if with_skill:
            skill.unlink(missing_ok=True)
        if variant == "equipped-check":
            helper.unlink(missing_ok=True)
    return {"exit": exit_code, "seconds": round(time.monotonic() - started, 2)}


def events(path):
    commands, reports = [], []
    for line in path.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        if event.get("type") == "item.completed" and item.get("type") == "command_execution":
            invocation = item.get("command")
            if not isinstance(invocation, str):
                continue
            exit_code = item.get("exit_code")
            outcome = None
            if "-m pytest" in invocation or "./.delivery-check" in invocation:
                output = "\n".join(str(item.get("aggregated_output", "")).splitlines()[-10:])
                if exit_code == 1 and re.search(r"\b[1-9]\d* failed\b", output):
                    outcome = "failed"
                elif exit_code == 0 and re.search(r"\b[1-9]\d* passed\b", output):
                    outcome = "passed"
            commands.append({"command": invocation, "exit": exit_code, "test_outcome": outcome})
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            if isinstance(item.get("text"), str):
                reports.append(item["text"])
    usage = summarize([path])["totals"] or {}
    return commands, reports[-1] if reports else "", usage


def permitted_diff(records, prefixes):
    parts = records.rstrip("\0").split("\0") if records else []
    if not parts or len(parts) % 2:
        return False
    for header, name in zip(parts[::2], parts[1::2]):
        old_mode, new_mode = header[1:].split()[:2]
        if (not any(name.startswith(prefix) for prefix in prefixes)
                or {old_mode, new_mode} - {"000000", "100644", "100755"}):
            return False
    return True


def trial(case, python, model, variant, base, run, timeout, *, agent="codex", launcher=None):
    if run.exists():
        if (run / "result.json").exists():
            prior = json.loads((run / "result.json").read_text())
            if prior.get("coding_agent", "codex") != agent or prior["model"] != model:
                raise RuntimeError("use a fresh round name for a different agent or model")
            return prior
        raise RuntimeError(f"Choose a new round rather than overwriting an incomplete run: {run}")
    run.mkdir(parents=True)
    tree = checkout(base, run / "solve")
    execution = run_agent(case, python, model, variant, tree, run, timeout, agent=agent, launcher=launcher)
    git(tree, "add", "-A")
    patch = git(tree, "diff", "--binary", "HEAD", "--")
    (run / "candidate.patch").write_text(patch)
    paths = git(tree, "diff", "--name-only", "-z", "HEAD", "--").split("\0")[:-1]
    modes = git(tree, "diff", "--raw", "--no-renames", "-z", "HEAD", "--")
    scope_ok = permitted_diff(modes, (case["package"], case["tests"]))
    source_patch = git(tree, "diff", "--binary", "HEAD", "--", case["package"])
    commands, report, usage = events(run / "events.jsonl")
    result = {"case": case["instance_id"], "variant": variant, "model": model,
              "agent": execution, "coding_agent": agent, "usage": usage, "human_interventions": 0, "commands": commands, "report": report,
              "changed_paths": paths, "scope_pass": scope_ok,
              "test_changed": any(p.startswith(case["tests"]) for p in paths),
              "diff_stat": git(tree, "diff", "--shortstat", "HEAD", "--").strip()}
    if scope_ok and source_patch:
        result.update(grade(case, python, base, run, source_patch))
    result["solved"] = (scope_ok and result.get("acceptance", {}).get("exit") == 0
                        and result.get("acceptance", {}).get("passed") == len(case["acceptance"])
                        and result.get("regression", {}).get("exit") == 0)
    (run / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True, help="Scratch directory outside the harness project")
    parser.add_argument("--python", required=True, help="Absolute path to the Python 3.11 test venv")
    parser.add_argument("--agent", choices=AGENTS, default="codex")
    parser.add_argument("--model")
    parser.add_argument("--isolated-worker", type=Path, help="operator-run launcher for an external coding CLI")
    parser.add_argument("--round", default="pilot")
    parser.add_argument("--variant", nargs="+",
                        choices=["plain", "equipped", "equipped-feedback", "equipped-check",
                                 "equipped-receipt"],
                        default=["plain", "equipped-feedback"])
    parser.add_argument("--case", action="append", help="Exact instance ID, repeat to select several")
    parser.add_argument("--timeout", type=int, default=210)
    parser.add_argument("--controls-only", action="store_true")
    args = parser.parse_args()
    if args.isolated_worker and not args.isolated_worker.is_absolute():
        parser.error("--isolated-worker requires an absolute path")
    if args.agent == "codex":
        args.model = args.model or "gpt-6.2-sol"
    elif not args.controls_only and (not args.model or not args.isolated_worker):
        parser.error("external trials require --model and --isolated-worker")
    if args.isolated_worker and "equipped-receipt" in args.variant:
        parser.error("structured receipts require native local Codex execution")
    state = args.state.resolve()
    cache = state / "snapshots"
    cache.mkdir(parents=True, exist_ok=True)
    cases = [case for case in json.loads((ROOT / "cases.json").read_text())
             if not args.case or case["instance_id"] in args.case]
    if not cases or (args.case and len(args.case) != len(cases)):
        parser.error("unknown or repeated case")
    for case in cases:
        name = case["instance_id"]
        base = snapshot(case, cache)
        control(case, args.python, base, state / "controls" / name)
        print(f"{name}: controls passed", flush=True)
        if args.controls_only:
            continue
        for variant in args.variant:
            result = trial(case, args.python, args.model, variant, base,
                           state / args.round / name / variant, args.timeout, agent=args.agent, launcher=args.isolated_worker)
            print(json.dumps({key: value for key, value in result.items()
                              if key not in {"report", "commands"}}), flush=True)


if __name__ == "__main__":
    main()
