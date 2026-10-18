"""Focused tests for verify_eagle_deploy.check() — fake zip + fake data dir."""
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import verify_eagle_deploy as ved

ARCH = "9ba626afa44a3aa3"
ICON_ARCH = "007e093ca718ca1a"


def make_pack(path, layers):
    """layers: {filename: bytes}. Writes a fake Arsenal-style zip."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("manifest.json", '{"Name": "Eagle-1 Cockpit Pack T"}')
        for fname, data in layers.items():
            z.writestr("Addon/" + fname, data)


def deploy(data_dir, fname, data):
    with open(os.path.join(data_dir, fname), "wb") as f:
        f.write(data)


class VerifyDeployTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.zip_path = os.path.join(self.tmp.name, "pack.zip")
        self.data_dir = os.path.join(self.tmp.name, "data")
        os.mkdir(self.data_dir)
        self.payload = b"lua source eagle_payload eagle_camera_scope" * 8
        self.icon = b"xaml icons" * 16
        make_pack(self.zip_path, {
            ARCH + ".patch_0": self.payload,
            ICON_ARCH + ".patch_0": self.icon,
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_deploy(self):
        deploy(self.data_dir, ARCH + ".patch_11", self.payload)
        deploy(self.data_dir, ICON_ARCH + ".patch_0", self.icon)
        ok, lines = ved.check(self.zip_path, self.data_dir)
        self.assertTrue(ok, lines)
        self.assertTrue(any("OK" in l for l in lines))
        self.assertIn("Eagle-1 Cockpit Pack T", lines[0])

    def test_missing_layer(self):
        deploy(self.data_dir, ARCH + ".patch_11", self.payload)
        ok, lines = ved.check(self.zip_path, self.data_dir)
        self.assertFalse(ok)
        self.assertTrue(any("MISS" in l and ICON_ARCH in l for l in lines))

    def test_stale_payload_flagged(self):
        stale = b"old lua source eagle_payload" * 4  # marker present, hash differs
        deploy(self.data_dir, ARCH + ".patch_11", self.payload)
        deploy(self.data_dir, ARCH + ".patch_9", stale)
        deploy(self.data_dir, ICON_ARCH + ".patch_0", self.icon)
        ok, lines = ved.check(self.zip_path, self.data_dir)
        self.assertFalse(ok)
        self.assertTrue(any("STALE" in l and "patch_9" in l for l in lines))

    def test_unrelated_patch_is_other_not_stale(self):
        deploy(self.data_dir, ARCH + ".patch_11", self.payload)
        deploy(self.data_dir, ICON_ARCH + ".patch_0", self.icon)
        deploy(self.data_dir, ARCH + ".patch_40", b"\x00" * 4096)  # other mod
        ok, lines = ved.check(self.zip_path, self.data_dir)
        self.assertTrue(ok, lines)
        self.assertTrue(any("OTHER" in l and "patch_40" in l for l in lines))

    def test_missing_zip(self):
        ok, lines = ved.check(self.zip_path + ".nope", self.data_dir)
        self.assertFalse(ok)
        self.assertTrue(any("not found" in l for l in lines))


if __name__ == "__main__":
    unittest.main()
