"""Package the eagle_probe entry.lua into an Arsenal-style mod folder.

Produces EagleProbe/<archive>.patch_0 (+ empty sidecars) + manifest.json.
Read-only addon: logs the Lua environment to EagleProbe.log.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "hd2tools"))
import hd2_archive as A

WORK = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(WORK, "eagle_probe", "entry.lua")
OUTDIR = os.path.join(WORK, "EagleProbe")
ARCHIVE = "9ba626afa44a3aa3"
LUA_TYPE = 0xA14E8DFA2CD117E2
RESOURCE = b"mods/devin/eagle_probe"


def build_envelope(source: bytes) -> bytes:
    return struct.pack("<II", len(source), 2) + source


def main() -> None:
    source = open(ENTRY, "rb").read()
    first_line = source.split(b"\n", 1)[0]
    assert first_line == b"-- HD2-Addon: mods/devin/eagle_probe", first_line

    file_id = A.murmur64_hash(RESOURCE)
    entry = A.TocEntry()
    entry.FileID = file_id
    entry.TypeID = LUA_TYPE
    entry.SetData(bytearray(build_envelope(source)), bytearray(), bytearray())

    toc = A.StreamToc()
    toc.TocDict[LUA_TYPE] = {file_id: entry}

    os.makedirs(OUTDIR, exist_ok=True)
    patch_path = os.path.join(OUTDIR, ARCHIVE + ".patch_0")
    toc.ToFile(patch_path)
    for suffix in (".gpu_resources", ".stream"):
        open(patch_path + suffix, "wb").close()

    manifest = {
        "Version": 1,
        "Guid": "d1agno5t-1c-p10b-e000-eag1eprobe01".replace(" ", ""),
        "Name": "Eagle Probe (diagnostics)",
        "Description": "Read-only Lua environment probe. Writes EagleProbe.log "
                       "under CowboyBingus logs. Requires Bingus Shared Loader.",
        "Options": [],
    }
    with open(os.path.join(OUTDIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    # Parse the patch back and verify contents.
    back = A.StreamToc()
    assert back.FromFile(patch_path, SerializeData=True)
    got = bytes(back.TocDict[LUA_TYPE][file_id].TocData)
    want = build_envelope(source)
    assert got == want, "round-trip mismatch"
    body_len, ver = struct.unpack_from("<II", got)
    assert body_len == len(source) and ver == 2
    print("patch_0 written:", patch_path)
    print("FileID:", hex(file_id), "entries:", len(got), "bytes")
    print("first line:", got[8:got.index(b"\n")].decode())


if __name__ == "__main__":
    main()
