"""Package our Eagle payload modules; HD2Runtime remains a separate dependency."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_cockpit_patch import encode_lua_archive, archive

ROOT = Path(__file__).resolve().parent
GUID = "589ee7e6-dd4a-40f2-85d7-4a76b5aa0909"
ENTRY = "mods/jacks/eagle_payload"
SOURCES = {
    ENTRY: "eagle_payload_entry.lua",
    "mods/jacks/eagle_payload_core": "eagle_payload.lua",
    "mods/jacks/eagle_service_point": "eagle_service_point.lua",
    "mods/jacks/eagle_runtime_adapter": "runtime_adapter/eagle_runtime_adapter.lua",
    "mods/jacks/eagle_camera_scope": "eagle_camera_scope.lua",
}
README = """Eagle Payload Experiment 0.3

EXPERIMENTAL: offline tests passed; not yet tested in Helldivers 2.

Requires HD2Runtime 0.40.0 by SkyeShade, Bingus Shared Loader v18, Vehicle
Flight Control 1.0.1, Advanced Vehicle Pack 1.1.1 (ATH + ATT), and Eagle1
Maelstrom v5. Keep Tank Seat Kit disabled. Use the gunner/pilot seat.
Use the separate Eagle Cockpit Camera Experiment for camera compatibility.

Controls (also listed under the game's MODS keybindings):
  X       Select the next Eagle weapon (cycles).
  1-7     Jump straight to a weapon slot.
  B       Release the selected weapon while flight mode is on.
  Home    Call a rearm run while landed and stationary (flight mode OFF).

Seven weapons per vehicle load, each with its own reserve:
  500 KG x2, AIRSTRIKE x3, CLUSTER x4, NAPALM x3, ROCKETS x8, GAS x2, SMOKE x4.
Hold B and only one is released. A second release needs a fresh press at
least one second later, and the interval is shared across weapons. Counters
survive leaving and re-entering the seat. A failed request preserves
ammunition; an uncertain result locks further releases for that mission to
avoid duplicate projectiles.

The rearm run needs no marked service point. Land (flight mode off), hold
still, and press Home. Remain landed and stationary for 60 seconds to refill
EVERY weapon. Taking off, moving, leaving the seat, pausing updates or
losing focus cancels the run without refilling. There is no physical
ground-contact sensor; the run uses flight-mode state and measured speed.

The adapter pins Runtime 0.40.0/API 1 and the installed VFC revision. It checks
the game build, mission host, player life, fresh flight status, control role 4,
camera template 26, and native vehicle identity before a request. Other seat
roles or camera templates are refused rather than guessed. It preloads the
assets of all seven supported stratagems once per mission.

Uses HD2Runtime's documented DEVELOPMENT API to clone unchanged vanilla Eagle
projectiles. Their nominal speed, fuse, visual and damage are not verified
with this aircraft. Releases happen four world metres below the vehicle root,
not from a measured hardpoint, and do not inherit aircraft momentum. The
dependency preserves its own build/asset/host guards. Queued asset waits are
cancelled so a projectile cannot release later unexpectedly.

Existing Maelstrom weapons are still provided by Advanced Vehicle Pack.
Super Destroyer docking is not implemented.

Deployment: import through HD2 Arsenal; enable the dependencies and this mod.
BSL must win its startup-resource conflict. Quit the game before deploying
and restart. Start with solo play and a clear area. A requested action in the
log proves only that the engine accepted the call, not its damage or visuals.
The overlay shows ammo/status; HD2Runtime logs refusals and requests.

Rollback: disable this mod and redeploy after exiting the game. Disable the
camera experiment and restore its saved INI separately if reverting the camera.

CREDIT: HD2Runtime by SkyeShade
https://github.com/SkyeShade/HD2Runtime
This archive contains only our addon source, not the Runtime or its native
address tables. Keep this credit when sharing code; follow upstream terms.
"""


def build(output):
    output = Path(output)
    if not output.parent.is_dir():
        raise ValueError("output parent must already exist")
    resources, hashes = {}, {}
    for name, relative in SOURCES.items():
        data = (ROOT / relative).read_bytes()
        data.decode("utf-8")
        if b"\0" in data:
            raise ValueError("source must be plain UTF-8 Lua")
        if name == ENTRY and not data.startswith(("-- HD2-Addon: " + name + "\n").encode()):
            raise ValueError("entry declaration mismatch")
        resources[archive.murmur64_hash(name.encode())] = struct.pack("<II", len(data), 2) + data
        hashes[name] = hashlib.sha256(data).hexdigest()
    manifest = {
        "Version": 1, "Guid": GUID, "Name": "Eagle Payload Experiment 0.3",
        "Description": "Experimental seven-weapon Eagle payload with 60-second "
                       "landed rearm runs. Requires HD2Runtime 0.40.0, VFC "
                       "1.0.1, Advanced Vehicle Pack and BSL. Not game-tested.",
        "Options": [{"Name": "Multi-weapon Eagle payload",
                     "Description": "X or 1-7: select weapon. B: fire while "
                                    "flying. Home: rearm run while landed and "
                                    "stopped.",
                     "Include": ["Addon"]}],
    }
    report = {"source_sha256": hashes, "game_tested": False,
              "runtime_version": "0.40.0", "runtime_api": 1,
              "runtime_zip_sha256": "3357d8b2b832dad23dd96af90e21d4fcdea60367a097a172d7e749ddbc1ff0ab",
              "weapons": ["output/v1/projectile/eagle-500kg-bomb-projectile-239",
                          "output/v1/projectile/eagle-airstrike-projectile-170",
                          "output/v1/projectile/eagle-cluster-bomb-projectile-286",
                          "output/v1/projectile/eagle-napalm-airstrike-projectile-141",
                          "output/v1/projectile/eagle-110mm-rocket-pods-projectile-82",
                          "output/v1/projectile/eagle-gas-airstrike-projectile-188",
                          "output/v1/projectile/eagle-smoke-strike-projectile-130"],
              "uses_development_api": True, "native_offsets_copied": False}
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        z.writestr("README.txt", README)
        z.writestr("validation.json", json.dumps(report, indent=2))
        name = "Addon/9ba626afa44a3aa3.patch_0"
        z.writestr(name, encode_lua_archive(resources))
        z.writestr(name + ".gpu_resources", b"")
        z.writestr(name + ".stream", b"")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2))
