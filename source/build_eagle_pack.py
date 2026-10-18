"""Build one local Eagle Arsenal package from reviewed components.

Winning resources are checked by (archive, type, file ID), in explicit
low-to-high priority order. The package preserves internal archive boundaries:
ATT's compatibility scanner distinguishes its archive from the Eagle skin.
Models keep their GPU/stream data. Shared loaders are excluded.
This builder never writes to the game or Arsenal registry.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "hd2tools"))
import hd2_archive as archive

GUID = "e716c824-32ab-4c84-a00b-95c83c08f525"
NAME = "Eagle-1 Cockpit Pack 0.9"
SOURCE_IDS = {
    "flight": "39daa4c6-0918-5b08-9b7f-65c56d3303f9",
    "vehicles": "508ec003-1e65-5d8f-b528-8584fbfa7b29",
    "camera": "ab464d73-2b5a-4894-9b46-e0754fa28673",
    "skin": "72dc6ebf-1bec-5043-86cf-dc9de8abe68e",
}
PATTERN = re.compile(r"^([0-9a-f]{16})\.patch_[0-9]+$", re.I)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_checked(path):
    """Validate bounds before the legacy reader can allocate based on a header."""
    path = Path(path)
    data = path.read_bytes()
    if len(data) < 72:
        raise ValueError("truncated archive header: " + str(path))
    magic, types, files = struct.unpack_from("<III", data)
    end = 72 + 32 * types + 80 * files
    if magic != archive.TOC_MAGIC or not types or not files or end > len(data):
        raise ValueError("invalid archive table: " + str(path))
    declared = {}
    for i in range(types):
        _, type_id, count, _, _ = struct.unpack_from("<QQQII", data, 72 + 32 * i)
        if type_id in declared:
            raise ValueError("duplicate type record")
        declared[type_id] = count
    actual, seen = {}, set()
    sizes = {}
    for suffix in (".gpu_resources", ".stream"):
        sidecar = Path(str(path) + suffix)
        sizes[suffix] = sidecar.stat().st_size if sidecar.is_file() else 0
    for i in range(files):
        row = struct.unpack_from("<7Q6I", data, 72 + 32 * types + 80 * i)
        file_id, type_id, toc, stream, gpu = row[:5]
        toc_size, stream_size, gpu_size = row[7:10]
        key = type_id, file_id
        if key in seen or type_id not in declared:
            raise ValueError("duplicate resource or undeclared type")
        seen.add(key)
        actual[type_id] = actual.get(type_id, 0) + 1
        if toc_size and (toc < end or toc + toc_size > len(data)):
            raise ValueError("resource exceeds archive data")
        for offset, size, suffix in ((gpu, gpu_size, ".gpu_resources"),
                                     (stream, stream_size, ".stream")):
            if size and offset + size > sizes[suffix]:
                raise ValueError("missing or truncated sidecar: " + suffix)
    if actual != declared:
        raise ValueError("type counts do not match resource table")
    result = archive.StreamToc()
    if not result.FromFile(str(path)):
        raise ValueError("cannot parse archive: " + str(path))
    return result


def resource_record(entry, winner):
    return dict(file_id=hex(entry.FileID), type_id=hex(entry.TypeID), winner=winner,
                toc_sha256=digest(bytes(entry.TocData)),
                gpu_sha256=digest(bytes(entry.GpuData)),
                stream_sha256=digest(bytes(entry.StreamData)))


def merge_archives(inputs, output_dir):
    """Merge ordered input archives; reject nonempty destinations and bad inputs."""
    if not inputs:
        raise ValueError("no source archives")
    output_dir = Path(output_dir)
    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise ValueError("output directory must be empty or absent")
    if not output_dir.parent.is_dir():
        raise ValueError("output parent must exist")
    grouped, reports = {}, {}
    # Validate everything before creating output. Inputs must not be overwritten.
    for label, path in inputs:
        path = Path(path)
        match = PATTERN.fullmatch(path.name)
        if not match:
            raise ValueError("invalid patch archive filename: " + path.name)
        base = match[1].lower()
        toc = read_checked(path)
        resources = grouped.setdefault(base, {})
        report = reports.setdefault(base, {"resources": [], "overrides": []})
        for type_id, entries in toc.TocDict.items():
            for file_id, entry in entries.items():
                key = type_id, file_id
                if key in resources:
                    report["overrides"].append(dict(
                        file_id=hex(file_id), type_id=hex(type_id),
                        previous=resources[key][1], winner=label))
                resources[key] = copy.deepcopy(entry), label
    output_dir.mkdir(exist_ok=True)
    for base, resources in sorted(grouped.items()):
        merged = archive.StreamToc()
        for key in sorted(resources):
            entry, label = resources[key]
            merged.AddEntry(entry)
            reports[base]["resources"].append(resource_record(entry, label))
        path = output_dir / (base + ".patch_0")
        merged.ToFile(str(path))
        # Readback checks every payload, including both graphics sidecars.
        back = read_checked(path)
        if sum(map(len, back.TocDict.values())) != len(resources):
            raise ValueError("merged resource count changed")
        for (type_id, file_id), (entry, label) in resources.items():
            actual = back.GetEntry(file_id, type_id)
            if resource_record(actual, label) != resource_record(entry, label):
                raise ValueError("merged payload differs from winning input")
    return {"archives": reports}


def extract_generated_package(package, destination):
    """Extract only generated patch triplets, with no arbitrary ZIP paths."""
    destination = Path(destination)
    destination.mkdir()
    with zipfile.ZipFile(package) as z:
        for name in z.namelist():
            if not name.startswith("Addon/"):
                continue
            leaf = name[len("Addon/"):]
            base_leaf = re.sub(r"\.(gpu_resources|stream)$", "", leaf)
            if not PATTERN.fullmatch(base_leaf):
                raise ValueError("unexpected generated archive member")
            (destination / leaf).write_bytes(z.read(name))
    return sorted(p for p in destination.iterdir() if PATTERN.fullmatch(p.name))


def layer_archives(inputs, output_dir):
    """One Arsenal entry, with ordered internal patches for upstream scanners."""
    output_dir = Path(output_dir)
    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise ValueError("output directory must be empty or absent")
    if not output_dir.parent.is_dir():
        raise ValueError("output parent must exist")
    prepared, counters = [], {}
    for label, source in inputs:
        source = Path(source)
        match = PATTERN.fullmatch(source.name)
        if not match:
            raise ValueError("invalid patch archive filename")
        read_checked(source)
        base = match[1].lower()
        index = counters.get(base, 0)
        counters[base] = index + 1
        prepared.append((label, source, base + ".patch_" + str(index)))
    output_dir.mkdir(exist_ok=True)
    records = []
    for label, source, name in prepared:
        for suffix in ("", ".gpu_resources", ".stream"):
            original, target = Path(str(source) + suffix), output_dir / (name + suffix)
            if original.exists():
                shutil.copyfile(original, target)
            else:
                target.write_bytes(b"")
        records.append({"label": label, "archive": name})
    return records


def build(registry_path, output, profile_id=None):
    """Build using installed upstream sources and our current local feature code."""
    from build_eagle_payload import build as build_payload
    import make_icon_patch
    import hd2tool

    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    if not output.parent.is_dir():
        raise ValueError("output parent must exist")
    registry_bytes = Path(registry_path).read_bytes()
    data = json.loads(registry_bytes.decode("utf-8-sig"))
    if data.get("setTopPriority"):
        raise ValueError("review reversed Arsenal priority before consolidating")
    profile_id = profile_id or data["selectedProfile"]
    # After consolidation the originals live in Library, not the active profile.
    mods = {m["uuid"]: m for m in data.get("modsLibrary", [])}
    mods.update({m["uuid"]: m for m in data["modsList"][profile_id]["mods"]})
    sources = {name: Path(mods[uuid]["path"]) for name, uuid in SOURCE_IDS.items()}
    options = {o["name"]: o["enabled"] for o in mods[SOURCE_IDS["vehicles"]]["options"]}
    for expected in ("Advanced Tank Turret 3.3.0", "Advanced Tank Hull 0.11.1"):
        if not options.get(expected):
            raise ValueError("required AVP component is disabled: " + expected)
    if options.get("Exo Dodge 1.1.0"):
        raise ValueError("EXO is enabled: review scope rather than silently discarding it")
    with tempfile.TemporaryDirectory(dir=output.parent, prefix="eagle-pack-") as tmp:
        stage = Path(tmp)
        payload_zip = stage / "payload.zip"
        build_payload(payload_zip)
        payload_files = extract_generated_package(payload_zip, stage / "payload")
        icon_dir = stage / "icon"
        icon_dir.mkdir()
        sdk = hd2tool.load_sdk()
        hd2tool.init_game_data(sdk)
        make_icon_patch.build_patch(sdk, str(icon_dir))
        make_icon_patch.verify(sdk, str(icon_dir))
        inputs = [
            ("Vehicle Flight Control 1.0.1", sources["flight"] / "Addon/9ba626afa44a3aa3.patch_0"),
            ("Advanced Tank Hull 0.11.1", sources["vehicles"] / "ATH/9ba626afa44a3aa3.patch_0"),
            ("Advanced Tank Turret 3.3.0", sources["vehicles"] / "ATT/9ba626afa44a3aa3.patch_0"),
            ("Cockpit camera override", sources["camera"] / "Addon/9ba626afa44a3aa3.patch_0"),
            *[("Current Eagle payload/rearm", p) for p in payload_files],
            ("Eagle1 Maelstrom v5", sources["skin"] / "9ba626afa44a3aa3.patch_0"),
            ("Custom blue Eagle icon", icon_dir / make_icon_patch.OUT_PATCH),
        ]
        report = merge_archives(inputs, stage / "merged-reference")
        report["archive_order"] = layer_archives(inputs, stage / "Addon")
        report["preserves_upstream_archive_boundaries"] = True
        report.update(
            game_tested=False, source_profile=profile_id,
            source_registry_sha256=digest(registry_bytes),
            shared_dependencies=["Bingus Shared Loader v18", "HD2Runtime 0.40.0"],
            excluded=["Tank Seat Kit", "Exo Dodge"],
            sources=[{"label": label, "file": str(path),
                      "sha256": digest(path.read_bytes())} for label, path in inputs])
        manifest = dict(Version=1, Guid=GUID, Name=NAME,
                        Description="Eagle1 Maelstrom v5 with flight, cockpit-only camera, "
                        "drive/fire vehicle features, custom blue icon, seven Eagle weapons "
                        "and a 60-second landed rearm run. Experimental mission behavior. "
                        "Requires Bingus Shared Loader and HD2Runtime 0.40.0.",
                        IconPath="eagle_icon.png",
                        Options=[{"Name": "Eagle flight, cockpit and payload",
                                  "Description": "One combined Eagle setup. Shared loaders remain separate.",
                                  "Include": ["Addon"]}])
        readme = (
            NAME + "\n\nPRIVATE LOCAL COMBINATION; mission behavior still needs testing.\n"
            "Contains Eagle1 Maelstrom v5, Vehicle Flight Control 1.0.1, Advanced "
            "Tank Hull/Turret and our cockpit/icon/payload changes. Original authors "
            "retain ownership of their components; obtain their permission before "
            "redistributing this combined archive.\n\n"
            "Install this ONE Eagle entry with Bingus Shared Loader v18 and "
            "HD2Runtime 0.40.0 (https://github.com/SkyeShade/HD2Runtime). "
            "Disable the six original Eagle component entries and Tank Seat Kit. "
            "Keep originals installed for rollback. Other mods remain independent.\n\n"
            "I: flight. X or 1-7: select one of seven Eagle weapons (500kg x2, "
            "airstrike x3, cluster x4, napalm x3, rockets x8, gas x2, smoke x4). "
            "B: fire the selected weapon. Home: rearm run while landed and "
            "stopped; a service Pelican flies in and hovers over the parked "
            "Eagle for the 60-second run that refills every weapon. "
            "Insert is unused now.\n"
            "Normal camera on foot; cockpit mode and HUD are requested only in "
            "the verified Maelstrom pilot/gunner seat, landed or flying. The "
            "first-person eye now sits inside the canopy (0.6 m forward, 1.15 m "
            "up); the fake blue canopy frame is removed, leaving only the "
            "crosshair and the ammo panel. A parked seat found by proximity no "
            "longer needs a flight toggle. Fired weapons launch along the nose "
            "- toward the crosshair - not straight down. Turn/roll feel tuned "
            "through the VFC options file (turn 100%, roll 85%) and the "
            "ship now sinks under gravity when you let go instead of "
            "freezing in midair (hover_hold off in the VFC patch).\n"
            "Only the 500kg projectile is proven in game; the other six are "
            "unverified donors. Super Destroyer docking is not implemented.\n"
        )
        with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(manifest, indent=2))
            z.writestr("validation.json", json.dumps(report, indent=2))
            z.writestr("README.txt", readme)
            z.write(ROOT / "eagle_icon.png", "eagle_icon.png")
            for file in sorted((stage / "Addon").iterdir()):
                z.write(file, "Addon/" + file.name)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = build(args.registry, args.output)
    print(json.dumps({"output": str(args.output),
                      "resources": {k: len(v["resources"]) for k, v in result["archives"].items()}}))
