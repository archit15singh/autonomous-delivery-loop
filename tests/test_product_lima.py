from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from delivery import lima_pilot


class ProductLimaTests(unittest.TestCase):
    def test_optional_redis_network_and_app_limits(self):
        policy = {"revision": "a" * 40, "sha256": "b" * 64}
        for redis in (False, True):
            with self.subTest(redis=redis), TemporaryDirectory() as temp, \
                 patch.object(lima_pilot, "running_definition", return_value=policy), \
                 patch.object(lima_pilot, "Lima", autospec=True) as constructor:
                state = Path(temp)
                contract = state / "contract.json"
                contract.write_text("{}")
                source = b"print('hello')"
                product = SimpleNamespace(
                    source=source, source_path="app.py", revision="c" * 40,
                    contract_path=contract, contract=SimpleNamespace(digest=sha256(contract.read_bytes()).hexdigest()),
                    redis=redis, port=8190, cpu_limit=0.5, memory_mb=128,
                    identity={"name": "demo"},
                )
                guest = constructor.return_value
                guest.machine = "d" * 32
                guest.version = "test"
                guest.resources.return_value = []
                guest.cleanup.return_value = {"status": "confirmed"}
                guest.guest.return_value = sha256(source).hexdigest()

                def nerdctl(*args, **kwargs):
                    if args[:2] == ("run", "--rm"):
                        return json.dumps({"verdict": "verified", "reason": "all_required_evidence_passed"})
                    if args[0] == "exec":
                        return "2"
                    return "container-id"

                guest.nerdctl.side_effect = nerdctl
                with patch.object(lima_pilot, "payload", return_value=b"tar") as bundle:
                    result = lima_pilot.run(state, product=product)
                bundle.assert_called_once_with(source, policy["revision"], False, contract.read_bytes())
                self.assertEqual(result["verdict"], "verified")
                self.assertEqual(result["product"], product.identity)
                self.assertEqual("redis_counter" in result, redis)
                calls = [c.args for c in guest.nerdctl.call_args_list]
                project = result["deployment"]
                api = next(args for args in calls if args[:4] == ("run", "-d", "--name", project + "-api"))
                judge = next(args for args in calls if args[:2] == ("run", "--rm"))
                self.assertEqual(api[api.index("--network") + 1], f"container:{project}-redis" if redis else "none")
                self.assertEqual(api[api.index("--cpus") + 1], "0.5")
                self.assertEqual(api[api.index("--memory") + 1], "128m")
                self.assertIn("PORT=8190", api)
                self.assertIn("ADL_PORT=8190", api)
                self.assertEqual(judge[-2:], ("8190", "product"))
                self.assertEqual(judge[judge.index("--network") + 1],
                                 f"container:{project}-{'redis' if redis else 'api'}")
                self.assertEqual(any(args[0] == "exec" for args in calls), redis)
                guest.cleanup.assert_called_once()


if __name__ == "__main__":
    unittest.main()
