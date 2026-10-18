"""Synthetic package checks. No game, SDK, Lua runtime, or installation access."""

import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import verify_eagle_package as checker


class PackageCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.module = "mods/test/example"
        self.source = b"return {enabled=true}\n"
        (self.root / "entry.lua").write_bytes(self.source)
        self.source_names = {self.module: "entry.lua"}
        body = struct.pack("<II", len(self.source), 2) + self.source
        self.body = body
        fid = checker.murmur64_hash(self.module.encode())
        # Independent fixed, one-resource archive fixture.
        self.toc = (struct.pack("<4I56x", 0xF0000011, 1, 1, 0)
                    + struct.pack("<QQQII", 0, checker.LUA, 1, 16, 64)
                    + struct.pack("<7Q6I", fid, checker.LUA, 184, 0, 0, 0, 0,
                                  len(body), 0, 0, 16, 64, 1) + body)
        self.patch = checker.BASE + ".patch_0"
        self.report = {
            "archive_order": [{"archive": self.patch, "label": "fixture"}],
            "archives": {checker.BASE: {"resources": [{
                "file_id": hex(fid), "type_id": hex(checker.LUA), "winner": "fixture",
                "toc_sha256": hashlib.sha256(body).hexdigest(),
                "gpu_sha256": hashlib.sha256(b"").hexdigest(),
                "stream_sha256": hashlib.sha256(b"").hexdigest(),
            }]}},
        }
        self.members = {
            "manifest.json": json.dumps({"Version": 1, "Name": "Fixture",
                                        "Options": [{"Include": ["Addon"]}]}).encode(),
            "Addon/" + self.patch: self.toc,
            "Addon/" + self.patch + ".gpu_resources": b"",
            "Addon/" + self.patch + ".stream": b"",
        }

    def write(self):
        path = self.root / "fixture.zip"
        with zipfile.ZipFile(path, "w") as bundle:
            bundle.writestr("validation.json", json.dumps(self.report))
            for name, data in self.members.items():
                bundle.writestr(name, data)
        return path

    def check(self):
        return checker.check(self.write(), self.root, self.source_names)

    def test_matching_package_and_source_pass_without_writes(self):
        package = self.write()
        original = package.read_bytes()
        before = set(self.root.iterdir())
        result = checker.check(package, self.root, self.source_names)
        self.assertEqual(result["winning_resources"], 1)
        self.assertEqual(result["layers"], 1)
        self.assertEqual(result["package_sha256"], hashlib.sha256(original).hexdigest())
        self.assertFalse(result["game_tested"])
        self.assertEqual(set(self.root.iterdir()), before)
        self.assertEqual(package.read_bytes(), original)
        self.assertEqual((self.root / "entry.lua").read_bytes(), self.source)

    def test_stale_module_requires_rebuild(self):
        (self.root / "entry.lua").write_bytes(b"return {enabled=false}\n")
        with self.assertRaisesRegex(ValueError, "stale Lua: entry.lua"):
            self.check()

    def test_missing_source_module_rejected(self):
        self.source_names["mods/test/missing"] = "entry.lua"
        with self.assertRaisesRegex(ValueError, "Missing local Lua module"):
            self.check()

    def test_sidecar_and_unreported_layer_rejected(self):
        del self.members["Addon/" + self.patch + ".gpu_resources"]
        with self.assertRaisesRegex(ValueError, "Missing patch member"):
            self.check()
        self.members["Addon/" + self.patch + ".gpu_resources"] = b""
        self.members["Addon/" + checker.BASE + ".patch_1"] = self.toc
        with self.assertRaisesRegex(ValueError, "unreported patch"):
            self.check()

    def test_wrong_report_hash_rejected(self):
        self.report["archives"][checker.BASE]["resources"][0]["toc_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            self.check()

    def test_duplicate_or_wrong_priority_layer_rejected(self):
        self.report["archive_order"] *= 2
        with self.assertRaisesRegex(ValueError, "duplicate patch"):
            self.check()
        self.report["archive_order"] = [{"archive": checker.BASE + ".patch_1",
                                         "label": "fixture"}]
        with self.assertRaisesRegex(ValueError, "numbered patch priority"):
            self.check()

    def test_truncated_cpu_and_gpu_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "CPU"):
            checker.read_layer(self.toc[:-1], b"", b"")
        bad = bytearray(self.toc)
        struct.pack_into("<I", bad, 104 + 64, 1)  # one byte of GPU data required
        with self.assertRaisesRegex(ValueError, "GPU"):
            checker.read_layer(bad, b"", b"")

    def test_report_duplicate_and_source_escape_rejected(self):
        records = self.report["archives"][checker.BASE]["resources"]
        records.append(records[0].copy())
        with self.assertRaisesRegex(ValueError, "Duplicate resource"):
            self.check()
        records.pop()
        self.source_names[self.module] = "../outside.lua"
        with self.assertRaisesRegex(ValueError, "leaves its project"):
            self.check()


if __name__ == "__main__":
    unittest.main()
