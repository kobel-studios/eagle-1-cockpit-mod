"""Focused tests for build_probe_patch.py and the eagle_probe entry."""
import json
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

WORK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORK)
sys.path.insert(0, os.path.join(WORK, "hd2tools"))

import hd2_archive as A  # noqa: E402
import build_probe_patch as B  # noqa: E402


class TestEnvelope(unittest.TestCase):
    def test_envelope_layout(self):
        env = B.build_envelope(b"abc")
        body_len, ver = struct.unpack_from("<II", env)
        self.assertEqual(body_len, 3)
        self.assertEqual(ver, 2)
        self.assertEqual(env[8:], b"abc")

    def test_resource_name_declaration(self):
        with open(B.ENTRY, "rb") as f:
            src = f.read()
        first = src.split(b"\n", 1)[0]
        self.assertEqual(first, b"-- HD2-Addon: mods/devin/eagle_probe")
        self.assertEqual(A.murmur64_hash(B.RESOURCE),
                         A.murmur64_hash(b"mods/devin/eagle_probe"))


class TestProbeSource(unittest.TestCase):
    def setUp(self):
        with open(B.ENTRY, "rb") as f:
            self.src = f.read().decode("utf-8")

    def test_no_writes_to_game(self):
        # The probe must not touch files, memory, or engine state. Reading
        # function references to log them is fine; calls are not.
        for bad in ("io.open", "os.execute", "ffi.", "VirtualProtect",
                    "WriteProcessMemory", "jit.flush"):
            self.assertNotIn(bad, self.src, bad)
        for call in ("spawn_unit(", "destroy_unit(", "set_local_pose(",
                     "spawn_scene("):
            self.assertNotIn(call, self.src, call)

    def test_probe_is_pcall_wrapped(self):
        self.assertIn("pcall(function()", self.src)

    def test_probe_logs_expected_apis(self):
        for name in ("stingray", "spawn_unit", "world_pose", "package.loaded",
                     "CowboyBingusModLoader"):
            self.assertIn(name, self.src)


class TestBuildOutput(unittest.TestCase):
    def test_patch_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            outdir = os.path.join(tmp, "EagleProbe")
            with mock.patch.object(B, "OUTDIR", outdir):
                B.main()
            patch = os.path.join(outdir, "9ba626afa44a3aa3.patch_0")
            self.assertTrue(os.path.exists(patch))
            for side in (".gpu_resources", ".stream"):
                self.assertTrue(os.path.exists(patch + side))
            back = A.StreamToc()
            self.assertTrue(back.FromFile(patch, SerializeData=True))
            fid = A.murmur64_hash(B.RESOURCE)
            data = bytes(back.TocDict[B.LUA_TYPE][fid].TocData)
            want = B.build_envelope(open(B.ENTRY, "rb").read())
            self.assertEqual(data, want)
            manifest = json.load(open(os.path.join(outdir, "manifest.json")))
            self.assertEqual(manifest["Name"], "Eagle Probe (diagnostics)")

    def test_missing_entry_fails(self):
        with mock.patch.object(B, "ENTRY", os.path.join(WORK, "nope.lua")):
            with self.assertRaises((FileNotFoundError, AssertionError)):
                B.main()


if __name__ == "__main__":
    unittest.main()
