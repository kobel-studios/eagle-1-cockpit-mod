"""Verify every required module is packaged without third-party Runtime code."""
from pathlib import Path
import json
import struct
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build_eagle_payload as builder


class PayloadPackageTests(unittest.TestCase):
    def test_package_has_exact_modules_and_valid_envelopes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "payload.zip"
            builder.build(path)
            with zipfile.ZipFile(path) as z:
                manifest = json.loads(z.read("manifest.json"))
                self.assertEqual(manifest["Guid"], builder.GUID)
                self.assertEqual(len(z.namelist()), 6)
                report = json.loads(z.read("validation.json"))
                self.assertFalse(report["game_tested"])
                self.assertEqual(report["runtime_version"], "0.40.0")
                data = z.read("Addon/9ba626afa44a3aa3.patch_0")
            magic, types, count = struct.unpack_from("<III", data)
            self.assertEqual((magic, types, count), (0xF0000011, 1, 5))
            expected = {builder.archive.murmur64_hash(n.encode()): (n, f)
                        for n, f in builder.SOURCES.items()}
            declarations = []
            for i in range(count):
                row = struct.unpack_from("<7Q6I", data, 104 + 80 * i)
                name, filename = expected.pop(row[0])
                self.assertEqual(row[1], 0xA14E8DFA2CD117E2)
                self.assertEqual(row[2] % 16, 0)
                payload = data[row[2]:row[2] + row[7]]
                size, version = struct.unpack_from("<II", payload)
                self.assertEqual((size, version), (len(payload) - 8, 2))
                self.assertEqual(payload[8:], (ROOT / filename).read_bytes())
                if payload[8:].startswith(b"-- HD2-Addon:"):
                    declarations.append(name)
            self.assertEqual(expected, {})
            self.assertEqual(declarations, [builder.ENTRY])
            with self.assertRaises(FileExistsError):
                builder.build(path)


if __name__ == "__main__":
    unittest.main()
