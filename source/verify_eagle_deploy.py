"""Verify the Eagle-1 Cockpit Pack layers actually deployed to the game data dir.

Compares every patch file Arsenal wrote for the two archives the pack touches
(9ba626afa44a3aa3, 007e093ca718ca1a) against the pack zip's Addon contents by
SHA-256. Flags pack layers that are missing and stale duplicate payloads that
still contain our module names but no longer match the pack.

Run after Arsenal Purge + Deploy, before launching the game:

    C:\\Python310\\python.exe verify_eagle_deploy.py

Exit code 0 = every pack layer present and no stale Eagle payload remnants.
"""
import hashlib
import json
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = r"b:\all da games baby\steamapps\common\Helldivers 2\data"


def newest_pack(directory=HERE):
    """Newest Eagle-1-Cockpit-Pack-*.zip in the work dir, or None."""
    best = None
    for name in os.listdir(directory):
        if name.startswith("Eagle-1-Cockpit-Pack-") and name.endswith(".zip"):
            path = os.path.join(directory, name)
            if best is None or os.path.getmtime(path) > os.path.getmtime(best):
                best = path
    return best

# Module-name fingerprints that mark a patch as "ours" for stale detection.
OUR_MARKERS = (b"eagle_payload", b"eagle_camera_scope", b"camera_diagnostics")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def pack_label(pack_zip_path):
    """Human identity of the zip being verified, e.g. 'Eagle-1 Cockpit Pack 0.6'."""
    try:
        with zipfile.ZipFile(pack_zip_path) as z:
            manifest = json.loads(z.read("manifest.json"))
            name = manifest.get("Name")
            return name if isinstance(name, str) and name else os.path.basename(
                pack_zip_path)
    except Exception:
        return os.path.basename(pack_zip_path)


def expected_layers(pack_zip_path):
    """Return {archive_id: {layer_name: sha256}} for every .patch_N in the zip."""
    layers = {}
    with zipfile.ZipFile(pack_zip_path) as z:
        for name in z.namelist():
            base = os.path.basename(name)
            if not base.startswith("0") and not base.startswith("9"):
                continue
            if ".patch_" not in base or base.endswith((".stream", ".gpu_resources")):
                continue
            archive, _, _ = base.partition(".patch_")
            layers.setdefault(archive, {})[base] = sha256(z.read(name))
    return layers


def deployed_patches(data_dir, archives):
    """Return {filename: sha256} for patch files of the given archives."""
    found = {}
    for fname in os.listdir(data_dir):
        for arch in archives:
            if fname.startswith(arch + ".patch_") and not fname.endswith(
                (".stream", ".gpu_resources")
            ):
                with open(os.path.join(data_dir, fname), "rb") as f:
                    found[fname] = sha256(f.read())
    return found


def check(pack_zip_path=None, data_dir=DATA_DIR):
    """Return (ok, report_lines). ok True = fully deployed, no stale remnants."""
    pack_zip_path = pack_zip_path or newest_pack()
    if not pack_zip_path or not os.path.isfile(pack_zip_path):
        return False, ["pack zip not found: %s" % pack_zip_path]
    if not os.path.isdir(data_dir):
        return False, ["game data dir not found: %s" % data_dir]

    expected = expected_layers(pack_zip_path)
    deployed = deployed_patches(data_dir, expected.keys())
    by_hash = {}
    for fname, h in deployed.items():
        by_hash.setdefault(h, []).append(fname)

    lines, ok = ["PACK %s (%s)" % (pack_label(pack_zip_path),
                os.path.basename(pack_zip_path))], True
    matched_deployed = set()
    for arch, layers in sorted(expected.items()):
        for layer, h in sorted(layers.items()):
            hits = by_hash.get(h, [])
            if hits:
                matched_deployed.update(hits)
                lines.append("OK   %s deployed as %s" % (layer, ", ".join(hits)))
            else:
                ok = False
                lines.append("MISS %s not found in game data" % layer)

    for fname, h in sorted(deployed.items()):
        if fname in matched_deployed:
            continue
        path = os.path.join(data_dir, fname)
        with open(path, "rb") as f:
            data = f.read()
        marks = [m.decode() for m in OUR_MARKERS if m in data]
        if marks:
            ok = False
            lines.append(
                "STALE %s contains %s but does not match any pack layer"
                % (fname, marks)
            )
        else:
            lines.append("OTHER %s (unrelated mod patch, %d bytes)"
                         % (fname, len(data)))
    return ok, lines


def main(argv):
    ok, lines = check(argv[1] if len(argv) > 1 else None)
    for line in lines:
        print(line)
    print("DEPLOY %s" % ("CLEAN" if ok else "INCOMPLETE"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
