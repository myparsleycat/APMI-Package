"""Exact scalar packing for the vertex formats observed in AP captures."""
import re
import struct


def specification(fmt):
    match = re.fullmatch(r"(R\d+(?:G\d+)?(?:B\d+)?(?:A\d+)?)_(FLOAT|UNORM|SNORM|UINT|SINT)", fmt)
    if not match:
        raise ValueError(f"Unsupported vertex format {fmt}")
    bits = [int(n) for n in re.findall(r"\d+", match[1])]
    if len(set(bits)) != 1:
        raise ValueError(f"Packed vertex format needs explicit support: {fmt}")
    kind, width = match[2], bits[0]
    codes = {"FLOAT": {16: "e", 32: "f"}, "UNORM": {8: "B", 16: "H"},
             "SNORM": {8: "b", 16: "h"}, "UINT": {8: "B", 16: "H", 32: "I"},
             "SINT": {8: "b", 16: "h", 32: "i"}}
    try:
        code = codes[kind][width]
    except KeyError as exc:
        raise ValueError(f"Unsupported vertex format {fmt}") from exc
    return "<" + str(len(bits)) + code, kind, width


def unpack(data, offset, fmt):
    code, kind, width = specification(fmt)
    values = struct.unpack_from(code, data, offset)
    if kind == "UNORM":
        return tuple(x / ((1 << width) - 1) for x in values)
    if kind == "SNORM":
        return tuple(max(-1, x / ((1 << (width - 1)) - 1)) for x in values)
    return values


def pack_into(data, offset, fmt, values):
    code, kind, width = specification(fmt)
    original = unpack(data, offset, fmt)
    if len(values) != len(original):
        raise ValueError(f"Wrong element size for {fmt}")
    if all(abs(a-b) <= 2e-7 for a,b in zip(values, original)):
        return  # preserve original bytes through Blender's float32 UV conversions
    if kind == "UNORM":
        values = [round(max(0, min(1, v)) * ((1 << width) - 1)) for v in values]
    elif kind == "SNORM":
        values = [round(max(-1, min(1, v)) * ((1 << (width - 1)) - 1)) for v in values]
    elif kind in ("UINT", "SINT"):
        values = [round(v) for v in values]
    struct.pack_into(code, data, offset, *values)
