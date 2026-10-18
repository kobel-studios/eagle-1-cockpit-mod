"""Read-only Eagle package/source checks. Never extract or execute mod content."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "hd2tools"))
from hd2_archive import murmur64_hash

PATCH = re.compile(r"Addon/([0-9a-f]{16})\.patch_(0|[1-9][0-9]*)")
LUA = 0xA14E8DFA2CD117E2
BASE = "9ba626afa44a3aa3"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_layer(toc, gpu, stream):
    if len(toc) < 72:
        raise ValueError("Truncated archive header")
    magic, types, count = struct.unpack_from("<III", toc)
    end = 72 + types * 32 + count * 80
    if magic != 0xF0000011 or not types or not count or end > len(toc):
        raise ValueError("Invalid archive table")
    declared, actual, result = {}, {}, {}
    for index in range(types):
        _, ident, amount, _, _ = struct.unpack_from("<QQQII", toc, 72 + index * 32)
        if ident in declared:
            raise ValueError("Duplicate archive type")
        declared[ident] = amount
    for index in range(count):
        row = struct.unpack_from("<7Q6I", toc, 72 + types * 32 + index * 80)
        fid, tid, toc_offset, stream_offset, gpu_offset = row[:5]
        toc_size, stream_size, gpu_size = row[7:10]
        if tid not in declared or (tid, fid) in result:
            raise ValueError("Duplicate resource or undeclared type")
        actual[tid] = actual.get(tid, 0) + 1
        chunks = []
        for label, data, start, size in (
            ("CPU", toc, toc_offset, toc_size),
            ("GPU", gpu, gpu_offset, gpu_size),
            ("stream", stream, stream_offset, stream_size),
        ):
            if size and (start + size > len(data) or (label == "CPU" and start < end)):
                raise ValueError(f"Resource exceeds {label} data")
            chunks.append(data[start:start + size])
        result[tid, fid] = tuple(chunks)
    if actual != declared:
        raise ValueError("Archive type counts do not match")
    return result


def check(package, source_root=ROOT, source_names=None):
    """Return evidence on success; raise on corruption or stale local modules."""
    package, source_root = Path(package), Path(source_root).resolve()
    if source_names is None:
        # These are our local Python builder constants, not archive code.
        from build_eagle_payload import SOURCES
        source_names = SOURCES
    winners, observed, counters = {}, set(), {}
    # A teammate can rebuild while this runs. Parse and fingerprint one snapshot.
    package_data = package.read_bytes()
    with zipfile.ZipFile(io.BytesIO(package_data)) as bundle:
        members = bundle.namelist()
        if len(members) != len(set(members)):
            raise ValueError("Duplicate ZIP member")
        if bundle.testzip() is not None:
            raise ValueError("ZIP integrity check failed")
        manifest = json.loads(bundle.read("manifest.json"))
        report = json.loads(bundle.read("validation.json"))
        if not isinstance(manifest.get("Name"), str) or manifest.get("Version") != 1:
            raise ValueError("Invalid Arsenal manifest")
        options = manifest.get("Options", [])
        if not any("Addon" in option.get("Include", []) for option in options):
            raise ValueError("Manifest does not include the patch folder")
        icon = manifest.get("IconPath")
        if icon is not None and icon not in members:
            raise ValueError("Manifest icon is missing")
        order = report.get("archive_order")
        if not isinstance(order, list) or not order:
            raise ValueError("Missing archive order")
        for item in order:
            member = "Addon/" + item["archive"]
            match = PATCH.fullmatch(member)
            if match is None or member in observed:
                raise ValueError("Invalid or duplicate patch in archive order")
            base, index = match[1], int(match[2])
            if index != counters.get(base, 0):
                raise ValueError("Archive order does not match numbered patch priority")
            counters[base] = index + 1
            observed.add(member)
            chunks = []
            for suffix in ("", ".gpu_resources", ".stream"):
                name = member + suffix
                if name not in members:
                    raise ValueError(f"Missing patch member: {name}")
                chunks.append(bundle.read(name))
            for (tid, fid), content in read_layer(*chunks).items():
                record = dict(
                    file_id=hex(fid), type_id=hex(tid), winner=item["label"],
                    toc_sha256=digest(content[0]), gpu_sha256=digest(content[1]),
                    stream_sha256=digest(content[2]),
                )
                winners[base, tid, fid] = record, content[0]
        actual_addon = {name for name in members if name.startswith("Addon/")
                        and not name.endswith("/")}
        expected_addon = {name + suffix for name in observed
                          for suffix in ("", ".gpu_resources", ".stream")}
        if actual_addon != expected_addon:
            raise ValueError("ZIP contains unreported patch files")
        expected = {}
        for base, detail in report["archives"].items():
            for record in detail["resources"]:
                key = base, int(record["type_id"], 16), int(record["file_id"], 16)
                if key in expected:
                    raise ValueError("Duplicate resource in validation report")
                expected[key] = record
        if set(expected) != set(winners):
            raise ValueError("Packaged resources differ from validation report")
        for key, (record, _) in winners.items():
            if record != expected[key]:
                raise ValueError(f"Resource fingerprint or winner differs: {key}")

        checked_sources, stale = {}, []
        for name, relative in source_names.items():
            local = (source_root / relative).resolve()
            if not local.is_relative_to(source_root):
                raise ValueError("Local source path leaves its project")
            key = BASE, LUA, murmur64_hash(name.encode("utf-8"))
            if key not in winners:
                raise ValueError(f"Missing local Lua module: {name}")
            body = winners[key][1]
            if len(body) < 8 or struct.unpack_from("<II", body) != (len(body) - 8, 2):
                raise ValueError(f"Invalid Lua envelope: {name}")
            source = local.read_bytes()
            if body[8:] != source:
                stale.append(relative)
            checked_sources[name] = digest(source)
        if stale:
            raise ValueError("Package needs rebuilding; stale Lua: " + ", ".join(stale))
    return {
        "name": manifest["Name"], "package_sha256": digest(package_data),
        "layers": len(observed), "winning_resources": len(winners),
        "current_source_sha256": checked_sources,
        "game_tested": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="Exact ZIP to verify")
    args = parser.parse_args(argv)
    try:
        result = check(args.package)
    except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile) as error:
        print(f"PACKAGE CHECK FAILED: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    print("PACKAGE CHECK PASSED (files only; no in-game test)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
