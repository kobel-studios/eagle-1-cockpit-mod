"""Tests for hd2_archive: murmur hashing, archive round-trip, friendly names."""

import os
import tempfile
import unittest

import hd2_archive as A


class TestHashing(unittest.TestCase):
    def test_known_file_ids(self):
        # verified against hashlists/friendlynames.txt
        self.assertEqual(
            A.murmur64_hash(b"content/fac_helldivers/vehicles/frv/frv"),
            14709257759554793401)
        self.assertEqual(
            A.murmur64_hash(b"content/fac_helldivers/vehicles/eagle/eagle"),
            5638538380783989280)
        self.assertEqual(
            A.murmur64_hash(b"content/fac_helldivers/vehicles/combat_walker/combat_walker"),
            8783342891467425251)


class TestRoundTrip(unittest.TestCase):
    def _make_entry(self, file_id, type_id, toc=b"", gpu=b"", stream=b""):
        e = A.TocEntry()
        e.FileID = file_id
        e.TypeID = type_id
        e.SetData(bytearray(toc), bytearray(gpu), bytearray(stream))
        return e

    def test_write_then_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deadbeef")
            toc = A.StreamToc()
            toc.AddEntry(self._make_entry(111, A.UnitID, toc=b"\x01\x02\x03"))
            toc.AddEntry(self._make_entry(222, A.TexID,
                                          toc=b"\xaa" * 100,
                                          gpu=b"\xbb" * 64,
                                          stream=b"\xcc" * 200))
            toc.ToFile(path)

            self.assertTrue(os.path.exists(path))
            self.assertTrue(os.path.exists(path + ".gpu_resources"))
            self.assertTrue(os.path.exists(path + ".stream"))

            back = A.StreamToc()
            self.assertTrue(back.FromFile(path))
            e1 = back.GetEntry(111, A.UnitID)
            self.assertIsNotNone(e1)
            self.assertEqual(bytes(e1.TocData), b"\x01\x02\x03")
            e2 = back.GetEntry(222, A.TexID)
            self.assertIsNotNone(e2)
            self.assertEqual(bytes(e2.TocData), b"\xaa" * 100)
            self.assertEqual(bytes(e2.GpuData), b"\xbb" * 64)
            self.assertEqual(bytes(e2.StreamData), b"\xcc" * 200)

    def test_add_duplicate_fails(self):
        toc = A.StreamToc()
        toc.AddEntry(self._make_entry(5, A.UnitID, toc=b"x"))
        with self.assertRaises(Exception):
            toc.AddEntry(self._make_entry(5, A.UnitID, toc=b"y"))
        toc.AddEntry(self._make_entry(5, A.UnitID, toc=b"y"), override=True)
        self.assertEqual(bytes(toc.GetEntry(5, A.UnitID).TocData), b"y")

    def test_bad_magic_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad")
            with open(path, "wb") as f:
                f.write(b"\x00" * 100)
            toc = A.StreamToc()
            self.assertFalse(toc.FromFile(path))


class TestFriendlyNames(unittest.TestCase):
    def test_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "fn.txt")
            with open(p, "w") as f:
                f.write("123 content/a/b\n456 content/c/d\nnotanumber line\n")
            names = A.load_friendly_names(p)
            self.assertEqual(names[123], "content/a/b")
            self.assertEqual(names[456], "content/c/d")
            self.assertEqual(len(names), 2)


if __name__ == "__main__":
    unittest.main()
