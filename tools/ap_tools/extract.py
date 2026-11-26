"""Extract observed AP compute-skinned meshes from a frame analysis dump."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
import re
import shutil
import struct

from .frame_dump import parse_frame_dump
from .skinning import VARIANTS, decode_blend


def file_for(root, draw, slot, extension):
    entry = draw.slots.get(slot)
    files = [root / name for name in entry.files if name.endswith('.' + extension)] if entry else []
    if len(files) != 1 or not files[0].is_file():
        raise ValueError(f"Missing/ambiguous {draw.number:06d} {slot}.{extension}")
    return files[0]


def layout_of(path):
    text = path.read_text(encoding="utf-8", errors="strict").split("vertex-data:", 1)[0]
    header = {}
    for key in ("stride", "byte offset", "first vertex", "vertex count", "topology", "format", "first index", "index count"):
        match = re.search(r"^" + re.escape(key) + r":\s*(.+)$", text, re.M)
        if match:
            header[key] = int(match[1]) if match[1].isdigit() else match[1].strip()
    elements = []
    for block in re.split(r"element\[\d+\]:", text)[1:]:
        fields = dict(re.findall(r"^\s+(\w+):\s*(.+)$", block, re.M))
        elements.append(dict(semantic=fields["SemanticName"], index=int(fields["SemanticIndex"]),
                             format=fields["Format"], slot=int(fields["InputSlot"]),
                             offset=int(fields["AlignedByteOffset"]),
                             per_instance=fields["InputSlotClass"] != "per-vertex"))
    return header, elements


def inventory(path):
    path = Path(path).resolve()
    dump = parse_frame_dump(path)
    skinning = []
    for draw in dump.draws.values():
        if draw.call != "Dispatch" or draw.shaders.get("cs") not in VARIANTS:
            continue
        count, = struct.unpack_from("<I", file_for(path, draw, "cs-cb0", "buf").read_bytes())
        output = file_for(path, draw, "u0", "buf")
        skinning.append(dict(draw=draw, vertices=count, output=output.read_bytes(),
                             hash=draw.slots["u0"].hash, influences=VARIANTS[draw.shaders["cs"]]))
    groups, skipped = {}, []
    for draw in dump.draws.values():
        if draw.call not in ("DrawIndexed", "DrawIndexedInstanced") or "ib" not in draw.slots or "vb0" not in draw.slots:
            continue
        possible = [s for s in skinning if s["hash"] == draw.slots["vb0"].hash and s["draw"].number < draw.number]
        if not possible:
            continue
        posed = file_for(path, draw, "vb0", "buf").read_bytes()
        matches = [s for s in possible if s["output"] == posed]
        if len(matches) != 1:
            skipped.append(dict(draw=draw.number, reason="Compute-output identity is ambiguous or changed after skinning"))
            continue
        skin = matches[0]
        count = draw.args.get("IndexCount", draw.args.get("IndexCountPerInstance"))
        first = draw.args.get("StartIndexLocation", 0)
        key = (draw.slots["ib"].hash, count, first, skin["draw"].number)
        group = groups.setdefault(key, dict(key=key, skin=skin, draws=[]))
        group["draws"].append(draw)
    return dump, list(groups.values()), skipped


def extract(path, destination, ibs=(), textures=True):
    path, destination = Path(path).resolve(), Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Extraction destination must be new or empty")
    dump, groups, skipped = inventory(path)
    source_counts = Counter(group["skin"]["draw"].slots["cs-t0"].hash for group in groups)
    if ibs:
        groups = [g for g in groups if g["key"][0] in ibs]
    if not groups:
        raise ValueError("No unambiguous AP compute-skinned meshes match this selection")
    destination.mkdir(parents=True, exist_ok=True)
    report = dict(schema=1, game="AzurPromilia", source=str(path), hash_policy="whole_buffer",
                  geometry="compute skinning input snapshot", components=[], skipped=skipped)
    for component_id, group in enumerate(groups):
        ib_hash, index_count, first_index, _ = group["key"]
        skin = group["skin"]
        source, draws = skin["draw"], group["draws"]
        name = f"{ib_hash}_{first_index}_{index_count}"
        folder = destination / "meshes" / name
        folder.mkdir(parents=True)
        count = skin["vertices"]
        rest = file_for(path, source, "cs-t0", "buf").read_bytes()
        bones = file_for(path, source, "cs-t2", "buf").read_bytes()
        if len(rest) != count * 40 or len(bones) % 64:
            raise ValueError(f"{name}: unexpected AP skinning buffer size")
        blend = bytearray()
        for weights, indices in decode_blend(file_for(path, source, "cs-t1", "buf").read_bytes(), skin["influences"], count):
            if any(i >= len(bones) // 64 for i in indices):
                raise ValueError(f"{name}: invalid bone index")
            blend.extend(struct.pack("<4f4I", *(list(weights) + [0.] * (4-len(weights))),
                                     *(list(indices) + [0] * (4-len(indices)))))
        header, _ = layout_of(file_for(path, draws[0], "ib", "txt"))
        index_format = str(header.get("format", "")).removeprefix("DXGI_FORMAT_")
        if index_format not in ("R16_UINT", "R32_UINT"):
            raise ValueError(f"{name}: unsupported index format {index_format}")
        code, size = ("H", 2) if index_format == "R16_UINT" else ("I", 4)
        raw = file_for(path, draws[0], "ib", "buf").read_bytes()
        offset = header.get("byte offset", 0) + first_index * size
        indices = list(struct.unpack_from(f"<{index_count}{code}", raw, offset))
        base = draws[0].args.get("BaseVertexLocation", 0)
        indices = [i + base for i in indices]
        if index_count % 3 or min(indices) < 0 or max(indices) >= count:
            raise ValueError(f"{name}: invalid triangle index range")
        files = {"rest": rest, "blend": blend, "bones": bones,
                 "indices": struct.pack(f"<{len(indices)}I", *indices)}
        for key, data in files.items():
            (folder / (key + ".buf")).write_bytes(data)
        component = dict(id=name, component_id=component_id, ib_hash=ib_hash, vertex_count=count, index_count=index_count,
                         first_index=first_index, base_vertex=base, bone_count=len(bones)//64,
                         skin_dispatch=source.number, skin_shader=source.shaders["cs"],
                         source_hash=source.slots["cs-t0"].hash, blend_hash=source.slots["cs-t1"].hash,
                         shared_skinning=source_counts[source.slots["cs-t0"].hash] > 1,
                         output_hash=skin["hash"], output_bytes=len(skin["output"]),
                         influences=skin["influences"], streams=[], passes=[], textures=[],
                         files={k: str((folder / (k + ".buf")).relative_to(destination)).replace("\\", "/") for k in files})
        seen_streams, seen_textures = {}, set()
        for draw in draws:
            bindings = {}
            position_header, layout = layout_of(file_for(path, draw, "vb0", "txt"))
            # MCP also retains buffers that are bound but unused by this layout.
            for slot_number in sorted({e["slot"] for e in layout}):
                slot = f"vb{slot_number}"
                header = position_header if slot_number == 0 else layout_of(file_for(path, draw, slot, "txt"))[0]
                if header.get("topology") != "trianglelist":
                    raise ValueError(f"{name}: non-triangle topology")
                stream = file_for(path, draw, slot, "buf").read_bytes()
                stride = header["stride"]
                elements = [e for e in layout if e["slot"] == slot_number]
                if any(e["per_instance"] for e in elements):
                    raise ValueError(f"{name}: instanced vertex stream needs separate support")
                role = "current" if slot == "vb0" else "previous" if (
                    stride == 40 and any(e["semantic"] == "TEXCOORD" and e["format"] == "R32G32B32_FLOAT"
                                         and e["offset"] == 0 for e in elements)) else "attributes"
                key = (slot, stride, role, hashlib.sha256(stream).hexdigest() if role == "attributes" else "")
                if key not in seen_streams:
                    stream_id = f"stream{len(seen_streams)}"
                    entry = dict(id=stream_id, slot=int(slot[2:]), stride=stride, role=role, elements=elements,
                                 offset=header.get("byte offset", 0))
                    if role == "attributes":
                        stream_path = folder / (stream_id + ".buf")
                        stream_path.write_bytes(stream)
                        entry["file"] = str(stream_path.relative_to(destination)).replace("\\", "/")
                    component["streams"].append(entry)
                    seen_streams[key] = entry["id"]
                bindings[slot] = seen_streams[key]
            component["passes"].append(dict(draw=draw.number, call=draw.call, shaders=draw.shaders, bindings=bindings))
            for slot, entry in draw.slots.items():
                if not slot.startswith("ps-t"):
                    continue
                dds = next((path / f for f in entry.files if f.endswith('.dds')), None)
                if not dds or (slot, entry.hash) in seen_textures:
                    continue
                seen_textures.add((slot, entry.hash))
                data = dds.read_bytes()
                fmt = struct.unpack_from('<I', data, 128)[0] if data[84:88] == b'DX10' else None
                info = dict(slot=slot, hash=entry.hash, shader=draw.shaders.get('ps'), format=fmt, source=dds.name)
                if textures and fmt in (*range(70, 85), *range(94, 100)):
                    target = destination / 'textures' / (entry.hash + '.dds')
                    target.parent.mkdir(exist_ok=True)
                    if not target.exists():
                        shutil.copyfile(dds, target)
                    info['file'] = str(target.relative_to(destination)).replace('\\', '/')
                component['textures'].append(info)
        report['components'].append(component)
    (destination / 'project.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report
