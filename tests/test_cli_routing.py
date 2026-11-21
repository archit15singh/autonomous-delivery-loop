from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from delivery import runtime_cli
from delivery.__main__ import main


class CliRoutingTests(unittest.TestCase):
    def test_pilot_exit_status_uses_the_requested_operation(self):
        receipt = {"verdict": "failed", "cleanup": {"status": "confirmed"}}
        cases = [
            ("compose-pilot", "compose_pilot", ["--socket", "docker.sock"]),
            ("lima-pilot", "lima_pilot", []),
            ("kube-pilot", "kube_pilot", ["--context", "kind-adl-test", "--kubeconfig", "config"]),
        ]
        for command, driver, options in cases:
            for flags, expected in (([], 1), (["--cleanup-only"], 0)):
                argv = ["delivery", "factory", command, "--state", "state", *options, *flags]
                with self.subTest(command=command, flags=flags), patch("sys.argv", argv), \
                        patch.object(runtime_cli, driver, return_value=receipt) as operation, \
                        redirect_stdout(StringIO()) as output:
                    self.assertEqual(main(), expected)
                    self.assertEqual(json.loads(output.getvalue()), receipt)
                    self.assertEqual(operation.call_args.kwargs["cleanup_only"], bool(flags))

    def test_upstream_merges_and_pending_collection_keep_their_distinct_exit_codes(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            scan = root / "scan.json"
            scan.write_text("[]")
            report = {"missing_prs": ["unavailable"], "branches": []}
            destination = root / "reports" / "merges.json"
            argv = ["delivery", "upstream-merges", str(scan), "--output", str(destination)]
            with patch("sys.argv", argv), patch("delivery.upstream_cli.merge_precedents", return_value=report):
                self.assertEqual(main(), 1)
            self.assertEqual(json.loads(destination.read_text()), report)

            argv = ["delivery", "factory", "hosted-runtime", "collect", "--state", str(root)]
            with patch("sys.argv", argv), patch.object(runtime_cli.hosted_runtime, "collect",
                                                       return_value={"status": "queued"}), \
                    redirect_stdout(StringIO()) as output:
                self.assertEqual(main(), 3)
                self.assertEqual(json.loads(output.getvalue()), {"status": "queued"})
