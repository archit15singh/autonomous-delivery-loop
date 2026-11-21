import base64
from contextlib import ExitStack
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from delivery import kube_pilot as kube


class ProductKubeTests(unittest.TestCase):
    def product(self, redis):
        return SimpleNamespace(source=b"print('from Git')\n", revision="a" * 40,
                               port=9123, redis=redis, memory_mb=64, cpu_limit=0.25,
                               identity={"backend": "kubernetes"}, contract=SimpleNamespace(digest="digest"))

    def test_http_manifests_use_exact_source_and_declared_resources(self):
        product = self.product(False)
        config, api = kube.manifests("adl-run", kube.PYTHON, product.revision, product)["items"]
        self.assertTrue(config["immutable"])
        self.assertEqual(base64.b64decode(config["binaryData"]["service.py"]), product.source)
        pod = api["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertEqual(pod["volumes"][0]["configMap"]["name"], config["metadata"]["name"])
        container = pod["containers"][0]
        self.assertEqual(container["image"], kube.PYTHON)
        self.assertTrue(container["volumeMounts"][0]["readOnly"])
        self.assertEqual(container["command"], ["python", "-I", "-B", "/product/service.py"])
        env = {entry["name"]: entry["value"] for entry in container["env"]}
        self.assertEqual(env["ADL_PORT"], "9123")
        self.assertNotIn("ADL_REDIS_HOST", env)
        self.assertEqual(container["resources"]["limits"], {"memory": "64Mi", "cpu": "0.25"})

    def test_redis_readback_and_http_only_dispatch(self):
        for redis, readback, verdict in ((False, "", "verified"), (True, "2", "verified"), (True, "1", "failed")):
            with self.subTest(redis=redis, readback=readback), TemporaryDirectory() as temp, ExitStack() as mocks:
                product = self.product(redis)
                mock_kube = MagicMock()
                def call(*args, **options):
                    if args[0] == "config":
                        return json.dumps({"clusters": [{"cluster": {"server": "https://127.0.0.1:4999"}}]})
                    if args[0] == "create" and "-o" in args:
                        return '{"metadata":{"uid":"owned"}}'
                    if args[0] == "exec":
                        return readback
                    return ""
                mock_kube.call.side_effect = call
                mock_kube.get.return_value = {"metadata": {"uid": "cluster"}}
                mocks.enter_context(patch.object(kube, "Kubectl", return_value=mock_kube))
                mocks.enter_context(patch.object(kube, "running_definition", return_value={"revision": "base"}))
                mocks.enter_context(patch.object(kube, "ownership", return_value=None))
                mocks.enter_context(patch.object(kube, "cleanup", return_value={"status": "confirmed"}))
                ping = mocks.enter_context(patch.object(kube, "wait_for_redis_service", return_value="PONG"))
                rollout = mocks.enter_context(patch.object(kube, "rollout"))
                probe = mocks.enter_context(patch.object(kube, "probe", return_value=(
                    {"verdict": "verified", "reason": "all_required_evidence_passed"}, "sha256:image")))
                result = kube.run(Path(temp) / "config", "kind-adl-test", Path(temp), product=product)
                self.assertEqual(result["verdict"], verdict)
                self.assertEqual(result["product"], product.identity)
                self.assertEqual(probe.call_args.args[-1], product.port)
                self.assertEqual(rollout.call_count, 2 if redis else 1)
                self.assertEqual(ping.called, redis)
                self.assertEqual("redis_counter" in result, redis)
                if verdict == "failed":
                    self.assertEqual(result["reason"], "redis_readback_mismatch")

    def test_product_incompatible_options_fail_before_cluster_access(self):
        for options in ({"image": "foreign"}, {"rollback_revision": "b" * 40},
                        {"revision": "b" * 40}, {"retry": True}, {"cleanup_only": True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                kube.run(None, "not-a-context", None, product=self.product(False), **options)
