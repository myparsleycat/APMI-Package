"""Blender 4.5 import/export of native AP skinning inputs and vertex attributes."""
from __future__ import annotations

import json
from pathlib import Path
import struct

import bpy

from .formats import unpack, pack_into
from .mod_export import write_mod


def read_project(folder):
    folder = Path(folder).resolve()
    project = json.loads((folder / 'project.json').read_text(encoding='utf-8'))
    if project.get('schema') != 1 or project.get('game') != 'AzurPromilia':
        raise ValueError('Unsupported AP project schema')
    return folder, project


def attributes(component):
    """One editable layer per physical element; layout aliases share that layer."""
    result = []
    for stream in component['streams']:
        if stream['role'] != 'attributes':
            continue
        seen = set()
        for element in stream['elements']:
            if element['semantic'] not in ('TEXCOORD', 'COLOR'):
                continue
            key = (element['offset'], element['format'])
            if key in seen:
                continue
            seen.add(key)
            result.append(dict(stream=stream, element=element,
                               name=f'{stream["id"]}_{element["semantic"]}{element["index"]}'))
    return result


def import_project(folder):
    folder, project = read_project(folder)
    collection = bpy.data.collections.new('Azur Promilia')
    bpy.context.scene.collection.children.link(collection)
    for component in project['components']:
        rest = (folder / component['files']['rest']).read_bytes()
        vertices = list(struct.iter_unpack('<10f', rest))
        raw = (folder / component['files']['indices']).read_bytes()
        indices = struct.unpack(f'<{len(raw)//4}I', raw)
        faces = [indices[i:i+3] for i in range(0, len(indices), 3)]
        mesh = bpy.data.meshes.new(component['id'])
        mesh.from_pydata([v[:3] for v in vertices], [], faces)
        mesh.update()
        mesh.normals_split_custom_set_from_vertices([v[3:6] for v in vertices])
        for polygon in mesh.polygons:
            polygon.use_smooth = True
        obj = bpy.data.objects.new(component['id'], mesh)
        collection.objects.link(obj)
        obj['ap_component'] = component['id']
        obj['ap_project'] = str(folder)
        obj['ap_bone_count'] = component['bone_count']
        mesh.attributes.new('ap_source_vertex', 'INT', 'POINT').data.foreach_set('value', range(len(vertices)))
        blend = (folder / component['files']['blend']).read_bytes()
        groups = {}
        for index, item in enumerate(struct.iter_unpack('<4f4I', blend)):
            combined = {}
            for weight, bone in zip(item[:4], item[4:]):
                if weight > 0:
                    combined[bone] = combined.get(bone, 0) + weight
            for bone, weight in combined.items():
                if bone not in groups:
                    groups[bone] = obj.vertex_groups.new(name=f'Bone_{bone:04d}')
                groups[bone].add([index], weight, 'REPLACE')
        buffers = {s['id']: (folder / s['file']).read_bytes() for s in component['streams'] if s['role'] == 'attributes'}
        for attribute in attributes(component):
            stream, element, name = attribute['stream'], attribute['element'], attribute['name']
            values = [unpack(buffers[stream['id']], stream['offset'] + i * stream['stride'] + element['offset'], element['format'])
                      for i in range(len(vertices))]
            if element['semantic'] == 'TEXCOORD' and len(values[0]) >= 2:
                layer = mesh.uv_layers.new(name=name)
                layer.data.foreach_set('uv', [value for loop in mesh.loops
                                             for value in (values[loop.vertex_index][0], 1-values[loop.vertex_index][1])])
            elif element['semantic'] == 'COLOR' and len(values[0]) == 4:
                layer = mesh.color_attributes.new(name=name, type='FLOAT_COLOR', domain='POINT')
                layer.data.foreach_set('color', [v for value in values for v in value])
        material = bpy.data.materials.new('AP captured material ' + component['ib_hash'])
        material.use_nodes = True
        material['ap_texture_evidence'] = json.dumps(component['textures'])
        material['ap_material_roles'] = 'unassigned; original game bindings are preserved on export'
        mesh.materials.append(material)
    bpy.context.scene['ap_project'] = str(folder)
    bpy.context.view_layer.update()
    return collection


def _weights(obj, vertex, original, bone_count):
    weights = {}
    for membership in vertex.groups:
        name = obj.vertex_groups[membership.group].name
        if not name.startswith('Bone_'):
            continue
        bone = int(name[5:])
        if bone < 0 or bone >= bone_count:
            raise ValueError(f'{obj.name}: bone {bone} is outside the component palette')
        if membership.weight > 0:
            weights[bone] = weights.get(bone, 0) + membership.weight
    source = struct.unpack('<4f4I', original)
    expected = {}
    for weight, bone in zip(source[:4], source[4:]):
        if weight > 0:
            expected[bone] = expected.get(bone, 0) + weight
    if weights.keys() == expected.keys() and all(abs(weights[k]-expected[k]) <= 1e-7 for k in weights):
        return original
    if not weights or len(weights) > 4:
        raise ValueError(f'{obj.name}: vertex {vertex.index} needs one to four nonzero bone weights')
    total = sum(weights.values())
    values = sorted(weights.items(), key=lambda item: (-item[1], item[0]))
    bones = [b for b, _ in values] + [0] * (4-len(values))
    amounts = [w/total for _, w in values] + [0.] * (4-len(values))
    return struct.pack('<4f4I', *amounts, *bones)


def export_project(folder, destination, recalculate_normals=False):
    folder, project = read_project(folder)
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Export destination must be new or empty')
    destination.mkdir(parents=True, exist_ok=True)
    exported = []
    for component in project['components']:
        objects = [o for o in bpy.context.scene.objects if o.type == 'MESH' and o.get('ap_component') == component['id']]
        if len(objects) != 1:
            raise ValueError(f'{component["id"]}: expected exactly one imported mesh object')
        obj = objects[0]
        if any(m.show_viewport for m in obj.modifiers):
            raise ValueError(f'{obj.name}: apply mesh modifiers before export')
        mesh = obj.data
        source_ids = mesh.attributes.get('ap_source_vertex')
        if not source_ids or source_ids.domain != 'POINT':
            raise ValueError(f'{obj.name}: source-vertex attribute was removed')
        mesh.calc_loop_triangles()
        specifications = attributes(component)
        original_rest = (folder / component['files']['rest']).read_bytes()
        original_blend = (folder / component['files']['blend']).read_bytes()
        original_attributes = {s['id']: (folder / s['file']).read_bytes() for s in component['streams'] if s['role'] == 'attributes'}
        out_rest, out_blend = bytearray(), bytearray()
        out_attributes = {key: bytearray() for key in original_attributes}
        output_strides = {s['id']: s['stride'] for s in component['streams'] if s['role'] == 'attributes'}
        tangent_uv = next((a['name'] for a in specifications if a['element']['semantic'] == 'TEXCOORD'
                           and a['stream']['stride'] and mesh.uv_layers.get(a['name'])), None)
        if recalculate_normals and tangent_uv:
            mesh.calc_tangents(uvmap=tangent_uv)
        transform = obj.matrix_world
        identity = all(abs(transform[r][c] - (1 if r == c else 0)) < 1e-7 for r in range(4) for c in range(4))
        normal_matrix = transform.to_3x3().inverted().transposed()
        records, keys = [], {}
        first_loop = {}
        for loop in mesh.loops:
            first_loop.setdefault(loop.vertex_index, loop.index)

        def encode(vertex_index, loop_index=None):
            vertex = mesh.vertices[vertex_index]
            source = source_ids.data[vertex_index].value
            if not 0 <= source < component['vertex_count']:
                raise ValueError(f'{obj.name}: vertex {vertex_index} has an invalid source reference')
            rest = bytearray(original_rest[source*40:(source+1)*40])
            position = transform @ vertex.co
            struct.pack_into('<3f', rest, 0, *position)
            if recalculate_normals:
                n = mesh.corner_normals[loop_index].vector if loop_index is not None else vertex.normal
                n = (normal_matrix @ n).normalized()
                struct.pack_into('<3f', rest, 12, *n)
                if tangent_uv and loop_index is not None:
                    loop = mesh.loops[loop_index]
                    tangent = (transform.to_3x3() @ loop.tangent).normalized()
                    sign = -loop.bitangent_sign * (-1 if transform.to_3x3().determinant() < 0 else 1)
                    struct.pack_into('<4f', rest, 24, *tangent, sign)
            elif not identity:
                from mathutils import Vector
                n = (normal_matrix @ Vector(struct.unpack_from('<3f', rest, 12))).normalized()
                t = (transform.to_3x3() @ Vector(struct.unpack_from('<3f', rest, 24))).normalized()
                struct.pack_into('<3f', rest, 12, *n)
                struct.pack_into('<3f', rest, 24, *t)
                if transform.to_3x3().determinant() < 0:
                    struct.pack_into('<f', rest, 36, -struct.unpack_from('<f', rest, 36)[0])
            blend = _weights(obj, vertex, original_blend[source*32:(source+1)*32], component['bone_count'])
            streams = {}
            for stream in component['streams']:
                if stream['role'] != 'attributes':
                    continue
                stride = stream['stride']
                raw = original_attributes[stream['id']]
                offset = stream['offset'] + source * stride
                streams[stream['id']] = bytearray(raw[offset:offset+stride] if stride else raw)
            for attribute in specifications:
                stream, element, name = attribute['stream'], attribute['element'], attribute['name']
                data = streams[stream['id']]
                offset = element['offset'] + (stream['offset'] if not stream['stride'] else 0)
                original = unpack(data, offset, element['format'])
                if element['semantic'] == 'TEXCOORD' and len(original) >= 2 and loop_index is not None:
                    layer = mesh.uv_layers.get(name)
                    if layer is None:
                        raise ValueError(f'{obj.name}: required UV layer {name} was removed')
                    uv = layer.data[loop_index].uv
                    values = (uv.x, 1-uv.y, *original[2:])
                elif element['semantic'] == 'COLOR' and len(original) == 4:
                    layer = mesh.color_attributes.get(name)
                    if layer is None or layer.domain != 'POINT':
                        raise ValueError(f'{obj.name}: required point color {name} was removed')
                    values = tuple(layer.data[vertex_index].color)
                else:
                    continue
                pack_into(data, offset, element['format'], values)
            return bytes(rest), blend, streams

        def add(vertex_index, loop_index=None):
            rest, blend, streams = encode(vertex_index, loop_index)
            key = (vertex_index, rest, blend, tuple((k, bytes(v)) for k,v in sorted(streams.items())))
            if key in keys:
                return keys[key]
            result = len(records)
            keys[key] = result
            records.append(vertex_index)
            out_rest.extend(rest)
            out_blend.extend(blend)
            for stream in component['streams']:
                if stream['role'] != 'attributes':
                    continue
                key = stream['id']
                if output_strides[key]:
                    out_attributes[key].extend(streams[key])
                elif out_attributes[key] and out_attributes[key] != streams[key]:
                    output_strides[key] = len(streams[key])
                    out_attributes[key] = out_attributes[key] * result + streams[key]
                else:
                    out_attributes[key] = bytearray(streams[key])
            return result

        # Retain unused vertices and stable numbering in unchanged projects.
        for vertex in mesh.vertices:
            add(vertex.index, first_loop.get(vertex.index))
        mirrored = transform.to_3x3().determinant() < 0
        indices = [add(mesh.loops[loop].vertex_index, loop) for triangle in mesh.loop_triangles
                   for loop in (tuple(reversed(triangle.loops)) if mirrored else triangle.loops)]
        if not indices:
            raise ValueError(f'{obj.name}: no triangles remain')
        output = destination / 'Meshes' / component['id']
        output.mkdir(parents=True)
        for name, data in {'rest': out_rest, 'blend': out_blend, 'indices': struct.pack(f'<{len(indices)}I', *indices), **out_attributes}.items():
            (output / (name + '.buf')).write_bytes(data)
        streams = [dict(s, stride=output_strides.get(s['id'], s['stride'])) for s in component['streams']]
        exported.append(dict(component, streams=streams, export_vertices=len(records), export_indices=len(indices)))
    write_mod(project, destination, exported)
    return dict(components=len(exported), vertices=sum(c['export_vertices'] for c in exported),
                indices=sum(c['export_indices'] for c in exported), output=str(destination))
