from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from delivery import lima_repair


class LimaRepairTests(unittest.TestCase):
    def test_local_writer_patch_is_bound_to_revision_and_scope(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            product = root / "service.py"
            product.write_text("before\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@localhost",
                            "commit", "-qm", "base"], cwd=root, check=True)
            revision = lima_repair.git("rev-parse", "HEAD", cwd=root).decode().strip()

            def write(*, cwd, prompt, role, **kwargs):
                self.assertEqual(role, "writer")
                self.assertEqual(lima_repair.git("rev-parse", "HEAD", cwd=cwd).decode().strip(), revision)
                (cwd / prompt).write_text("after\n")
                return 0

            with patch.object(lima_repair, "ROOT", root), patch.object(lima_repair, "run_codex", write):
                diff = lima_repair.local_patch(root, revision, "service.py", None, 5, ["service.py"])
                self.assertIn(b"+after", diff)
                with self.assertRaisesRegex(ValueError, "protected paths"):
                    lima_repair.local_patch(root, revision, "extra.py", None, 5, ["service.py"])
                self.assertEqual(product.read_text(), "before\n")

    def test_verified_failure_gets_one_repair_and_a_fresh_browser_run(self):
        failed = {"verdict": "failed", "reason": "redis_readback_mismatch", "redis_counter": "",
                  "cleanup": {"status": "confirmed"}, "observation": {"probes": []}}
        passed = {"verdict": "verified", "reason": "all_required_evidence_passed"}
        with TemporaryDirectory() as folder, \
             patch.object(lima_repair, "running_definition", return_value={"revision": "a" * 40}), \
             patch.object(lima_repair, "check_candidate"), \
             patch.object(lima_repair, "run", side_effect=[failed, passed]) as run, \
             patch.object(lima_repair, "local_patch", return_value=b"candidate") as writer, \
             patch.object(lima_repair, "repaired_commit", return_value="b" * 40):
            state = Path(folder)
            result = lima_repair.repair(state, "a" * 40, browser=True)
            self.assertEqual(result["verdict"], "verified")
            self.assertEqual(result["repair_attempts"], 1)
            self.assertEqual(run.call_args_list[0].args, (state / "before", "a" * 40))
            self.assertEqual(run.call_args_list[1].args, (state / "after", "b" * 40))
            self.assertTrue(all(call.kwargs == {"browser": True} for call in run.call_args_list))
            self.assertIn('"redis_counter": {"expected": "2", "observed": ""}', writer.call_args.args[2])
            with self.assertRaisesRegex(ValueError, "already owns"):
                lima_repair.repair(state, "a" * 40)
            writer.assert_called_once()

    def test_uncertain_cleanup_prevents_dispatch(self):
        failed = {"verdict": "failed", "reason": "probe_failed", "cleanup": {"status": "unconfirmed"}}
        with TemporaryDirectory() as folder, \
             patch.object(lima_repair, "running_definition", return_value={"revision": "a" * 40}), \
             patch.object(lima_repair, "check_candidate"), \
             patch.object(lima_repair, "run", return_value=failed), \
             patch.object(lima_repair, "local_patch") as writer:
            result = lima_repair.repair(Path(folder), "a" * 40)
            self.assertEqual(result["repair_attempts"], 0)
            writer.assert_not_called()
