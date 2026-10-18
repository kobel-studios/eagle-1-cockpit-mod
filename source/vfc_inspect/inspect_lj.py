"""Read stripped LuaJIT 2 bytecode as data only. Never load/execute Lua or FFI.

Format: https://github.com/LuaJIT/LuaJIT/blob/v2.1/src/lj_bcdump.h
Opcodes: https://github.com/LuaJIT/LuaJIT/blob/v2.1/src/lj_bc.h
This focused inspector rejects unsupported flags and malformed boundaries.
It opens no process handles and calls no Lua runtime.
"""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path


OPS = """ISLT ISGE ISLE ISGT ISEQV ISNEV ISEQS ISNES ISEQN ISNEN ISEQP ISNEP
ISTC ISFC IST ISF ISTYPE ISNUM MOV NOT UNM LEN
ADDVN SUBVN MULVN DIVVN MODVN ADDNV SUBNV MULNV DIVNV MODNV
ADDVV SUBVV MULVV DIVVV MODVV POW CAT KSTR KCDATA KSHORT KNUM KPRI KNIL
UGET USETV USETS USETN USETP UCLO FNEW TNEW TDUP GGET GSET
TGETV TGETS TGETB TGETR TSETV TSETS TSETB TSETM TSETR
CALLM CALL CALLMT CALLT ITERC ITERN VARG ISNEXT RETM RET RET0 RET1
FORI JFORI FORL IFORL JFORL ITERL IITERL JITERL LOOP ILOOP JLOOP JMP
FUNCF IFUNCF JFUNCF FUNCV IFUNCV JFUNCV FUNCC FUNCCW""".split()


class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def take(self, count):
        if count < 0 or self.pos + count > len(self.data):
            raise ValueError("truncated data")
        value = self.data[self.pos:self.pos + count]
        self.pos += count
        return value

    def byte(self):
        return self.take(1)[0]

    def uleb(self):
        value = 0
        for shift in range(0, 35, 7):
            b = self.byte()
            value |= (b & 127) << shift
            if not b & 128:
                return value
        raise ValueError("oversized ULEB128")


def signed32(n):
    return n - 2**32 if n >= 2**31 else n


def double(lo, hi):
    return struct.unpack("<d", struct.pack("<II", lo, hi))[0]


def table_value(r):
    tag = r.uleb()
    if tag >= 5:
        return r.take(tag - 5).decode("utf-8", errors="backslashreplace")
    if tag == 3:
        return signed32(r.uleb())
    if tag == 4:
        return double(r.uleb(), r.uleb())
    return [None, False, True][tag]


def unwrap(data):
    """Accept only this wrapper's literal decimal escapes; do not evaluate it."""
    match = re.search(rb'local _c\s*=\s*"((?:\\[0-9]{1,3})*)"', data[8:])
    if match is None:
        raise ValueError("no decimal-escape bytecode literal")
    return bytes(int(x) for x in match[1].split(bytes([92]))[1:])


def parse(data):
    r = Reader(data)
    if r.take(4) != b"\x1bLJ\x02":
        raise ValueError("requires LuaJIT bytecode version 2")
    flags = r.uleb()
    if flags != 2:
        raise ValueError("only stripped little-endian non-FFI dump supported")
    protos, stack = [], []
    while True:
        size = r.uleb()
        if size == 0:
            break
        offset = r.pos
        p = Reader(r.take(size))
        pflags, params, frame, nuv = p.take(4)
        nkgc, nnum, nbc = p.uleb(), p.uleb(), p.uleb()
        instructions = [struct.unpack("<I", p.take(4))[0] for _ in range(nbc)]
        upvalues = [struct.unpack("<H", p.take(2))[0] for _ in range(nuv)]
        constants = []
        for _ in range(nkgc):
            tag = p.uleb()
            if tag >= 5:
                value = p.take(tag - 5).decode("utf-8", errors="backslashreplace")
            elif tag == 0:
                if not stack:
                    raise ValueError("missing child prototype")
                value = {"proto": stack.pop()}
            elif tag == 1:
                na, nh = p.uleb(), p.uleb()
                value = {"array": [table_value(p) for _ in range(na)],
                         "hash": [[table_value(p), table_value(p)] for _ in range(nh)]}
            else:
                raise ValueError("unsupported cdata constant")
            constants.append(value)
        numbers = []
        for _ in range(nnum):
            lo = p.uleb()
            numbers.append(double(lo >> 1, p.uleb()) if lo & 1 else signed32(lo >> 1))
        if p.pos != size:
            raise ValueError(f"prototype {len(protos)} has unconsumed bytes")
        proto = dict(id=len(protos), offset=offset, size=size, flags=pflags,
                     params=params, frame=frame, upvalues=upvalues,
                     constants=list(reversed(constants)), numbers=numbers,
                     instructions=instructions)
        protos.append(proto)
        stack.append(proto["id"])
    if r.pos != len(data) or len(stack) != 1:
        raise ValueError("invalid trailing bytes or prototype tree")
    return protos


def listing(protos):
    lines = []
    for p in protos:
        lines.append(f'\nPROTO {p["id"]} offset={p["offset"]} size={p["size"]} '
                     f'params={p["params"]} frame={p["frame"]} upvalues={p["upvalues"]}')
        for i, c in enumerate(p["constants"]):
            lines.append(f"  KGC[{i}] = {c!r}")
        lines.append(f'  NUM = {p["numbers"]!r}')
        for pc, ins in enumerate(p["instructions"], 1):
            op, a, c, b = ins & 255, ins >> 8 & 255, ins >> 16 & 255, ins >> 24
            d = ins >> 16
            name = OPS[op] if op < len(OPS) else f"UNKNOWN_{op}"
            annotation = ""
            if name in {"KSTR", "KCDATA", "FNEW", "TDUP", "GGET", "GSET", "ISEQS", "ISNES", "USETS"}:
                annotation = repr(p["constants"][d])
            elif name in {"TGETS", "TSETS"}:
                annotation = repr(p["constants"][c])
            elif name in {"KNUM", "USETN", "ISEQN", "ISNEN"}:
                annotation = repr(p["numbers"][d])
            elif name.endswith(("VN", "NV")):
                annotation = repr(p["numbers"][c])
            elif name == "KSHORT":
                annotation = str(d if d < 32768 else d - 65536)
            elif name in {"JMP", "UCLO", "FORI", "FORL", "ITERL", "LOOP", "ISNEXT"}:
                annotation = f"-> {pc + 1 + d - 32768}"
            lines.append(f"  {pc:04d} {name:7s} A={a:3d} B={b:3d} C={c:3d} D={d:5d} ; {annotation}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("wrapper", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    original = args.wrapper.read_bytes()
    bytecode = unwrap(original)
    protos = parse(bytecode)
    if args.json:
        print(json.dumps(protos, indent=2))
    else:
        print(f"Wrapper SHA256: {hashlib.sha256(original).hexdigest()}")
        print(f"Bytecode length: {len(bytecode)}; SHA256: {hashlib.sha256(bytecode).hexdigest()}")
        print(listing(protos))


if __name__ == "__main__":
    main()
