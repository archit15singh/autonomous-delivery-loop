import json
from pathlib import Path
import sqlite3
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from delivery import factory_publish as publisher
from delivery.verify import Contract


class PublisherTests(unittest.TestCase):
    def test_local_apply_fails_before_any_remote_lookup(self):
        with patch.dict("os.environ", {}, clear=True), patch.object(publisher, "remote_ref") as remote:
            with self.assertRaisesRegex(ValueError, "owned main Actions"):
                publisher.publish(Path("."), Path("missing"), "a" * 40, "pilot", apply=True)
            remote.assert_not_called()

    def test_interrupted_publication_resumes_from_exact_reservation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = Path(__file__).resolve().parents[1]
            policy = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            candidate = "a" * 40
            reservation = f"refs/heads/factory/intent-{candidate}"
            staging = f"refs/heads/factory/verified-{candidate}"
            refs = {"refs/heads/main": policy}
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"version": 1, "policy_revision": policy, "revision": candidate,
                "contract_sha256": Contract.read(repo / "contracts/pilot.json").digest}))
            ledger = root / "actions.sqlite3"
            env = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": publisher.OWNER_REPO,
                   "GITHUB_REF": "refs/heads/main", "GH_TOKEN": "unit-test"}
            attempts = []
            def write_ref(args, **options):
                ref = args[-3].removeprefix("ref=")
                attempts.append(ref)
                if attempts == [reservation, staging]:
                    raise subprocess.CalledProcessError(1, args)
                refs[ref] = candidate

            with patch.dict("os.environ", env, clear=True), patch.object(publisher, "verify_signature"), \
                 patch.object(publisher, "check_candidate"), \
                 patch.object(publisher, "remote_ref", side_effect=lambda _repo, ref: refs.get(ref)), \
                 patch.object(publisher.subprocess, "run", side_effect=write_ref):
                # Preserve real Git reads while replacing the authenticated GitHub write.
                with patch.object(publisher, "git", return_value=(repo / "contracts/pilot.json").read_bytes()):
                    with self.assertRaises(subprocess.CalledProcessError):
                        publisher.publish(repo, manifest, candidate, "pilot", apply=True, ledger=ledger)
                    self.assertEqual(refs[reservation], candidate)
                    self.assertNotIn(staging, refs)
                    done = publisher.publish(repo, manifest, candidate, "pilot", apply=True, ledger=ledger)
                    self.assertEqual(done, publisher.publish(repo, manifest, candidate, "pilot", apply=True, ledger=ledger))
            self.assertEqual(attempts, [reservation, staging, staging])
            with sqlite3.connect(ledger) as db:
                self.assertEqual(db.execute("SELECT state FROM staging_publications").fetchall(), [("published",)])
