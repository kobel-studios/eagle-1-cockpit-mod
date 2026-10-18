"""Standalone HD2 stingray archive reader/writer.

Pure-python extraction of the archive code from HD2SDK-CommunityEdition so it
runs without Blender. Supports the LEGACY on-disk package layout used by the
game's data folder (a package file plus optional .gpu_resources and .stream
sidecars). DSAR / bundled package types are not handled here.
"""

import os
import struct
from math import ceil
from pathlib import Path

TOC_MAGIC = 4026531857

# ---- hashing (from utils/hashing.py) ----

def bytes_to_long(b):
    assert len(b) == 8
    return sum((byte << (k * 8) for k, byte in enumerate(b)))


def murmur64_hash(data, seed: int = 0):
    m = 0xc6a4a7935bd1e995
    r = 47
    MASK = 2 ** 64 - 1
    data_as_bytes = bytearray(data)
    h = seed ^ ((m * len(data_as_bytes)) & MASK)
    off = int(len(data_as_bytes) / 8) * 8
    for ll in range(0, off, 8):
        k = bytes_to_long(data_as_bytes[ll:ll + 8])
        k = (k * m) & MASK
        k = k ^ ((k >> r) & MASK)
        k = (k * m) & MASK
        h = (h ^ k)
        h = (h * m) & MASK
    l = len(data_as_bytes) & 7
    if l >= 7: h = (h ^ (data_as_bytes[off+6] << 48))
    if l >= 6: h = (h ^ (data_as_bytes[off+5] << 40))
    if l >= 5: h = (h ^ (data_as_bytes[off+4] << 32))
    if l >= 4: h = (h ^ (data_as_bytes[off+3] << 24))
    if l >= 3: h = (h ^ (data_as_bytes[off+2] << 16))
    if l >= 2: h = (h ^ (data_as_bytes[off+1] << 8))
    if l >= 1:
        h = (h ^ data_as_bytes[off])
        h = (h * m) & MASK
    h = h ^ ((h >> r) & MASK)
    h = (h * m) & MASK
    h = h ^ ((h >> r) & MASK)
    return h


# ---- type ids (from utils/constants.py) ----

CompositeUnitID = 14191111524867688662
UnitID          = 16187218042980615487
TexID           = 14790446551990181426
MaterialID      = 16915718763308572383
BoneID          = 1792059921637536489
WwiseBankID     = 6006249203084351385
WwiseDepID      = 12624162998411505776
WwiseStreamID   = 5785811756662211598
WwiseMetaDataID = 15351235653606224144
ParticleID      = 12112766700566326628
AnimationID     = 10600967118105529382
StateMachineID  = 11855396184103720540
StringID        = 979299457696010195
PhysicsID       = 6877563742545042104
XamlID          = 5097092548853106021

TYPE_NAMES = {
    0x18dead01056b72e9: "bones",
    0x2a690fd348fe9ac5: "level",
    0x5f7203c8f280dab8: "physics",
    0x931e336d7646cc26: "animation",
    0xa486d4045106165c: "state_machine",
    0xa8193123526fad64: "particles",
    0xab2f78e885f513c6: "prefab",
    0xcd4238c6a0c69e32: "texture",
    0xe0a48d0be9a7453f: "unit",
    0xeac0b497876adedf: "material",
    0x535a7bd3e650d799: "wwise_bank",
    0xaf32095c82f2b070: "wwise_dep",
    0x504b55235d21440e: "wwise_stream",
    0x250e0a11ac8e26f8: "shading_environment_mapping",
    0x9831ca893b0d087d: "entity",
    0xaa5965f03029fa18: "bik",
    0x9efe0a916aae7880: "font",
    0xd7014a50477953e0: "cloth",
    0xfe73c7dcff8a7ca5: "shading_environment",
    0xa14e8dfa2cd117e2: "lua",
    0xf7505933166d6755: "vector_field",
    0x92d3ee038eeb610d: "flow",
    0x27862fe24795319c: "render_config",
    0x0d972bab10b40fd3: "strings",
    0x3b1fa9e8f6bac374: "network_config",
    0x82645835e6b73232: "config",
    0xad9c6d9ed1e5e77a: "package",
    0xd50a8b7e1c82b110: "wwise_metadata",
    0xb277b11fe4a61d37: "mouse_cursor",
    0x7910103158fc1de9: "renderable",
    0x9e5c3cc74575aeb5: "shader_library_group",
    0xe5ee32a477239a93: "shader_library",
    0x05106b81dcd58a13: "runtime_font",
    0x1d59bd6687db6b33: "ragdoll_profile",
    0x2a0a70acfe476e1d: "ah_bin",
    0x57a13425279979d7: "ik_skeleton",
    0x5fdd5fe391076f9f: "wwise_properties",
    0x6592b918e67f082c: "havok_ai_properties",
    0x9199bb50b6896f02: "texture_atlas",
    0xb8fd4d2cede20ed7: "geleta",
    0xc4f0f4be7fb0c8d6: "geometry_group",
    0xe3f2851035957af5: "hash_lookup",
    0xe985c5f61c169997: "speedtree",
    0xf7a09f8bb35a1d49: "havok_physics_properties",
    0xfcaaf813b4d3cc1e: "camera_shake",
    0x5ee65304478f8db5: "bik2",
    0x46bc82aae9ae0565: "unknown",
}


def type_name(type_id):
    return TYPE_NAMES.get(type_id, hex(type_id))


# ---- memory stream (from utils/memoryStream.py) ----

class MemoryStream:
    def __init__(self, Data=b"", IOMode="read"):
        self.Location = 0
        self.Data = bytearray(Data)
        self.reading = IOMode == "read"

    def IsReading(self):
        return self.reading

    def IsWriting(self):
        return not self.reading

    def seek(self, Location):
        self.Location = Location
        if self.Location > len(self.Data):
            self.Data.extend(bytearray(self.Location - len(self.Data)))

    def tell(self):
        return self.Location

    def read(self, length=-1):
        if length == -1:
            length = len(self.Data) - self.Location
        if self.Location + length > len(self.Data):
            raise Exception("reading past end of stream")
        newData = self.Data[self.Location:self.Location + length]
        self.Location += length
        return bytes(newData)

    def write(self, data):
        length = len(data)
        self.Data[self.Location:self.Location + length] = data
        self.Location += length

    def serialize(self, value, fmt, size):
        if self.reading:
            return struct.unpack(fmt, self.read(size))[0]
        self.write(struct.pack(fmt, value))
        return value

    def uint32(self, value):
        return self.serialize(value, '<I', 4)

    def uint64(self, value):
        return self.serialize(value, '<Q', 8)

    def bytes(self, value, size=-1):
        if size == -1:
            size = len(value)
        if len(value) != size:
            value = bytearray(size)
        if self.reading:
            return bytearray(self.read(size))
        self.write(value)
        return bytearray(value)


# ---- package io (legacy path of utils/slim.py::load_package) ----

def load_package(package_path):
    """Read a LEGACY package triplet from disk.

    Returns (toc_data, gpu_data, stream_data) as bytearrays.
    """
    with open(package_path, 'rb') as f:
        toc_data = bytearray(f.read())
    gpu_data = bytearray()
    stream_data = bytearray()
    if os.path.exists(package_path + ".gpu_resources"):
        with open(package_path + ".gpu_resources", 'rb') as f:
            gpu_data = bytearray(f.read())
    if os.path.exists(package_path + ".stream"):
        with open(package_path + ".stream", 'rb') as f:
            stream_data = bytearray(f.read())
    return toc_data, gpu_data, stream_data


# ---- toc structs (from __init__.py) ----

class TocFileType:
    def __init__(self, ID=0, NumFiles=0):
        self.unk1 = 0
        self.TypeID = ID
        self.NumFiles = NumFiles
        self.unk2 = 16
        self.unk3 = 64

    def Serialize(self, TocFile: MemoryStream):
        self.unk1 = TocFile.uint64(self.unk1)
        self.TypeID = TocFile.uint64(self.TypeID)
        self.NumFiles = TocFile.uint64(self.NumFiles)
        self.unk2 = TocFile.uint32(self.unk2)
        self.unk3 = TocFile.uint32(self.unk3)
        return self


class TocEntry:
    def __init__(self):
        self.FileID = self.TypeID = self.TocDataOffset = self.Unknown1 = \
            self.GpuResourceOffset = self.Unknown2 = self.TocDataSize = \
            self.GpuResourceSize = self.EntryIndex = self.StreamSize = \
            self.StreamOffset = 0
        self.Unknown3 = 16
        self.Unknown4 = 64
        self.TocData = self.TocData_OLD = b""
        self.GpuData = self.GpuData_OLD = b""
        self.StreamData = self.StreamData_OLD = b""
        self.IsModified = False

    def Serialize(self, TocFile: MemoryStream, Index=0):
        self.FileID = TocFile.uint64(self.FileID)
        self.TypeID = TocFile.uint64(self.TypeID)
        self.TocDataOffset = TocFile.uint64(self.TocDataOffset)
        self.StreamOffset = TocFile.uint64(self.StreamOffset)
        self.GpuResourceOffset = TocFile.uint64(self.GpuResourceOffset)
        self.Unknown1 = TocFile.uint64(self.Unknown1)
        self.Unknown2 = TocFile.uint64(self.Unknown2)
        self.TocDataSize = TocFile.uint32(len(self.TocData))
        self.StreamSize = TocFile.uint32(len(self.StreamData))
        self.GpuResourceSize = TocFile.uint32(len(self.GpuData))
        self.Unknown3 = TocFile.uint32(self.Unknown3)
        self.Unknown4 = TocFile.uint32(self.Unknown4)
        self.EntryIndex = TocFile.uint32(Index)
        return self

    def SerializeData(self, TocFile: MemoryStream, GpuFile, StreamFile):
        if TocFile.IsReading():
            TocFile.seek(self.TocDataOffset)
            self.TocData = bytearray(self.TocDataSize)
        elif TocFile.IsWriting():
            self.TocDataOffset = TocFile.tell()
        self.TocData = TocFile.bytes(self.TocData)

        if GpuFile.IsWriting():
            self.GpuResourceOffset = ceil(float(GpuFile.tell()) / 64) * 64
        if self.GpuResourceSize > 0:
            GpuFile.seek(self.GpuResourceOffset)
            if GpuFile.IsReading():
                self.GpuData = bytearray(self.GpuResourceSize)
            self.GpuData = GpuFile.bytes(self.GpuData)

        if StreamFile.IsWriting():
            self.StreamOffset = ceil(float(StreamFile.tell()) / 64) * 64
        if self.StreamSize > 0:
            StreamFile.seek(self.StreamOffset)
            if StreamFile.IsReading():
                self.StreamData = bytearray(self.StreamSize)
            self.StreamData = StreamFile.bytes(self.StreamData)
        if GpuFile.IsReading():
            self.TocData_OLD = bytearray(self.TocData)
            self.GpuData_OLD = bytearray(self.GpuData)
            self.StreamData_OLD = bytearray(self.StreamData)

    def GetData(self):
        return [self.TocData, self.GpuData, self.StreamData]

    def SetData(self, TocData, GpuData, StreamData, IsModified=True):
        self.TocData = TocData
        self.GpuData = GpuData
        self.StreamData = StreamData
        self.TocDataSize = len(self.TocData)
        self.GpuResourceSize = len(self.GpuData)
        self.StreamSize = len(self.StreamData)
        self.IsModified = IsModified


class StreamToc:
    def __init__(self):
        self.magic = TOC_MAGIC
        self.numTypes = self.numFiles = self.unknown = 0
        self.unk4Data = bytearray(56)
        self.TocTypes = []
        self.TocEntries = []
        self.TocDict = {}
        self.Path = ""
        self.Name = ""

    def Serialize(self, SerializeData=True):
        if self.TocFile.IsWriting():
            self.UpdateTypes()
        if len(self.TocFile.Data) == 0 and self.TocFile.IsReading():
            return False
        self.magic = self.TocFile.uint32(self.magic)
        if self.magic != TOC_MAGIC:
            return False
        self.numTypes = self.TocFile.uint32(len(self.TocTypes))
        if self.TocFile.IsReading():
            self.numFiles = self.TocFile.uint32(len(self.TocEntries))
        else:
            self.numFiles = self.TocFile.uint32(
                sum([len(e.keys()) for e in self.TocDict.values()]))
        self.unknown = self.TocFile.uint32(self.unknown)
        self.unk4Data = self.TocFile.bytes(self.unk4Data, 56)

        if self.TocFile.IsReading():
            self.TocTypes = [TocFileType() for _ in range(self.numTypes)]
            self.TocEntries = [TocEntry() for _ in range(self.numFiles)]
        self.TocTypes = [e.Serialize(self.TocFile) for e in self.TocTypes]
        TocEntryStart = self.TocFile.tell()
        if self.TocFile.IsReading():
            self.TocEntries = [e.Serialize(self.TocFile) for e in self.TocEntries]
            for entry in self.TocEntries:
                self.TocDict.setdefault(entry.TypeID, {})[entry.FileID] = entry
        else:
            Index = 1
            for Type in self.TocTypes:
                for Entry in self.TocDict[Type.TypeID].values():
                    Entry.Serialize(self.TocFile, Index)
                    Index += 1

        if SerializeData:
            for entries in self.TocDict.values():
                for FileEntry in entries.values():
                    FileEntry.SerializeData(self.TocFile, self.GpuFile, self.StreamFile)

        if self.TocFile.IsWriting():
            self.TocFile.seek(TocEntryStart)
            Index = 1
            for Type in self.TocTypes:
                for Entry in self.TocDict[Type.TypeID].values():
                    Entry.Serialize(self.TocFile, Index)
                    Index += 1
        return True

    def UpdateTypes(self):
        self.TocTypes = [TocFileType(t, len(self.TocDict[t])) for t in self.TocDict]

    def UpdatePath(self, path):
        self.Path = path
        self.Name = Path(path).name

    def FromFile(self, path, SerializeData=True):
        self.UpdatePath(path)
        toc_data, gpu_data, stream_data = load_package(path)
        self.TocFile = MemoryStream(toc_data)
        self.GpuFile = MemoryStream(gpu_data)
        self.StreamFile = MemoryStream(stream_data)
        return self.Serialize(SerializeData)

    def ToFile(self, path=None):
        self.TocFile = MemoryStream(IOMode="write")
        self.GpuFile = MemoryStream(IOMode="write")
        self.StreamFile = MemoryStream(IOMode="write")
        self.Serialize()
        if path is None:
            path = self.Path
        num_entries = sum(len(self.TocDict[k]) for k in self.TocDict)
        min_size = 256 * num_entries
        if len(self.TocFile.Data) < min_size:
            self.TocFile.Data.extend(bytearray(min_size - len(self.TocFile.Data)))
        with open(path, 'w+b') as f:
            f.write(bytes(self.TocFile.Data))
        with open(path + ".gpu_resources", 'w+b') as f:
            f.write(bytes(self.GpuFile.Data))
        with open(path + ".stream", 'w+b') as f:
            f.write(bytes(self.StreamFile.Data))

    def GetFileData(self, FileID, TypeID):
        try:
            return self.TocDict[TypeID][FileID].GetData()
        except KeyError:
            return None

    def GetEntry(self, FileID, TypeID):
        try:
            return self.TocDict[int(TypeID)][int(FileID)]
        except KeyError:
            return None

    def AddEntry(self, NewEntry, override=False):
        if not override and self.GetEntry(NewEntry.FileID, NewEntry.TypeID) is not None:
            raise Exception("Entry with same ID already exists")
        self.TocDict.setdefault(NewEntry.TypeID, {})[NewEntry.FileID] = NewEntry
        self.UpdateTypes()

    def RemoveEntry(self, FileID, TypeID):
        try:
            del self.TocDict[TypeID][FileID]
            self.UpdateTypes()
        except KeyError:
            pass


def load_friendly_names(path):
    """Load hashlist friendlynames.txt -> {file_id: name}."""
    names = {}
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0].isdigit():
                names[int(parts[0])] = parts[1].strip()
    return names
