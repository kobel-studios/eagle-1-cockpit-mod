"""Offline validation of the exact-input camera patch and manager package."""
from pathlib import Path
import json
import struct
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build_cockpit_patch as builder

FIXTURE = ROOT / "extracted/vfc/12970356483147164383.lua/toc.bin"


class CockpitTests(unittest.TestCase):
    def test_unknown_input_rejected(self):
        with self.assertRaises(ValueError):
            builder.patch_resource(b"wrong build")

    @unittest.skipUnless(FIXTURE.exists(), "original VFC fixture missing")
    def test_only_camera_and_flight_feel_bytes_change(self):
        original = FIXTURE.read_bytes()
        (result, offset, hover_offset, zhold_offset, tau_offset,
         gravity_offset) = builder.patch_resource(original)
        before, after = map(builder.inspect_lj.unwrap, (original, result))
        self.assertEqual(after[offset:offset + 4], b"\x4b\x00\x01\x00")
        self.assertEqual(before[hover_offset], 2)
        self.assertEqual(after[hover_offset], 1)
        self.assertEqual(before[zhold_offset], ord("z"))
        self.assertEqual(after[zhold_offset], ord("x"))
        tau_value = tau_offset + len(builder.TAU_NEEDLE) - 1
        self.assertEqual(before[tau_value], 2)
        self.assertEqual(after[tau_value], builder.NEW_TAU_IDLE)
        gravity_value = gravity_offset + len(b"\x0cgravity\x04")
        # Everything outside the five edited spans is byte-identical.
        spans = sorted([(offset, offset + 4), (hover_offset, hover_offset + 1),
                        (zhold_offset, zhold_offset + 1),
                        (tau_value, tau_value + 1),
                        (gravity_value, gravity_value + 10)])
        pos = 0
        for start, end in spans:
            self.assertEqual(before[pos:start], after[pos:start])
            pos = end
        self.assertEqual(before[pos:], after[pos:])
        self.assertEqual(len(original), len(result))
        # Flight/host guards remain in the identical unmodified remainder.
        parsed = builder.inspect_lj.parse(after)
        self.assertEqual(len(parsed), 103)
        tables = [c for p in parsed for c in p["constants"]
                  if isinstance(c, dict) and isinstance(c.get("hash"), list)
                  and any(pair[0] == "hover_hold" for pair in c["hash"])]
        self.assertEqual(len(tables), 1)
        defaults = dict(tables[0]["hash"])
        self.assertFalse(defaults["hover_hold"])
        self.assertEqual(defaults["gravity"], builder.NEW_GRAVITY)
        self.assertEqual(defaults["tau_idle"], builder.NEW_TAU_IDLE)
        # Only the takeoff proto's zhold write key became a dead "xhold" write;
        # the physics proto keeps its own zhold constant for reads.
        by_id = {p["id"]: p for p in parsed}
        proto54 = by_id[54]
        self.assertIn("xhold", proto54["constants"])
        self.assertNotIn("zhold", [c for c in proto54["constants"]
                                   if isinstance(c, str)])
        self.assertIn("zhold", by_id[55]["constants"])
        with self.assertRaises(ValueError):
            builder.patch_resource(result)

    @unittest.skipUnless(FIXTURE.exists(), "original VFC fixture missing")
    def test_package_manifest_and_expected_resources(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "cockpit.zip"
            report = builder.build(FIXTURE, target)
            self.assertFalse(report["game_tested"])
            with zipfile.ZipFile(target) as z:
                manifest = json.loads(z.read("manifest.json"))
                self.assertEqual(manifest["Options"][0]["Include"], ["Addon"])
                self.assertIn("No new bombs", manifest["Description"])
                self.assertEqual(len(z.namelist()), 6)
                data = z.read("Addon/9ba626afa44a3aa3.patch_0")
                patch = Path(tmp) / "roundtrip.patch_0"
                patch.write_bytes(data)
            toc = builder.archive.StreamToc()
            self.assertTrue(toc.FromFile(str(patch)))
            self.assertEqual(toc.numFiles, 2)
            entry = toc.GetEntry(builder.RESOURCE_ID, builder.LUA_TYPE)
            self.assertTrue(bytes(entry.TocData)[8:].startswith(
                b"-- HD2-Addon: mods/codex/vehicle_flight\n"))
            self.assertEqual(builder.archive.murmur64_hash(
                builder.RESOURCE_NAME.encode()), builder.RESOURCE_ID)
            with self.assertRaises(FileExistsError):
                builder.build(FIXTURE, target)

    def test_configuration_changes_only_camera_fields(self):
        source = ("; keep comments\r\n[camera]\r\ndistance = 100 ; note\r\nfov = 100\r\n"
                  "look_low = -15\r\nlook_high = 25\r\n"
                  "[vehicles]\r\ndistance = 5000\r\n[first_person]\r\n"
                  "enabled = 0\r\nbelow = 100\r\neye_forward = -50\r\n"
                  "[seat_distance]\r\n123 = 250\r\n[other]\r\nvalue = 9\r\n")
        changed = builder.camera_config(source)
        self.assertIn("distance = 25 ; note\r\n", changed)
        self.assertIn("fov = 100\r\n", changed)
        self.assertIn("look_low = -85\r\nlook_high = 85\r\n", changed)
        self.assertIn("eye_forward = -50\r\n", changed)
        self.assertIn("123 = 25\r\n", changed)
        self.assertTrue(changed.endswith("[other]\r\nvalue = 9\r\n"))
        self.assertEqual(builder.camera_config(changed), changed)

    def test_incomplete_configuration_rejected(self):
        with self.assertRaises(ValueError):
            builder.camera_config("[camera]\ndistance=100\n")

    def test_lua_archive_layout_matches_loader_contract(self):
        data = builder.encode_lua_archive({90: b"b" * 17, 20: b"a"})
        self.assertEqual(struct.unpack_from("<III", data), (0xF0000011, 1, 2))
        self.assertEqual(struct.unpack_from("<Q", data, 32)[0], len(data))
        self.assertEqual(len(data) % 16, 0)
        for i, (key, payload) in enumerate(((20, b"a"), (90, b"b" * 17))):
            entry = struct.unpack_from("<7Q6I", data, 104 + i * 80)
            self.assertEqual(entry[0:2], (key, builder.LUA_TYPE))
            self.assertEqual(entry[2] % 16, 0)
            self.assertEqual(entry[10:], (16, 16, i))
            self.assertEqual(data[entry[2]:entry[2] + entry[7]], payload)
        with self.assertRaises(ValueError):
            builder.encode_lua_archive({})


if __name__ == "__main__":
    unittest.main()
