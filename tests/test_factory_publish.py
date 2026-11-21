from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from delivery import factory_publish as publisher
from delivery.factory_evidence import compose_evidence
from delivery.verify import Contract


class PublisherTests(unittest.TestCase):
    def test_runtime_receipt_must_match_candidate_and_be_cleaned_up(self):
        revision, policy, source, contract, image = "a", "b", "c", "d", "e"
        deployment = "adl-pilot-" + "f" * 16
        receipt = {
            "verdict": "verified", "revision": revision, "policy_revision": policy,
            "source_sha256": source, "contract_sha256": contract, "deployment": deployment,
            "image_id": "sha256:" + image * 64, "redis_counter": "2",
            "cleanup": {"status": "confirmed", "remaining":
                        {kind: [] for kind in ("container", "network", "volume", "image")}},
            "observation": {"verdict": "verified", "revision": revision, "deployment": deployment,
                            "contract_sha256": contract, "ci": {"artifact_sha256": image * 64}},
        }
        self.assertEqual(compose_evidence(receipt, revision, policy, source, contract)["deployment"], deployment)
        for key, value in (("revision", "other"), ("source_sha256", "other"), ("policy_revision", "other"),
                           ("redis_counter", "1"), ("image_id", "sha256:" + "0" * 64),
                           ("cleanup", {"status": "unconfirmed"})):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "requires exact Compose evidence"):
                compose_evidence({**receipt, key: value}, revision, policy, source, contract)
        remaining = deepcopy(receipt)
        remaining["cleanup"]["remaining"]["volume"] = ["retained"]
        with self.assertRaisesRegex(ValueError, "confirmed cleanup"):
            compose_evidence(remaining, revision, policy, source, contract)

    def test_local_apply_fails_before_any_remote_lookup(self):
        with patch.dict("os.environ", {}, clear=True), patch.object(publisher, "remote_ref") as remote:
            with self.assertRaisesRegex(ValueError, "owned main Actions"):
                publisher.publish(Path("."), Path("missing"), "a" * 40, "pilot", apply=True)
            remote.assert_not_called()

    def test_signed_manifest_without_runtime_cannot_reach_publication(self):
        with TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "manifest.json"
            candidate, policy = "a" * 40, "b" * 40
            manifest.write_text(json.dumps({"version": 1, "revision": candidate, "policy_revision": policy}))
            with patch.object(publisher, "verify_signature") as verify, \
                 patch.object(publisher, "remote_ref", return_value=policy) as remote:
                with self.assertRaisesRegex(ValueError, "signed Compose"):
                    publisher.publish(Path("."), manifest, candidate, "pilot")
                verify.assert_called_once()
                remote.assert_called_once_with(Path("."), "refs/heads/main")

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
                "runtime": {"kind": "compose"},
                "contract_sha256": Contract.read(repo / "contracts/pilot.json").digest}))
            ledger = root / "actions.sqlite3"
            env = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": publisher.OWNER_REPO,
                   "GITHUB_REF": "refs/heads/main", "GH_TOKEN": "unit-test"}
            attempts = []
            real_run = subprocess.run

            def write_ref(args, **options):
                if args[0] == "git":
                    return real_run(args, **options)
                self.assertEqual(args[:4], ["gh", "api", "--method", "POST"])
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
                with self.assertRaises(subprocess.CalledProcessError):
                    publisher.publish(repo, manifest, candidate, "pilot", apply=True, ledger=ledger)
                self.assertEqual(refs[reservation], candidate)
                self.assertNotIn(staging, refs)
                done = publisher.publish(repo, manifest, candidate, "pilot", apply=True, ledger=ledger)
                self.assertEqual(done, publisher.publish(repo, manifest, candidate, "pilot", apply=True, ledger=ledger))
            self.assertEqual(attempts, [reservation, staging, staging])
            with closing(sqlite3.connect(ledger)) as db:
                self.assertEqual(db.execute("SELECT state FROM staging_publications").fetchall(), [("published",)])
