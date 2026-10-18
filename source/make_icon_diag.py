"""Diagnostic icon patch: recolors StratagemEagle500kgbomb to bright green.

Purpose: prove whether generated_icons/stratagem_icons.xaml is the live icon
source for the stratagem rows the user sees in game. Eagle 500kg is a
stratagem the user definitely equips; if its icon turns green after this
patch deploys, the dictionary IS live and the Maelstrom simply binds a
different enum than DropoffTank. If nothing changes, the row uses a
different icon path (atlas materials / code-resolved setter) and the whole
vector-dictionary approach needs retargeting.

Writes a separate patch file so the production patch stays unchanged.
"""
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hd2tool
import make_icon_patch as mip

OUT_PATCH = "007e093ca718ca1a.patch_1"
PROBE = "#FF44FF44"   # unmistakable bright green  - "is dictionary live?" probe
PROBE2 = "#FFFFA040"  # unmistakable bright orange - "is tank=DropoffCombatWalker?" probe

PROBES = [
    ("StratagemEagle500kgbomb", PROBE),
    ("StratagemVehicleCombatwalker", PROBE2),
]


def probe_template(key, color, canvas=256):
    paths = ['        <Path Fill="%s" Data="F1M0,0h%dv%dh-%dz" Stretch="Fill" '
             'Height="%d" Width="%d" Canvas.Left="0" Canvas.Top="0" />'
             % (mip.BG, canvas, canvas, canvas, canvas, canvas)]
    for fill, poly in mip.jet_polygons():
        fill = color if fill != mip.BG else fill
        paths.append('        <Path Data="%s" Fill="%s" />'
                     % (mip.path_data(poly, 0.5), fill))
    return ('<DataTemplate x:Key="%s">\n' % key
            + '    <Viewbox>\n'
            + '      <Canvas Width="%d" Height="%d">\n' % (canvas, canvas)
            + "\n".join(paths)
            + '\n      </Canvas>\n'
            '    </Viewbox>\n'
            '  </DataTemplate>')


def build_patch(sdk, out_dir):
    toc = sdk.StreamToc()
    if not toc.FromFile(mip.ICONS_PKG, SerializeData=True):
        raise RuntimeError("failed to parse icons package " + mip.ICONS_PKG)

    entry = toc.TocDict[mip.XAML_TYPE][mip.ICONS_XAML_ENTRY]
    xml = mip.read_xaml(bytes(entry.TocData))

    text = xml.decode("utf-8")
    new_xml, n = mip.TEMPLATE_RE.subn(mip.bastion_template(), text)
    if n != 1:
        raise RuntimeError(f"expected 1 StratagemBastion, replaced {n}")
    for key, color in PROBES:
        rx = re.compile(
            r'<DataTemplate x:Key="%s">.*?</DataTemplate>' % key, re.S)
        new_xml, n = rx.subn(probe_template(key, color), new_xml)
        if n != 1:
            raise RuntimeError(f"expected 1 {key}, replaced {n}")
    new_toc_data = mip.write_xaml(new_xml.encode("utf-8"))

    patch = sdk.StreamToc()
    patch.magic = toc.magic
    patch.unknown = toc.unknown
    patch.unk4Data = bytearray(toc.unk4Data)
    entry.TocData = bytearray(new_toc_data)
    entry.TocDataSize = len(new_toc_data)
    entry.GpuData = bytearray()
    entry.GpuResourceSize = 0
    entry.StreamData = bytearray()
    entry.StreamSize = 0
    patch.TocDict = {mip.XAML_TYPE: {mip.ICONS_XAML_ENTRY: entry}}
    patch.UpdateTypes()
    patch.UpdatePath(os.path.join(out_dir, OUT_PATCH))
    patch.ToFile()
    return patch


def verify(sdk, out_dir):
    check = sdk.StreamToc()
    assert check.FromFile(os.path.join(out_dir, OUT_PATCH), SerializeData=True)
    e = check.TocDict[mip.XAML_TYPE][mip.ICONS_XAML_ENTRY]
    xml = mip.read_xaml(bytes(e.TocData))
    assert PROBE.encode() in xml, "green probe fill missing"
    assert PROBE2.encode() in xml, "orange probe fill missing"
    assert mip.GLYPH.encode() in xml, "blue jet missing"
    print("diag patch verified:", len(e.TocData), "bytes")


def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))
    sdk = hd2tool.load_sdk()
    hd2tool.init_game_data(sdk)
    build_patch(sdk, out_dir)
    verify(sdk, out_dir)
    print("wrote", os.path.join(out_dir, OUT_PATCH))


if __name__ == "__main__":
    sys.exit(main())
