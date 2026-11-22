from io import BytesIO
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from delivery.firecracker_pilot import MAX_SERIAL, observe, preflight, vm_config


class FirecrackerTests(unittest.TestCase):
    def test_mac_preflight_fails_before_assets_or_state(self):
        with patch("delivery.firecracker_pilot.platform.system", return_value="Darwin"):
            with self.assertRaisesRegex(ValueError, "Linux host with /dev/kvm"):
                preflight(Path("/missing"))

    def test_linux_preflight_refuses_unavailable_kvm(self):
        with patch("delivery.firecracker_pilot.platform.system", return_value="Linux"), \
                patch("delivery.firecracker_pilot.platform.machine", return_value="x86_64"), \
                patch("builtins.open", side_effect=PermissionError):
            with self.assertRaisesRegex(ValueError, "requires usable read/write /dev/kvm"):
                preflight(Path("/missing"))

    def test_boot_disks_are_read_only_and_config_exposes_no_network(self):
        files = {"vmlinux": Path("/kernel"), "rootfs.ext4": Path("/rootfs")}
        product = SimpleNamespace(cpu_limit=0.5, memory_mb=64)
        config = vm_config(files, Path("/payload"), product)
        self.assertEqual(set(config), {"boot-source", "drives", "machine-config"})
        self.assertTrue(all(disk["is_read_only"] for disk in config["drives"]))
        self.assertEqual(config["machine-config"], {"vcpu_count": 1, "mem_size_mib": 160})

    def test_serial_reads_the_framed_result_by_line(self):
        report = b'boot\nADL_FIRECRACKER_RESULT {"verdict":"failed"}\r\n'
        with subprocess.Popen([sys.executable, "-c", f"import os; os.write(1, {report!r})"],
                              stdout=subprocess.PIPE) as process:
            serial = BytesIO()
            self.assertEqual(observe(process, time.monotonic() + 3, serial), {"verdict": "failed"})
            self.assertEqual(serial.getvalue(), report)

    def test_no_serial_marker_fails_and_logs_are_bounded(self):
        for label, output_bytes, error in (("early-exit", 10, "exited"), ("flood", MAX_SERIAL + 1, "limit")):
            with self.subTest(label=label), TemporaryDirectory() as directory:
                path = Path(directory) / "serial"
                with subprocess.Popen([sys.executable, "-c", f"import os; os.write(1, b'a' * {output_bytes})"],
                                      stdout=subprocess.PIPE) as process, path.open("wb") as serial:
                    try:
                        with self.assertRaisesRegex(ValueError, error):
                            observe(process, time.monotonic() + 3, serial)
                        self.assertLessEqual(serial.tell(), MAX_SERIAL)
                    finally:
                        process.kill()

    @unittest.skipUnless(sys.platform == "linux", "requires Linux prctl")
    def test_launch_requires_operator_go_ahead(self):
        from delivery.firecracker_pilot import LAUNCH

        retry = subprocess.run([sys.executable, "-c", LAUNCH, "/bin/echo", "started"], input=b"",
                               capture_output=True, timeout=3, env={"PATH": os.defpath})
        self.assertNotEqual(retry.returncode, 0)
        self.assertEqual(retry.stdout, b"")
        started = subprocess.run([sys.executable, "-c", LAUNCH, "/bin/echo", "started"], input=b"x",
                                 capture_output=True, timeout=3, env={"PATH": os.defpath})
        self.assertEqual(started.stdout, b"started\n")
