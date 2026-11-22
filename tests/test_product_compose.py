import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from delivery import compose_pilot as pilot


class ComposeProductTest(unittest.TestCase):
    def test_exact_external_source_configures_runtime_and_optional_redis_readback(self):
        contract = pilot.Contract.read(pilot.CONTRACT)
        revision = "a" * 40
        image = "sha256:" + "b" * 64
        policy = {"revision": "c" * 40, "sha256": "d" * 64}
        observed = {"verdict": "verified", "reason": "all_required_evidence_passed"}
        source = b'print("standalone product")\n'

        for redis in (False, True):
            with self.subTest(redis=redis), TemporaryDirectory() as folder, socket.socket(socket.AF_UNIX) as engine:
                root = Path(folder)
                endpoint = root / "docker.sock"
                engine.bind(str(endpoint))
                state = root / "run"
                product = SimpleNamespace(revision=revision, source=source, source_path="app/main.py",
                                          contract=contract, redis=redis, port=9100, cpu_limit=0.25,
                                          memory_mb=64, identity={"id": "example", "backend": "compose"})
                commands = []

                def docker(socket_path, config, cwd, *args, variables, timeout):
                    commands.append(args)
                    self.assertEqual(variables["COMPOSE_PROFILES"], "redis" if redis else "")
                    self.assertEqual(variables["ADL_API_PORT"], "9100")
                    self.assertEqual(variables["ADL_API_MEMORY"], "64m")
                    self.assertEqual(set(json.loads(variables["ADL_PROBE_PATHS"])),
                                     {"/_revision", *(probe.path for probe in contract.probes)})
                    if args[0] == "build":
                        context = Path(args[-1])
                        self.assertEqual((context / "service.py").read_bytes(), source)
                        self.assertEqual((context / "Dockerfile").read_bytes(), pilot.PRODUCT_RECIPE.read_bytes())
                    if args[:2] == ("image", "inspect"):
                        return image
                    if args[0] == "version":
                        return "28.0.0"
                    if args[:2] == ("compose", "version"):
                        return "2.39.4"
                    if args[0] == "info":
                        return "engine"
                    return ""

                with (
                    patch.object(pilot, "docker_cli", side_effect=docker),
                    patch.object(pilot, "disk_usage", return_value=SimpleNamespace(free=pilot.MIN_FREE_BYTES)),
                    patch.object(pilot, "running_definition", return_value=policy),
                    patch.object(pilot.Compose, "observe", return_value=observed) as observe,
                    patch.object(pilot, "git", side_effect=AssertionError("must use the resolved product revision")),
                ):
                    receipt = pilot.run(endpoint, state, revision, product=product)
                observe.assert_called_once_with(contract, image)
                self.assertTrue(any(command[0] == "build" for command in commands))
                self.assertEqual(receipt["product"], product.identity)
                self.assertEqual(receipt["cleanup"]["status"], "confirmed")
                self.assertEqual(receipt["verdict"], "failed" if redis else "verified")
                self.assertEqual(any("redis-cli" in command for command in commands), redis)
                if redis:
                    self.assertEqual(receipt["reason"], "redis_readback_mismatch")

    def test_cleanup_recovers_partial_start_with_original_template_and_no_product_options(self):
        with TemporaryDirectory() as folder, socket.socket(socket.AF_UNIX) as engine:
            state = Path(folder)
            endpoint = state / "docker.sock"
            engine.bind(str(endpoint))
            project = "adl-pilot-" + "f" * 16
            saved_template = state / "compose.yaml"
            saved_template.write_text('services: {api: {image: "${ADL_IMAGE:?}"}}\n')
            receipt = {"revision": "b" * 40, "deployment": project, "socket": str(endpoint.resolve()),
                       "template_sha256": pilot.file_digest(saved_template), "engine": "engine",
                       "reason": "interrupted", "cleanup": {"status": "pending"}}
            pilot.record(state / "runtime.json", receipt)
            resources = {"container": "owned-container"}
            down_calls = []

            def docker(socket_path, config, cwd, *args, variables, timeout):
                self.assertEqual(variables["ADL_PROJECT"], project)
                if args[0] == "info":
                    return "engine"
                if args[0] in resources:
                    self.assertIn(f"label=com.docker.compose.project={project}", args)
                    return resources[args[0]]
                if "down" in args:
                    self.assertIn(str(saved_template.resolve()), args)
                    self.assertIn(project, args)
                    down_calls.append(args)
                    resources.clear()
                return ""

            with patch.object(pilot, "docker_cli", side_effect=docker):
                result = pilot.run(endpoint, state, None, cleanup_only=True)
            self.assertEqual(len(down_calls), 1)
            self.assertEqual(result["cleanup"]["status"], "confirmed")
            self.assertEqual(result["reason"], "interrupted")
