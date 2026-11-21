import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from delivery.local_codex import TIMEOUT_EXIT, run_codex
from evals import run as eval_runner


class LocalCodexTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}))
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.events = self.root / "events.jsonl"
        self.program = self.root / "codex"
        self.program.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, subprocess, sys, time\n"
            "prompt = sys.stdin.read()\n"
            "if prompt == 'timeout':\n"
            "    subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(1); "
            "open(\"escaped\", \"w\").close()'])\n"
            "    open('spawned', 'w').close()\n"
            "    time.sleep(30)\n"
            "item = 'command_execution' if prompt == 'tool' else 'agent_message'\n"
            "print(json.dumps(dict(type='item.completed', item=dict(type=item), "
            "args=sys.argv[1:], cwd=os.getcwd(), prompt=prompt)))\n"
            "print('private diagnostic', file=sys.stderr)\n"
        )
        self.program.chmod(0o700)
        self.env = {**os.environ, "PATH": f"{self.root}{os.pathsep}{os.environ['PATH']}"}

    def invoke(self, **overrides):
        options = dict(cwd=self.root, prompt="normal", model="test-model", timeout=5,
                       events=self.events, role="writer", env=self.env)
        return run_codex(**{**options, **overrides})

    def event(self):
        return json.loads(self.events.read_text())

    def test_writer_uses_stdin_and_private_artifacts_with_bounded_opt_in(self):
        self.events.touch(mode=0o644)
        self.assertEqual(self.invoke(prompt="--not-a-cli-option", subagents=2), 0)
        event = self.event()
        self.assertTrue(event["prompt"].endswith("--not-a-cli-option"))
        self.assertEqual(Path(event["cwd"]).resolve(), self.root.resolve())
        args = event["args"]
        self.assertIn("workspace-write", args)
        self.assertIn("sandbox_workspace_write.writable_roots=[]", args)
        self.assertIn("sandbox_workspace_write.network_access=false", args)
        self.assertIn("mcp_servers={}", args)
        self.assertIn("agents.max_depth=1", args)
        self.assertIn("agents.max_threads=2", args)
        self.assertEqual(args[args.index("multi_agent") - 1], "--enable")
        for path in (self.events, self.events.with_suffix(".stderr")):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_reviewer_read_only_and_judge_rejects_tool_events(self):
        self.assertEqual(self.invoke(role="reviewer"), 0)
        args = self.event()["args"]
        self.assertIn("read-only", args)
        self.assertEqual(args[args.index("multi_agent") - 1], "--disable")
        with self.assertRaisesRegex(ValueError, "attempted to use a tool"):
            self.invoke(role="judge", prompt="tool", schema=self.root / "schema.json",
                        result=self.root / "result.json")
        args = self.event()["args"]
        for feature in ("shell_tool", "unified_exec", "computer_use", "apps", "plugins"):
            self.assertEqual(args[args.index(feature) - 1], "--disable")
        self.assertIn("--output-schema", args)
        self.assertIn("--output-last-message", args)

    def test_hosted_actions_and_invalid_delegation_fail_before_launch(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted"}):
            with self.assertRaisesRegex(ValueError, "GitHub-hosted"):
                self.invoke()
        for overrides in ({"subagents": True}, {"subagents": 5},
                          {"role": "judge", "subagents": 1}, {"role": "other"}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.invoke(**overrides)
        self.assertFalse(self.events.exists())

    def test_timeout_kills_descendants(self):
        self.assertEqual(self.invoke(prompt="timeout", timeout=0.6), TIMEOUT_EXIT)
        self.assertTrue((self.root / "spawned").is_file())
        # A surviving child writes after the parent times out.
        time.sleep(1)
        self.assertFalse((self.root / "escaped").exists())

    def test_eval_passes_test_environment_and_preserves_stderr_path(self):
        tree = self.root / "solve"
        tree.mkdir()
        case = {"repo": "sample/project", "regression": "test_sample.py", "selector": "",
                "import_path": "src", "problem_statement": "Example issue"}

        def fake_run(**kwargs):
            self.assertEqual(kwargs["role"], "writer")
            self.assertEqual(kwargs["env"]["PYTHONPATH"], str(tree / "src"))
            self.assertEqual(kwargs["env"]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"], "1")
            self.assertTrue(kwargs["schema"].is_file())
            kwargs["events"].with_suffix(".stderr").write_text("diagnostic")
            return TIMEOUT_EXIT

        with patch.object(eval_runner, "run_codex", side_effect=fake_run):
            result = eval_runner.run_agent(case, "python", "model", "equipped-receipt",
                                          tree, self.root, 5)
        self.assertEqual(result["exit"], TIMEOUT_EXIT)
        self.assertEqual((self.root / "agent.stderr").read_text(), "diagnostic")
        self.assertFalse((tree / ".agents/skills/deliver-outcome/SKILL.md").exists())
