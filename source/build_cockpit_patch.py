"""Build a local VFC camera-delegation experiment; never deploy or run it.

Requires the user's exact Vehicle Flight Control 1.0.1 Lua resource.
Only the camera-writing function is changed. Flight movement, flight/address
gates, host/seat checks, and cleanup code remain byte-for-byte intact.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "hd2tools"))
sys.path.insert(0, str(ROOT / "vfc_inspect"))
import hd2_archive as archive
import inspect_lj

SOURCE_SHA256 = "abc28461aecb613afa24cb5662feef1cf97c9cd2ea82e332cb4567fb0ba93fb2"
LUA_TYPE = 0xA14E8DFA2CD117E2
RESOURCE_NAME = "mods/codex/vehicle_flight"
RESOURCE_ID = 12970356483147164383
GUID = "ab464d73-2b5a-4894-9b46-e0754fa28673"

README = """Eagle Cockpit Camera Experiment 0.2

NOT YET TESTED IN GAME. This package does not add bombs or rearming.

This local derivative of Vehicle Flight Control 1.0.1 changes just the entry
instruction of its camera-writing function to return immediately, skipping its
camera-only checks and writes. The existing
Advanced Vehicle Pack camera can then own the camera without VFC overwriting
it each frame. Flight, seat checks, native validation, and cleanup are retained.

Dependencies: Eagle1 Maelstrom v5, Advanced Vehicle Pack 1.1.1 (ATH and ATT),
and Bingus Shared Loader v18. The original flight mod may remain installed;
this package must win its resource conflict. Keep Bingus Shared Loader last.
Do not enable Tank Seat Kit with this combination.

Configure AdvancedTankCamera.ini [camera] distance=25, look_low=-85,
look_high=85 and [vehicles]
distance=25; keep [first_person] enabled=1 and below=30. Existing
[seat_distance] overrides also need 25. The actual cockpit position may need
eye_height/eye_forward tuning for the Eagle model. First-person only applies
to gunner camera template 26; other seats may remain third person. This is
unverified in game.

Exit the game normally before deployment. Import through Arsenal, enable,
then deploy. Restart and test solo/host. Enter the gunner/pilot seat, press I,
and check camera placement and steering. Existing gun controls remain those
of Advanced Vehicle Pack. VFC's own camera height/zoom controls no longer
apply; camera controls belong to Advanced Vehicle Pack.

A small read-only addon logs the existing mods' status to
%LOCALAPPDATA%/CowboyBingus/Helldivers2/Logs/EagleCameraDiagnostics.log.
It helps verify the active seat camera template and flight state.

Rollback: disable this package in Arsenal and redeploy. Restore the saved
camera configuration if you applied one. The original VFC file is untouched.

Only one four-byte bytecode instruction is replaced, with a strict input
SHA256 check. This is static validation, not a claim of runtime compatibility.
Do not redistribute the included third-party mod without checking its license.
"""


def patch_resource(data):
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("unsupported VFC resource: exact 1.0.1 input required")
    size, version = struct.unpack_from("<II", data)
    if version != 2 or size != len(data) - 8:
        raise ValueError("invalid Lua resource envelope")
    raw = inspect_lj.unwrap(data)
    protos = inspect_lj.parse(raw)
    p = protos[46]
    if (len(protos) != 103 or p["params"] != 1
            or p["constants"][0] != "t_max"
            or p["constants"][24] != "camera_fix"
            or p["instructions"][0] != 15):
        raise ValueError("camera function no longer matches")
    r = inspect_lj.Reader(raw)
    r.pos = p["offset"]
    r.take(4)
    for _ in range(3):
        r.uleb()
    offset = r.pos
    modified = bytearray(raw)
    struct.pack_into("<I", modified, offset, 0x0001004B)  # RET0, no results

    # Second tweak: hover_hold True->False in the compiled-in defaults table.
    # Serialized as the ten-byte string key plus a one-byte tag (2=True,
    # 1=False). Off means the vehicle sinks under gravity when the controls
    # are released - it can still fly, it just stops hovering in midair.
    needle = b"\x0fhover_hold\x02"
    hits = [i for i in range(len(modified))
            if bytes(modified[i:i + len(needle)]) == needle]
    if len(hits) != 1:
        raise ValueError("hover_hold value tag is not unique")
    hover_offset = hits[0] + len(needle) - 1
    modified[hover_offset] = 1  # True tag -> False tag

    # Third tweak: orphan the takeoff-time zhold write. VFC latches zhold to
    # the takeoff altitude unconditionally, and its physics clamps position
    # and floors vertical thrust whenever zhold is set. hover_hold=False only
    # skips the re-arm path, so the latched value can still pin the craft.
    # Renaming proto 54's write key to "xhold" makes the init a dead write;
    # the physics proto (55) keeps its own "zhold" constant and always reads
    # nil. Occurrence[0] is proto 54's instruction key; [1] is the state
    # table template field and [2] lives in proto 55 - both stay untouched.
    zhits = [i for i in range(len(modified))
             if bytes(modified[i:i + 6]) == b"\x0azhold"]
    if len(zhits) != 3:
        raise ValueError("expected three zhold constants, found %d" % len(zhits))
    zhold_offset = zhits[0] + 1
    modified[zhold_offset] = ord("x")  # 'z' -> 'x'

    # Fourth tweak: tau_idle 2 -> 5 in the defaults table. The idle velocity
    # correction is a proportional pull toward zero; a longer time constant
    # lets the craft glide on release instead of dead-stopping in midair.
    thits = [i for i in range(len(modified))
             if bytes(modified[i:i + len(TAU_NEEDLE)]) == TAU_NEEDLE]
    if len(thits) != 1:
        raise ValueError("tau_idle value is not unique")
    modified[thits[0] + len(TAU_NEEDLE) - 1] = NEW_TAU_IDLE

    # Fifth tweak: gravity 9.81 -> 19.62 in the same table. LuaJIT stores a
    # table-constant double as two uleb128 halves (lo32 then hi32); the new
    # value was chosen so the encoding keeps the same 10-byte length.
    ghits = [i for i in range(len(modified))
             if bytes(modified[i:i + len(GRAVITY_NEEDLE)]) == GRAVITY_NEEDLE]
    if len(ghits) != 1:
        raise ValueError("gravity double is not unique")
    goff = ghits[0] + len(b"\x0cgravity\x04")
    modified[goff:goff + len(NEW_GRAVITY_ENC)] = NEW_GRAVITY_ENC

    after = inspect_lj.parse(bytes(modified))
    expected = list(p["instructions"])
    expected[0] = 0x0001004B
    seen = {"hover_hold": 0, "gravity": 0, "tau_idle": 0, "xhold": 0}
    for before_p, after_p in zip(protos, after):
        if before_p["id"] == 46:
            comparable = dict(before_p, instructions=expected)
            if after_p != comparable:
                raise ValueError("unexpected camera mutation")
        elif before_p == after_p:
            continue
        else:
            if len(before_p["constants"]) != len(after_p["constants"]):
                raise ValueError("unexpected non-camera mutation")
            for index, (before_c, after_c) in enumerate(
                    zip(before_p["constants"], after_p["constants"])):
                if before_c == after_c:
                    continue
                wanted, fields = _expected_constant(before_c, before_p["id"],
                                                    index)
                if after_c != wanted:
                    raise ValueError("unexpected non-camera mutation")
                for field in fields:
                    seen[field] += 1
    if seen != {"hover_hold": 1, "gravity": 1, "tau_idle": 1, "xhold": 1}:
        raise ValueError("expected one of each table tweak, saw %r" % seen)

    match = re.search(rb'local _c\s*=\s*"((?:\\[0-9]{3})*)"', data)
    if match is None:
        raise ValueError("unsupported Lua wrapper")
    escaped = "".join("\\%03d" % n for n in modified).encode("ascii")
    result = data[:match.start(1)] + escaped + data[match.end(1):]
    if len(result) != len(data):
        raise ValueError("resource size changed unexpectedly")
    return result, offset, hover_offset, zhold_offset, thits[0], ghits[0]


def _uleb(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | 0x80 if value else byte)
        if not value:
            return bytes(out)


TAU_NEEDLE = b"\x0dtau_idle\x03\x02"
NEW_TAU_IDLE = 5
NEW_GRAVITY = 19.62
_gravity_bits = struct.unpack("<Q", struct.pack("<d", NEW_GRAVITY))[0]
NEW_GRAVITY_ENC = (_uleb(_gravity_bits & 0xFFFFFFFF)
                   + _uleb(_gravity_bits >> 32))
GRAVITY_NEEDLE = (b"\x0cgravity\x04"
                  + bytes.fromhex("9f8aae8f05b8bd8e8104"))
assert len(NEW_GRAVITY_ENC) == 10  # must match the 9.81 encoding length


def _expected_constant(before, proto_id, index):
    """Return (expected_value, changed_field_names) for one constant. A dict
    is a serialized table constant; the bare "zhold" rename is only legal
    inside takeoff proto 54, where its TSETS key becomes a dead write."""
    if before == "zhold":
        if proto_id != 54:
            raise ValueError("zhold constant changed outside takeoff proto")
        return "xhold", ["xhold"]
    if isinstance(before, dict) and isinstance(before.get("hash"), list):
        wanted = dict(before)
        wanted["hash"] = [list(pair) for pair in before["hash"]]
        fields = []
        allowed = {"hover_hold": (True, False), "gravity": (9.81, NEW_GRAVITY),
                   "tau_idle": (2, NEW_TAU_IDLE)}
        for pair in wanted["hash"]:
            if pair[0] in allowed and pair[1] != allowed[pair[0]][0]:
                raise ValueError("unexpected %s start value %r"
                                 % (pair[0], pair[1]))
            if pair[0] in allowed:
                pair[1] = allowed[pair[0]][1]
                fields.append(pair[0])
        if not fields:
            raise ValueError("non-whitelisted table constant change")
        return wanted, fields
    raise ValueError("non-whitelisted constant change: %r" % (before,))


def camera_config(text):
    """Prepare a reviewed INI in memory, preserving unrelated values/comments."""
    section = ""
    changed = []
    output = []
    for line in text.splitlines(keepends=True):
        header = re.match(r"\s*\[([^]]+)\]", line)
        if header:
            section = header[1].lower()
        match = re.match(r"(\s*([^;#=\s]+)\s*=\s*)([-+]?\d+(?:\.\d+)?)(.*)", line)
        target = None
        if match:
            key = match[2].lower()
            if section in ("camera", "vehicles") and key == "distance":
                target = "25"
            elif section == "camera" and key == "look_low":
                target = "-85"
            elif section == "camera" and key == "look_high":
                target = "85"
            elif section == "first_person" and key == "enabled":
                target = "1"
            elif section == "first_person" and key == "below":
                target = "30"
            elif section == "seat_distance":
                target = "25"
        if target is not None:
            line = line[:match.start(3)] + target + line[match.end(3):]
            changed.append((section, match[2]))
        output.append(line)
    required = {("camera", "distance"), ("vehicles", "distance"),
                ("first_person", "enabled"), ("first_person", "below")}
    if not required.issubset({(s, k.lower()) for s, k in changed}):
        raise ValueError("missing expected Advanced Tank Camera settings")
    return "".join(output)


def encode_lua_archive(resources):
    """Encode the BSL authoring layout, including aligned payloads/header size.

    Layout checked against BingusSharedLoader/scripts/archive.py. The generic
    SDK writer uses different metadata/alignment; matching the loader's known
    Lua packaging format avoids relying on its tolerance for those differences.
    """
    if not resources:
        raise ValueError("at least one Lua resource required")
    count = len(resources)
    offset = (104 + 80 * count + 15) & ~15
    data, entries = bytearray(offset), bytearray()
    for index, (resource_id, payload) in enumerate(sorted(resources.items())):
        entries += struct.pack("<7Q6I", resource_id, LUA_TYPE, offset, 0, 0, 0, 0,
                               len(payload), 0, 0, 16, 16, index)
        data += payload
        data += b"\0" * (-len(data) % 16)
        offset = len(data)
    header = struct.pack("<III20sQQ24s", 0xF0000011, 1, count, b"", len(data), 0, b"")
    type_record = struct.pack("<IIQIIII", 0, 0, LUA_TYPE, count, 0, 16, 16)
    data[:104 + len(entries)] = header + type_record + entries
    return bytes(data)


def build(source, output):
    data = Path(source).read_bytes()
    patched, offset, hover_offset, zhold_offset, tau_offset, gravity_offset = \
        patch_resource(data)
    output = Path(output)
    if not output.parent.is_dir():
        raise ValueError("output parent must already exist")
    if output.exists():
        raise FileExistsError(output)
    manifest = {
        "Version": 1, "Guid": GUID, "Name": "Eagle Cockpit Camera Experiment 0.4",
        "Description": "Unverified cockpit camera compatibility and flight-feel "
                       "patch for Vehicle Flight Control 1.0.1 and Advanced "
                       "Vehicle Pack 1.1.1. Removes the altitude-hold latch "
                       "(hover_hold off and the takeoff zhold latch orphaned), "
                       "weakens the idle stop so the craft glides, and doubles "
                       "gravity for a heavier plane feel. No new bombs or "
                       "rearm feature. Requires BSL.",
        "Options": [{"Name": "Delegate flight camera to Advanced Vehicle Pack",
                     "Description": "Disable VFC camera writes; retain flying. "
                                    "Needs first-person camera configuration.",
                     "Include": ["Addon"]}],
    }
    report = dict(source_sha256=SOURCE_SHA256,
                  patched_sha256=hashlib.sha256(patched).hexdigest(),
                  resource=RESOURCE_NAME, prototype=46,
                  instruction=1, bytecode_offset=offset,
                  before="ISF A=0 D=0", after="RET0",
                  hover_hold=dict(bytecode_offset=hover_offset,
                                  before="True tag (2)", after="False tag (1)"),
                  zhold_init=dict(bytecode_offset=zhold_offset,
                                  before="zhold write key",
                                  after="xhold (dead write)"),
                  tau_idle=dict(bytecode_offset=tau_offset,
                                before=2, after=NEW_TAU_IDLE),
                  gravity=dict(bytecode_offset=gravity_offset,
                               before=9.81, after=NEW_GRAVITY),
                  game_tested=False, bombs_connected=False)
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        patch = Path(tmp) / "9ba626afa44a3aa3.patch_0"
        diagnostic = (ROOT / "eagle_camera_diagnostics.lua").read_bytes()
        diagnostic_name = "mods/jacks/eagle_camera_diagnostics"
        if not diagnostic.startswith(("-- HD2-Addon: " + diagnostic_name + "\n").encode()):
            raise ValueError("diagnostic declaration mismatch")
        diagnostic_id = archive.murmur64_hash(diagnostic_name.encode())
        patch.write_bytes(encode_lua_archive({
            RESOURCE_ID: patched,
            diagnostic_id: struct.pack("<II", len(diagnostic), 2) + diagnostic,
        }))
        for suffix in (".gpu_resources", ".stream"):
            Path(str(patch) + suffix).write_bytes(b"")
        check = archive.StreamToc()
        if not check.FromFile(str(patch)):
            raise ValueError("archive roundtrip failed")
        if bytes(check.GetEntry(RESOURCE_ID, LUA_TYPE).TocData) != patched:
            raise ValueError("archive content differs")
        with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(manifest, indent=2))
            z.writestr("README.txt", README)
            z.writestr("validation.json", json.dumps(report, indent=2))
            for f in sorted(Path(tmp).iterdir()):
                z.write(f, "Addon/" + f.name)
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", type=Path)
    ap.add_argument("output", type=Path)
    args = ap.parse_args()
    print(json.dumps(build(args.source, args.output), indent=2))
