"""AP's observed D3D11 compute skinning, reproduced from its DXBC instructions."""
from __future__ import annotations

import struct

VARIANTS = {"3b4f1b1749cd3030": 1, "10749e66a6e6de89": 2, "09d91b2eee7e232f": 4}
STRIDES = {1: 4, 2: 16, 4: 32}
# Variable-influence shaders. Their blend is not a fixed-stride layout, so they are not in VARIANTS.
VARIABLE = {"38cddb8c0126726a"}
MAX_VARIABLE_INFLUENCES = 8


def decode_blend(data: bytes, influences: int, count: int):
    stride = STRIDES[influences]
    if len(data) < count * stride:
        raise ValueError("Blend buffer is shorter than the vertex count")
    for vertex in range(count):
        offset = vertex * stride
        if influences == 1:
            yield (1.0,), struct.unpack_from("<I", data, offset)
        else:
            yield (struct.unpack_from(f"<{influences}f", data, offset),
                   struct.unpack_from(f"<{influences}I", data, offset + influences * 4))


def decode_variable_blend(data: bytes, count: int):
    """Decode the native variable blend: a (count + 1) offset table in uint units,
    then one uint per influence with the palette index in the low 16 bits and a
    UNORM16 weight in the high 16 bits."""
    if len(data) % 4 or len(data) < (count + 1) * 4:
        raise ValueError("Variable blend buffer is shorter than its offset table")
    words = struct.unpack(f"<{len(data) // 4}I", data)
    offsets = words[:count + 1]
    if offsets[0] != count + 1 or offsets[count] != len(words):
        raise ValueError("Variable blend offset table does not match the vertex count")
    for vertex in range(count):
        start, end = offsets[vertex], offsets[vertex + 1]
        if not 1 <= end - start <= MAX_VARIABLE_INFLUENCES:
            raise ValueError(f"Vertex {vertex} has {end - start} influences")
        packed = words[start:end]
        yield tuple((word >> 16) / 65535 for word in packed), tuple(word & 0xFFFF for word in packed)


def skin(rest: bytes, blends, matrices: bytes, influences: int | None, count: int) -> bytes:
    """Skin `count` vertices. `blends` is a raw blend buffer in the layout for
    `influences`, or already decoded (weights, indices) pairs per vertex."""
    if len(rest) < count * 40 or len(matrices) % 64:
        raise ValueError("Invalid AP vertex or matrix buffer length")
    if isinstance(blends, (bytes, bytearray, memoryview)):
        if influences not in STRIDES:
            raise ValueError("Raw blend buffers need a fixed influence count")
        blends = decode_blend(blends, influences, count)
    bones = list(struct.iter_unpack("<16f", matrices))
    output = bytearray(count * 40)
    for vertex, (weights, indices) in enumerate(blends):
        if any(index >= len(bones) for index in indices):
            raise ValueError(f"Vertex {vertex} references a bone outside its component palette")
        matrix = [sum(bones[index][i] * weight for index, weight in zip(indices, weights)) for i in range(16)]
        original = struct.unpack_from("<10f", rest, vertex * 40)
        values = []
        for start in (0, 3, 6):
            values += [sum(original[start + axis] * matrix[axis * 4 + row] for axis in range(3))
                       + (matrix[12 + row] if start == 0 else 0) for row in range(3)]
        struct.pack_into("<10f", output, vertex * 40, *values, original[9])
    return bytes(output)
