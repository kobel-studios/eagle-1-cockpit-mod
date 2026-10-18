"""Dump/list entries of an HD2 package archive.

Usage:
  python dump_archive.py <package_path> [--names <friendlynames.txt>]
                         [--type <type_id_hex_or_name>] [--extract <dir>]
                         [--find <name_substring>]

Lists every entry: FileID, TypeID(+name), toc/gpu/stream sizes.
--extract writes each entry's three data blobs as
  <outdir>/<FileID>.<type>/toc.bin, gpu.bin, stream.bin (skips empty blobs).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hd2_archive as A


def main():
    p = argparse.ArgumentParser()
    p.add_argument("package")
    p.add_argument("--names", default=None)
    p.add_argument("--type", default=None,
                   help="filter by type id (hex or decimal) or type name")
    p.add_argument("--extract", default=None)
    p.add_argument("--find", default=None,
                   help="only show entries whose friendly name contains this")
    args = p.parse_args()

    names = {}
    if args.names:
        names = A.load_friendly_names(args.names)

    toc = A.StreamToc()
    if not toc.FromFile(args.package):
        print(f"failed to read package: {args.package}")
        return 1

    type_filter = None
    if args.type:
        if args.type.lower().startswith("0x"):
            type_filter = int(args.type, 16)
        elif args.type.isdigit():
            type_filter = int(args.type)
        else:
            for tid, tname in A.TYPE_NAMES.items():
                if tname == args.type.lower():
                    type_filter = tid
                    break
            if type_filter is None:
                print(f"unknown type: {args.type}")
                return 1

    total = 0
    for type_id in sorted(toc.TocDict):
        if type_filter is not None and type_id != type_filter:
            continue
        entries = toc.TocDict[type_id]
        print(f"== type {type_id} ({A.type_name(type_id)}) - {len(entries)} entries")
        for file_id in sorted(entries):
            e = entries[file_id]
            fname = names.get(file_id, "")
            if args.find and args.find.lower() not in fname.lower():
                continue
            total += 1
            label = f"  {fname}" if fname else ""
            print(f"  {file_id:20d}  toc={e.TocDataSize:>9d}  "
                  f"gpu={e.GpuResourceSize:>9d}  stream={e.StreamSize:>9d}{label}")
            if args.extract:
                outdir = os.path.join(args.extract, f"{file_id}.{A.type_name(type_id)}")
                os.makedirs(outdir, exist_ok=True)
                for blob, suffix in ((e.TocData, "toc.bin"),
                                     (e.GpuData, "gpu.bin"),
                                     (e.StreamData, "stream.bin")):
                    if blob:
                        with open(os.path.join(outdir, suffix), "wb") as f:
                            f.write(blob)
    print(f"-- {total} entries shown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
