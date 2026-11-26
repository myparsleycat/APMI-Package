"""AP's observed D3D11 compute skinning, reproduced from its DXBC instructions."""
from __future__ import annotations

import struct

VARIANTS = {"3b4f1b1749cd3030": 1, "10749e66a6e6de89": 2, "09d91b2eee7e232f": 4}
STRIDES = {1: 4, 2: 16, 4: 32}


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


def skin(rest: bytes, blends: bytes, matrices: bytes, influences: int, count: int) -> bytes:
    if len(rest) < count * 40 or len(matrices) % 64:
        raise ValueError("Invalid AP vertex or matrix buffer length")
    bones = list(struct.iter_unpack("<16f", matrices))
    output = bytearray(count * 40)
    for vertex, (weights, indices) in enumerate(decode_blend(blends, influences, count)):
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
