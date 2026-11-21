from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest

from delivery.review_artifact import cached_json, retain


class ReviewArtifactTests(unittest.TestCase):
    def test_concurrent_creators_return_the_same_complete_record(self):
        with TemporaryDirectory() as temp:
            destination = Path(temp) / "trials" / "one.json"
            started = Barrier(2, timeout=5)

            def worker(worker_id):
                def create():
                    started.wait()
                    return {"worker": worker_id}
                return cached_json(destination, create)

            with ThreadPoolExecutor(max_workers=2) as pool:
                first, second = pool.map(worker, [1, 2])
            self.assertEqual(first, second)
            self.assertEqual(first, json.loads(destination.read_text()))
            self.assertEqual(first, cached_json(destination, lambda: self.fail("unexpected recomputation")))

    def test_retaining_a_different_replay_preserves_original(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "evidence"
            retain(path, "verified\n")
            retain(path, "verified\n")
            with self.assertRaisesRegex(ValueError, "saved artifact differs"):
                retain(path, "different\n")
            self.assertEqual(path.read_text(), "verified\n")
