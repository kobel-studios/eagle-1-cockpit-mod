"""Offline archive packing tests; all temporary files stay inside this project."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build_eagle_pack as pack


class EaglePackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def source(self, label, resources, base="1111111111111111"):
        directory = self.root / label
        directory.mkdir()
        path = directory / (base + ".patch_0")
        toc = pack.archive.StreamToc()
        for fid, tid, data, gpu, stream in resources:
            entry = pack.archive.TocEntry()
            entry.FileID, entry.TypeID = fid, tid
            entry.SetData(data, gpu, stream)
            toc.AddEntry(entry)
        toc.ToFile(str(path))
        return label, path

    def test_last_source_wins_without_losing_graphics_or_other_types(self):
        first = self.source("first", [(1, 101, b"old", b"old gpu", b"old stream"),
                                       (1, 102, b"other type", b"", b"")])
        second = self.source("last", [(1, 101, b"new", b"g" * 77, b"s" * 91),
                                      (2, 101, b"another", b"second gpu", b"second stream")])
        original = first[1].read_bytes()
        report = pack.merge_archives([first, second], self.root / "merged")
        toc = pack.read_checked(self.root / "merged/1111111111111111.patch_0")
        self.assertEqual(tuple(map(bytes, toc.GetEntry(1, 101).GetData())),
                         (b"new", b"g" * 77, b"s" * 91))
        self.assertEqual(bytes(toc.GetEntry(1, 102).TocData), b"other type")
        self.assertEqual(tuple(map(bytes, toc.GetEntry(2, 101).GetData())),
                         (b"another", b"second gpu", b"second stream"))
        self.assertEqual(first[1].read_bytes(), original)
        changes = report["archives"]["1111111111111111"]["overrides"]
        self.assertEqual(len(changes), 1)
        self.assertEqual((changes[0]["previous"], changes[0]["winner"]), ("first", "last"))
        self.assertEqual(toc.GetEntry(2, 101).GpuResourceOffset % 64, 0)
        self.assertEqual(toc.GetEntry(2, 101).StreamOffset % 64, 0)

    def test_different_archive_names_stay_separate(self):
        inputs = [self.source("a", [(1, 100, b"a", b"", b"")]),
                  self.source("b", [(1, 100, b"b", b"", b"")], base="2222222222222222")]
        report = pack.merge_archives(inputs, self.root / "merged")
        self.assertEqual(len(report["archives"]), 2)
        for base, expected in (("1111111111111111", b"a"), ("2222222222222222", b"b")):
            toc = pack.read_checked(self.root / "merged" / (base + ".patch_0"))
            self.assertEqual(bytes(toc.GetEntry(1, 100).TocData), expected)

    def test_layered_pack_preserves_att_skin_boundaries_and_order(self):
        att = self.source("ATT", [(1, 100, b"original unit", b"gpu A", b""),
                                  (99, 200, b"ATT script", b"", b"")])
        skin = self.source("skin", [(1, 100, b"Eagle unit", b"gpu B", b"stream B")])
        files = pack.layer_archives([att, skin], self.root / "Addon")
        self.assertEqual([v["archive"] for v in files],
                         ["1111111111111111.patch_0", "1111111111111111.patch_1"])
        for src, info in zip((att, skin), files):
            output = self.root / "Addon" / info["archive"]
            for suffix in ("", ".gpu_resources", ".stream"):
                self.assertEqual(Path(str(src[1]) + suffix).read_bytes(),
                                 Path(str(output) + suffix).read_bytes())
        # ATT can still identify its own archive separately from the skin.
        later = pack.read_checked(self.root / "Addon/1111111111111111.patch_1")
        self.assertIsNone(later.GetEntry(99, 200))

    def test_missing_or_truncated_required_sidecar_rejected_before_output(self):
        source = self.source("gpu", [(1, 100, b"x", b"graphics", b"stream")])
        gpu = Path(str(source[1]) + ".gpu_resources")
        for missing in (False, True):
            if missing:
                gpu.unlink()
            else:
                gpu.write_bytes(b"g")
            with self.assertRaisesRegex(ValueError, "sidecar"):
                pack.merge_archives([source], self.root / "merged")
            self.assertFalse((self.root / "merged").exists())

    def test_malformed_table_and_duplicate_output_refused(self):
        source = self.source("bad", [(1, 100, b"x", b"", b"")])
        good = source[1].read_bytes()
        for data in (b"", b"\0" * 72, good[:80], good[:4] + b"\xff" * 8 + good[12:]):
            source[1].write_bytes(data)
            with self.assertRaises(ValueError):
                pack.merge_archives([source], self.root / "merged")
        source[1].write_bytes(good)
        output = self.root / "merged"
        output.mkdir()
        sentinel = output / "keep.txt"
        sentinel.write_text("user file")
        with self.assertRaises(ValueError):
            pack.merge_archives([source], output)
        self.assertEqual(sentinel.read_text(), "user file")


if __name__ == "__main__":
    unittest.main()
