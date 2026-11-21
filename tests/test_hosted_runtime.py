import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from delivery import hosted_runtime


class HostedRuntimeTests(unittest.TestCase):
    def test_reserved_state_prevents_a_second_dispatch(self):
        with TemporaryDirectory() as folder, patch.object(hosted_runtime, "remote_ref") as remote:
            state = Path(folder)
            (state / "request.json").write_text('{"status": "dispatch_unconfirmed"}')
            with self.assertRaisesRegex(ValueError, "already holds a dispatch"):
                hosted_runtime.start(Path("."), state, "a" * 40, "pilot")
            remote.assert_not_called()

    def test_collect_rejects_a_run_from_different_main(self):
        repo = hosted_runtime.OWNER_REPO
        revision = "a" * 40
        with TemporaryDirectory() as folder:
            state = Path(folder)
            request = {"run_id": 7, "url": f"https://github.com/{repo}/actions/runs/7",
                       "revision": revision, "contract": "pilot", "policy_revision": "b" * 40}
            (state / "request.json").write_text(json.dumps(request))
            run = {"id": 7, "repository": {"full_name": repo}, "event": "workflow_dispatch",
                   "head_branch": "main", "head_sha": "c" * 40,
                   "path": ".github/workflows/trusted-candidate.yml",
                   "display_title": f"Verify {revision} against pilot"}
            with patch.object(hosted_runtime, "gh_json", return_value=run), \
                 patch.object(hosted_runtime.subprocess, "run") as download:
                with self.assertRaisesRegex(ValueError, "differs from the reserved"):
                    hosted_runtime.collect(Path("."), state)
                download.assert_not_called()
