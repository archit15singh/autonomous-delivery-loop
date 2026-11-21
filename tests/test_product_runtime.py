import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

from delivery.product_runtime import resolve
from delivery.verify import Contract


class ProductRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "catalog"
        shutil.copytree(Path(__file__).resolve().parents[1] / "examples/catalog", self.repo)
        self.git("init", "-q")
        self.base = self.commit()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True).strip()

    def commit(self):
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@localhost",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def product(self, revision, base=None):
        return resolve(self.repo, base or self.base, revision, "runtime.json", "lima")

    def test_dirty_worktree_cannot_override_committed_product_or_judge(self):
        candidate_source = b"print('candidate')\n"
        (self.repo / "app.py").write_bytes(candidate_source)
        revision = self.commit()
        (self.repo / "app.py").write_text("dirty")
        (self.repo / "outcome.json").write_text("{}")
        with self.product(revision) as product:
            self.assertEqual(product.source, candidate_source)
            self.assertEqual(product.contract.probes[0].expect, {"items": ["notebook"]})
            self.assertEqual(product.identity["base"], self.base)
            self.assertEqual(product.identity["revision"], revision)
            with self.assertRaisesRegex(ValueError, "inside pilot"):
                Contract.read(product.contract_path)

    def test_candidate_cannot_change_acceptance(self):
        contract = self.repo / "outcome.json"
        contract.write_text(contract.read_text().replace("notebook", "wrong"))
        with self.assertRaisesRegex(ValueError, "protected paths"):
            with self.product(self.commit()):
                pass

    def test_source_must_be_a_regular_git_blob(self):
        app = self.repo / "app.py"
        app.unlink()
        app.symlink_to("outcome.json")
        with self.assertRaisesRegex(ValueError, "regular file"):
            with self.product(self.commit()):
                pass

    def test_unknown_build_instructions_rejected_in_plan(self):
        spec = self.repo / "runtime.json"
        data = json.loads(spec.read_text())
        data["build"]["command"] = "build"
        spec.write_text(json.dumps(data))
        base = self.commit()
        with self.assertRaisesRegex(ValueError, "python-stdlib"):
            with self.product(base, base):
                pass

    def test_cleanup_replay_after_backend_shutdown(self):
        from argparse import Namespace
        from unittest.mock import patch
        from delivery.product_runtime import dispatch

        state = self.repo / "state"
        state.mkdir()
        missing = state / "offline"
        context = "kind-adl-test"
        for backend in ("compose", "kubernetes", "lima"):
            with self.subTest(backend=backend):
                args = Namespace(runtime_action="cleanup", state=state,
                                 socket=missing if backend == "compose" else None,
                                 kubeconfig=missing if backend == "kubernetes" else None,
                                 context=context if backend == "kubernetes" else None)
                receipt = {"product": {"backend": backend}, "context": context,
                           "socket": str(missing.resolve()), "cleanup": {"status": "confirmed"}}
                path = state / "runtime.json"
                path.write_text(json.dumps(receipt))
                with patch("delivery.lima_pilot.Lima", side_effect=FileNotFoundError("offline")):
                    self.assertEqual(dispatch(args), (receipt, 0))
                    receipt["cleanup"]["status"] = "pending"
                    path.write_text(json.dumps(receipt))
                    with self.assertRaises(FileNotFoundError):
                        dispatch(args)
                    self.assertEqual(json.loads(path.read_text()), receipt)
