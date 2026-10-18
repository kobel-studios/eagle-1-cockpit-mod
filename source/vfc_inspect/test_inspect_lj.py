import unittest
import hashlib
import importlib.util
from pathlib import Path
from unittest.mock import patch

_spec = importlib.util.spec_from_file_location(
    "vfc_static_inspector", Path(__file__).with_name("inspect_lj.py"))
_inspector = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_inspector)
Reader, parse, unwrap, listing = (
    _inspector.Reader, _inspector.parse, _inspector.unwrap, _inspector.listing)


class InspectTests(unittest.TestCase):
    def test_reader_bounds(self):
        with self.assertRaises(ValueError):
            Reader(b"").byte()
        with self.assertRaises(ValueError):
            Reader(b"\x80" * 6).uleb()

    def test_unwrap_literal_only(self):
        self.assertEqual(unwrap(b"12345678local _c = \"\\027\\076\\074\""), b"\x1bLJ")
        for bad in [b"12345678local _c = get_code()", b'12345678local _c = "\\999"']:
            with self.assertRaises(ValueError):
                unwrap(bad)

    def test_minimal_proto_and_no_execution(self):
        # Single RET0 instruction; all input is treated as data.
        data = b"\x1bLJ\x02\x02\x0b\x00\x00\x01\x00\x00\x00\x01\x4b\x00\x01\x00\x00"
        with patch("builtins.exec", side_effect=AssertionError("must not execute")):
            p = parse(data)
            self.assertEqual(p[0]["instructions"], [0x1004b])
            self.assertIn("RET0", listing(p))
        for bad in [data[:-1], data + b"extra", b"not bytecode",
                    data[:4] + b"\x03" + data[5:]]:
            with self.assertRaises(ValueError):
                parse(bad)

    def test_extracted_vfc_regression(self):
        fixture = Path(__file__).resolve().parents[1] / "extracted/vfc/12970356483147164383.lua/toc.bin"
        if not fixture.is_file():
            self.skipTest("local VFC fixture unavailable")
        data = fixture.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         "abc28461aecb613afa24cb5662feef1cf97c9cd2ea82e332cb4567fb0ba93fb2")
        protos = parse(unwrap(data))
        self.assertEqual(len(protos), 103)
        self.assertEqual(protos[-1]["offset"] + protos[-1]["size"], 37027)
        defaults = dict(protos[-1]["constants"][70]["hash"])
        self.assertEqual(defaults["zoom"], 13)
        self.assertEqual(defaults["cam_lift"], 0.12)
        self.assertEqual(protos[-1]["constants"][77], {"proto": 60})
        self.assertEqual(protos[64]["numbers"], [100])
        self.assertIn("'VehicleFlight'", listing(protos))


if __name__ == "__main__":
    unittest.main()
