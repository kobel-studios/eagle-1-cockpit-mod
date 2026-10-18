"""Read pinned HD2Runtime Lua source as data. Never import/execute archive code.

HD2Runtime is by SkyeShade. The archive has Guardian UNKNOWN/no findings,
which is not proof of safety. This utility only inspects the pinned artifact.
"""
import argparse
import hashlib
from pathlib import Path
import struct
import zipfile

SHA256 = "3357d8b2b832dad23dd96af90e21d4fcdea60367a097a172d7e749ddbc1ff0ab"
MEMBER = "runtime/9ba626afa44a3aa3.patch_0"


def murmur64(data):
    """Seed-zero MurmurHash64A for resource names (not native game calls)."""
    mask = (1 << 64) - 1
    multiplier = 0xC6A4A7935BD1E995
    value = len(data) * multiplier & mask
    end = len(data) // 8 * 8
    for offset in range(0, end, 8):
        word = int.from_bytes(data[offset:offset + 8], "little")
        word = word * multiplier & mask
        word ^= word >> 47
        word = word * multiplier & mask
        value = (value ^ word) * multiplier & mask
    if end != len(data):
        value = (value ^ int.from_bytes(data[end:], "little")) * multiplier & mask
    value ^= value >> 47
    value = value * multiplier & mask
    return value ^ (value >> 47)


def read_source(archive, resource):
    raw = Path(archive).read_bytes()
    if hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError("Not the reviewed HD2Runtime 0.40.0 runtime artifact")
    with zipfile.ZipFile(archive) as bundle:
        data = bundle.read(MEMBER)
    magic, types, files, _ = struct.unpack_from("<4I", data)
    if magic != 4026531857:
        raise ValueError("Unexpected archive format")
    resource_hash = murmur64(resource.encode("utf-8"))
    for index in range(files):
        entry = struct.unpack_from("<7Q6I", data, 72 + types * 32 + index * 80)
        if entry[0] != resource_hash or entry[1] != 0xA14E8DFA2CD117E2:
            continue
        offset, size = entry[2], entry[7]
        if size < 8 or offset + size > len(data):
            raise ValueError("Invalid Lua resource bounds")
        payload = data[offset:offset + size]
        length, version = struct.unpack_from("<2I", payload)
        if length != size - 8:
            raise ValueError("Unexpected Lua length header")
        return payload[8:].decode("utf-8"), version
    raise KeyError(resource)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resource")
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=100000)
    options = parser.parse_args()
    archive = Path(__file__).resolve().parent.parent / "HD2Runtime-0.40.0-runtime.zip"
    source, version = read_source(archive, options.resource)
    print(f"{options.resource} (resource header version {version})")
    for number, line in enumerate(source.splitlines(), 1):
        if options.start <= number <= options.end:
            print(f"{number}: {line}")


if __name__ == "__main__":
    main()
