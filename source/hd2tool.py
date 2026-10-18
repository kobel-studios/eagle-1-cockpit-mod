"""
hd2tool.py - standalone Helldivers 2 stingray archive reader.

Wraps the HD2SDK-CommunityEdition classes (StreamToc / TocManager / slim.py)
outside of Blender by installing stub modules for bpy/bmesh/mathutils.

Usage:
    python hd2tool.py                          # list entries in base archive
    python hd2tool.py <archive_name_or_path>   # list entries in that archive
    python hd2tool.py <archive> --data         # also read entry data (slow)
    python hd2tool.py --selftest               # validate stubs + parse patch_0

Work dir: C:\\Users\\jacks\\HQ\\downloads\\hd2-mods
SDK copy: hd2sdk_pkg
Game data: b:\\all da games baby\\steamapps\\common\\Helldivers 2\\data
"""

import json
import os
import sys
import types

WORKDIR = os.path.dirname(os.path.abspath(__file__))
SDK_DIR = os.path.join(WORKDIR, "hd2sdk_pkg")
GAME_DATA = r"b:\all da games baby\steamapps\common\Helldivers 2\data"
BASE_ARCHIVE = "9ba626afa44a3aa3"


# --------------------------------------------------------------------------
# Blender stubs
# --------------------------------------------------------------------------
class _AnyMeta(type):
    def __getattr__(cls, name):
        return _Any

    def __call__(cls, *a, **k):
        return type.__call__(cls, *a, **k)

    def __iter__(cls):
        return iter(())

    def __getitem__(cls, k):
        return _Any()


class _Any(metaclass=_AnyMeta):
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        return _Any

    def __call__(self, *a, **k):
        return _Any()

    def __getitem__(self, k):
        return _Any()

    def __iter__(self):
        return iter(())

    def __bool__(self):
        return False

    def __len__(self):
        return 0

    def __int__(self):
        return 0

    def __index__(self):
        return 0

    def __float__(self):
        return 0.0

    def __repr__(self):
        return "<blender-stub>"


class _BpyApp(_Any):
    # slim.py picks the bundled lz4 build from bpy.app.version.
    # Python 3.10 -> Blender 4.0 -> lz4_310
    version = (4, 0)
    version_file = (4, 0, 0)
    version_string = "4.0.0"


class _StubModule(types.ModuleType):
    """Module whose attributes are unique _Any subclasses.

    Uniqueness matters: 'class X(bpy.types.Operator, ExportHelper)' needs
    Operator and ExportHelper to be different classes.
    """

    def __init__(self, name):
        super().__init__(name)
        self.__attr_cache = {}

    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        cls = self.__attr_cache.get(name)
        if cls is None:
            cls = _AnyMeta(name, (_Any,), {})
            self.__attr_cache[name] = cls
        return cls


def install_stubs():
    bpy = _StubModule("bpy")
    bpy.app = _BpyApp()
    sys.modules["bpy"] = bpy
    for sub in (
        "types", "props", "utils", "ops", "data", "context", "msgbus",
        "path", "app", "blf",
    ):
        sys.modules[f"bpy.{sub}"] = _StubModule(f"bpy.{sub}")
    for name in (
        "bpy_extras", "bpy_extras.anim_utils", "bpy_extras.io_utils",
        "bpy_extras.mesh_helpers", "bmesh", "mathutils",
    ):
        sys.modules[name] = _StubModule(name)
    return bpy


# --------------------------------------------------------------------------
# SDK bootstrap
# --------------------------------------------------------------------------
_sdk = None


def load_sdk():
    global _sdk
    if _sdk is not None:
        return _sdk
    install_stubs()
    if WORKDIR not in sys.path:
        sys.path.insert(0, WORKDIR)
    import hd2sdk_pkg as sdk  # noqa: E402

    sdk.Global_gamepath = GAME_DATA
    sdk.Global_gamepathIsValid = True
    _sdk = sdk
    return sdk


def init_game_data(sdk, game_data=GAME_DATA):
    """Point the SDK at the game data folder and build the bundle map."""
    sdk.Global_gamepath = game_data
    sdk.Global_gamepathIsValid = True
    from hd2sdk_pkg.utils import slim

    slim.slim_init(game_data)  # detects slim version + maps bundles.nxa


def friendly_name_map(sdk):
    """FileID -> friendly name from hashlists/friendlynames.txt."""
    names = {}
    try:
        sdk.LoadNameHashes()
        names = {int(h[0]): h[1] for h in sdk.Global_NameHashes}
    except Exception as e:
        print(f"[hd2tool] friendly names unavailable: {e}")
    return names


def type_name_map(sdk):
    """TypeID -> type name from hashlists/typehash.txt."""
    names = {}
    try:
        sdk.LoadTypeHashes()
        names = {int(h[0]): h[1] for h in sdk.Global_TypeHashes}
    except Exception as e:
        print(f"[hd2tool] type names unavailable: {e}")
    return names


def list_archive(archive_ref, serialize_data=False, game_data=GAME_DATA,
                 dump_json=None):
    """Parse an archive and return {type_id: [file_ids]}.

    archive_ref: bare package name looked up in the bundle map, or a path
                 to an on-disk legacy/package file.
    """
    sdk = load_sdk()
    init_game_data(sdk, game_data)

    toc = sdk.StreamToc()
    ok = toc.FromFile(archive_ref, SerializeData=serialize_data)
    if not ok:
        raise RuntimeError(f"StreamToc failed to parse {archive_ref}")

    fnames = friendly_name_map(sdk)
    tnames = type_name_map(sdk)

    listing = {}
    for type_id, entries in sorted(toc.TocDict.items()):
        file_ids = sorted(entries.keys())
        listing[type_id] = file_ids
        tlabel = tnames.get(type_id, "")
        print(f"type 0x{type_id:016x} {tlabel:<24} {len(file_ids)} entries")

    out = {
        "archive": archive_ref,
        "types": {
            f"0x{t:016x}": {
                "name": tnames.get(t, ""),
                "entries": {
                    str(f): fnames.get(f, "")
                    for f in ids
                },
            }
            for t, ids in listing.items()
        },
    }
    if dump_json:
        with open(dump_json, "w") as f:
            json.dump(out, f, indent=1)
        print(f"[hd2tool] wrote {dump_json}")
    return listing, out


TEX_HEADER_OFFSET = 12 + 15 * 12  # unk ids + 15 StingrayMipmapInfo


def texture_dims(entry):
    """Parse a texture TocEntry's embedded DDS header.

    Returns (width, height, dxgi_format_int, array_size) or None.
    """
    data = entry.TocData
    if len(data) < TEX_HEADER_OFFSET + 148:
        return None
    import struct
    base = TEX_HEADER_OFFSET
    h, w = struct.unpack_from("<II", data, base + 12)
    fmt, = struct.unpack_from("<I", data, base + 128)
    arr, = struct.unpack_from("<I", data, base + 140)
    return (w, h, fmt, arr)


def dump_texture_dds(entry, out_dir):
    """Write a texture entry's data as a .dds file (header + raw mips)."""
    data = entry.TocData
    if len(data) < TEX_HEADER_OFFSET + 148:
        return None
    header = bytes(data[TEX_HEADER_OFFSET:TEX_HEADER_OFFSET + 148])
    raw = bytes(entry.StreamData) if len(entry.StreamData) else bytes(entry.GpuData)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{entry.FileID:x}.dds")
    with open(path, "wb") as f:
        f.write(header + raw)
    return path


def print_matches(listing, out, needles):
    """Print entries whose friendly name contains any needle (case-insens)."""
    print("\n-- friendly-name matches --")
    for t_hex, info in out["types"].items():
        for fid, name in info["entries"].items():
            if name and any(n.lower() in name.lower() for n in needles):
                print(f"{t_hex} {fid} {name}")


def selftest():
    """Validate stubs + parse a real on-disk patch archive."""
    sdk = load_sdk()
    print("[hd2tool] sdk import OK")

    patch = os.path.join(GAME_DATA, "9ba626afa44a3aa3.patch_0")
    assert os.path.exists(patch), f"missing test archive {patch}"

    init_game_data(sdk)
    toc = sdk.StreamToc()
    assert toc.FromFile(patch, SerializeData=False), "patch_0 parse failed"
    total = sum(len(v) for v in toc.TocDict.values())
    assert total > 0, "no entries parsed"
    assert toc.magic == 4026531857, f"bad magic {toc.magic}"
    print(f"[hd2tool] patch_0: {total} entries across "
          f"{len(toc.TocDict)} types - OK")
    return True


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}

    if "--selftest" in flags:
        selftest()
        sys.exit(0)

    archive = args[0] if args else BASE_ARCHIVE
    want_data = "--data" in flags
    json_out = os.path.join(
        WORKDIR, f"archive_{os.path.basename(archive)}_entries.json")
    listing, out = list_archive(archive, serialize_data=want_data,
                                dump_json=json_out)
    print_matches(listing, out,
                  ["maelstrom", "eagle", "stratagem", "vehicle", "icon",
                   "camera", "cockpit"])
