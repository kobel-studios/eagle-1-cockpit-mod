"""Build an icon patch for the Maelstrom/Eagle-1 cockpit mod.

Replaces the vector contents of the "StratagemBastion" DataTemplate inside
generated_icons/stratagem_icons.xaml (entry 7c6e2910b1a074a6, XamlID,
package 007e093ca718ca1a) with the REAL StratagemEagle500kgbomb vector art
from the same file, recolored from Eagle red to the game's own vehicle blue
(#FF45ACC8). The patch is written to the work directory only; installing it
is up to the Arsenal packaging step.
"""
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hd2tool

XAML_TYPE = 0x46BC82AAE9AE0565  # XamlID from typehash.txt
ICONS_PKG = "007e093ca718ca1a"
ICONS_XAML_ENTRY = 0x7C6E2910B1A074A6
OUT_PATCH = "007e093ca718ca1a.patch_0"

# Colors: stock stratagem panel + the game's own palette.
BG = "#FF2B2B2B"        # stock tile background
GLYPH = "#FF45ACC8"     # game vehicle/supply blue (same as StratagemBastion)
EAGLE_RED = "#FFCC5848"  # red used by real Eagle stratagem icons
WHITE = "#FFEDEDED"     # white accent paths (the bomb in the 500kg icon)

TEMPLATE_RE = re.compile(
    r'<DataTemplate x:Key="StratagemBastion">.*?</DataTemplate>', re.S)
EAGLE_RE = re.compile(
    r'<DataTemplate x:Key="StratagemEagleAirstrike">.*?</DataTemplate>', re.S)
WHITE_PATH_RE = re.compile(
    r'<Path\b[^>]*Fill="#FFEDEDED"[^>]*/>\s*')


def bastion_template(xml_text):
    """The replacement StratagemBastion DataTemplate: the REAL
    StratagemEagleAirstrike jet (white munition paths removed) recolored
    from Eagle red to the game's own vehicle blue."""
    m = EAGLE_RE.search(xml_text)
    if not m:
        raise RuntimeError("StratagemEagleAirstrike template not found")
    body = m.group(0).replace(
        'x:Key="StratagemEagleAirstrike"', 'x:Key="StratagemBastion"', 1)
    body = WHITE_PATH_RE.sub("", body)
    return body.replace(EAGLE_RED, GLYPH)


def read_xaml(toc_data: bytes) -> bytes:
    """XAML entry TocData = u32 body length, pad to 16, then xml bytes."""
    if len(toc_data) < 16:
        raise ValueError("xaml entry too short: %d bytes" % len(toc_data))
    (length,) = struct.unpack_from("<I", toc_data, 0)
    if length > len(toc_data) - 16:
        raise ValueError("xaml declared length %d exceeds %d available bytes"
                         % (length, len(toc_data) - 16))
    return bytes(toc_data[16:16 + length])


def write_xaml(xml: bytes) -> bytes:
    return struct.pack("<I", len(xml)) + bytes(12) + xml


def build_patch(sdk, out_dir):
    toc = sdk.StreamToc()
    if not toc.FromFile(ICONS_PKG, SerializeData=True):
        raise RuntimeError("failed to parse icons package " + ICONS_PKG)

    entry = toc.TocDict[XAML_TYPE][ICONS_XAML_ENTRY]
    xml = read_xaml(bytes(entry.TocData))
    if b'StratagemBastion' not in xml:
        raise RuntimeError("StratagemBastion template not found in icons xaml")

    text = xml.decode("utf-8")
    new_xml, n = TEMPLATE_RE.subn(bastion_template(text), text)
    if n != 1:
        raise RuntimeError(f"expected 1 StratagemBastion template, replaced {n}")
    new_toc_data = write_xaml(new_xml.encode("utf-8"))

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
    patch.TocDict = {XAML_TYPE: {ICONS_XAML_ENTRY: entry}}
    patch.UpdateTypes()
    patch.UpdatePath(os.path.join(out_dir, OUT_PATCH))
    patch.ToFile()
    return patch


def verify(sdk, out_dir):
    """Re-parse the patch and confirm the new template landed."""
    check = sdk.StreamToc()
    assert check.FromFile(os.path.join(out_dir, OUT_PATCH), SerializeData=True)
    e = check.TocDict[XAML_TYPE][ICONS_XAML_ENTRY]
    xml = read_xaml(bytes(e.TocData))
    assert GLYPH.encode() in xml, "blue glyph fill missing in patched xaml"
    assert b"StratagemBastion" in xml
    print("patch verified:", len(e.TocData), "bytes toc data")


def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))
    sdk = hd2tool.load_sdk()
    hd2tool.init_game_data(sdk)
    build_patch(sdk, out_dir)
    verify(sdk, out_dir)
    print("wrote", os.path.join(out_dir, OUT_PATCH))


if __name__ == "__main__":
    sys.exit(main())
