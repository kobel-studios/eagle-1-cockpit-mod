"""Focused tests for make_icon_patch.py: template geometry, xaml container
format, and that the patch only changes the StratagemBastion template."""
import os
import struct
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import make_icon_patch as mip

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUMP = os.path.join(HERE, 'xaml_dump', '7c6e2910b1a074a6.xaml')
PATCH = os.path.join(HERE, mip.OUT_PATCH)


def templates(xml_text):
    """Return {key: template_block} for every DataTemplate in the file."""
    out = {}
    for m in __import__('re').finditer(
            r'<DataTemplate x:Key="(\w+)">.*?</DataTemplate>', xml_text,
            __import__('re').S):
        out[m.group(1)] = m.group(0)
    return out


FAKE_XML = ('<ResourceDictionary>'
            '<DataTemplate x:Key="StratagemEagleAirstrike"><Viewbox>'
            '<Path Fill="#FF2B2B2B" Data="F1M0,0h256v256h-256z"/>'
            '<Path Fill="#FFCC5848" Data="M1,1L2,2Z"/>'
            '<Path Fill="#FFEDEDED" Data="M3,3L4,4Z"/>'
            '</Viewbox></DataTemplate>'
            '<DataTemplate x:Key="StratagemBastion"><Viewbox>'
            '<Path Fill="#FF2B2B2B" Data="F1M0,0h256v256h-256z"/>'
            '</Viewbox></DataTemplate>'
            '</ResourceDictionary>')


class TestRealArtTemplate(unittest.TestCase):
    def test_template_is_valid_xml(self):
        frag = mip.bastion_template(FAKE_XML)
        root = ET.fromstring(
            '<Root xmlns:x="http://schemas.microsoft.com/xaml/2006/xaml">'
            + frag + '</Root>')
        tpl = root.find('DataTemplate')
        self.assertIsNotNone(tpl)
        self.assertEqual('StratagemBastion',
                         tpl.get('{http://schemas.microsoft.com/xaml/2006/xaml}Key'))

    def test_template_lifts_eagle_jet_only_recolored_to_game_blue(self):
        frag = mip.bastion_template(FAKE_XML)
        self.assertIn(mip.GLYPH, frag)                # recolored to game blue
        self.assertIn(mip.BG, frag)                   # stock tile background
        self.assertNotIn(mip.EAGLE_RED, frag)         # every red path recolored
        self.assertNotIn('StratagemEagleAirstrike', frag)  # rekeyed, not copied
        self.assertIn('M1,1L2,2Z', frag)              # real eagle jet path carried over

    def test_white_bomb_path_removed(self):
        frag = mip.bastion_template(FAKE_XML)
        self.assertNotIn('#FFEDEDED', frag)           # no white accent paths
        self.assertNotIn('M3,3L4,4Z', frag)           # the bomb shape is gone

    def test_missing_eagle_template_raises(self):
        with self.assertRaises(RuntimeError):
            mip.bastion_template('<ResourceDictionary/>')


class TestXamlContainer(unittest.TestCase):
    def test_header_roundtrip(self):
        body = b'<ResourceDictionary/>'
        packed = mip.write_xaml(body)
        self.assertEqual(len(body), struct.unpack_from('<I', packed, 0)[0])
        self.assertEqual(bytes(12), packed[4:16])
        self.assertEqual(body, mip.read_xaml(packed))

    def test_read_uses_header_length(self):
        packed = mip.write_xaml(b'<a/>') + b'JUNK_TRAILING'
        self.assertEqual(b'<a/>', mip.read_xaml(packed))

    def test_read_rejects_short_header(self):
        for n in (0, 4, 15):
            with self.assertRaises(ValueError):
                mip.read_xaml(bytes(n))

    def test_read_rejects_oversized_declared_length(self):
        packed = struct.pack('<I', 100) + bytes(12) + b'<a/>'
        with self.assertRaises(ValueError):
            mip.read_xaml(packed)

    def test_read_rejects_truncated_body(self):
        packed = mip.write_xaml(b'<ResourceDictionary/>')[:18]
        with self.assertRaises(ValueError):
            mip.read_xaml(packed)


@unittest.skipUnless(os.path.exists(DUMP), 'icons xaml dump missing')
class TestAgainstRealDump(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DUMP, encoding='utf-8', errors='replace') as f:
            cls.xml = f.read()

    def test_bastion_matches_exactly_once(self):
        self.assertEqual(1, len(mip.TEMPLATE_RE.findall(self.xml)))

    def test_only_bastion_template_changes(self):
        before = templates(self.xml)
        new_xml, n = mip.TEMPLATE_RE.subn(mip.bastion_template(self.xml), self.xml)
        self.assertEqual(1, n)
        after = templates(new_xml)
        self.assertEqual(before.keys(), after.keys())
        for key, block in before.items():
            if key == 'StratagemBastion':
                self.assertNotEqual(block, after[key])
            else:
                self.assertEqual(block, after[key], key + ' changed')

    def test_patched_xml_parses(self):
        new_xml, _ = mip.TEMPLATE_RE.subn(mip.bastion_template(self.xml), self.xml)
        ET.fromstring(new_xml)  # raises if the patch broke well-formedness

    def test_trigger_binding_untouched(self):
        new_xml, _ = mip.TEMPLATE_RE.subn(mip.bastion_template(self.xml), self.xml)
        self.assertIn('Value="DropoffTank"', new_xml)
        self.assertIn('DynamicResource StratagemBastion', new_xml)


@unittest.skipUnless(os.path.exists(PATCH), 'patch_0 not built')
class TestBuiltPatch(unittest.TestCase):
    def test_patch_container(self):
        from hd2tool import load_sdk, init_game_data
        sdk = load_sdk()
        init_game_data(sdk)
        toc = sdk.StreamToc()
        self.assertTrue(toc.FromFile(PATCH, SerializeData=True))
        self.assertEqual(1, len(toc.TocEntries))
        e = toc.TocDict[mip.XAML_TYPE][mip.ICONS_XAML_ENTRY]
        xml = mip.read_xaml(bytes(e.TocData)).decode('utf-8')
        ET.fromstring(xml)
        self.assertIn(mip.GLYPH, xml)

    def test_binary_layout_matches_sdk_patch_format(self):
        """Same field layout as the deployed Eagle1 patch_0 (verified by
        compare_patch_layout.py): magic 0xf0000011, 72B header + 32B type
        records + 80B entry records, contiguous entry data, flags 16/64."""
        with open(PATCH, 'rb') as f:
            d = f.read()
        magic, ntypes, nfiles, _unk = struct.unpack_from('<4I', d, 0)
        self.assertEqual(0xF0000011, magic)
        self.assertEqual(1, ntypes)
        self.assertEqual(1, nfiles)
        # type record at 72: unk1, TypeID, NumFiles, unk2=16, unk3=64
        u1, tid, nf, u2, u3 = struct.unpack_from('<3Q2I', d, 72)
        self.assertEqual(mip.XAML_TYPE, tid)
        self.assertEqual(1, nf)
        self.assertEqual((16, 64), (u2, u3))
        # entry record at 104: offsets point at packed contiguous data
        (fid, etid, toc_off, strm_off, gpu_off, _u1, _u2,
         tsize, ssize, gsize, fu3, fu4, idx) = struct.unpack_from(
            '<5Q2Q3I3I', d, 104)
        self.assertEqual(mip.ICONS_XAML_ENTRY, fid)
        self.assertEqual(mip.XAML_TYPE, etid)
        self.assertEqual(184, toc_off)          # data right after headers
        self.assertGreaterEqual(len(d) - toc_off, tsize)
        self.assertEqual((0, 0), (ssize, gsize))  # xaml: no stream/gpu data
        self.assertEqual((16, 64, 1), (fu3, fu4, idx))


if __name__ == '__main__':
    unittest.main()
