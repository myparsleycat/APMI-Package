"""Run in real Blender; validates original, edited and topology-changing exports."""
import json
from pathlib import Path
import struct
import sys

import bpy
import bmesh

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from ap_tools.blender_io import import_project, export_project

project_folder = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
output = Path(sys.argv[sys.argv.index('--') + 2]).resolve()
output.mkdir(parents=True, exist_ok=True)
project = json.loads((project_folder / 'project.json').read_text())
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
import_project(project_folder)
blend = output / 'imported.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(blend))
bpy.ops.wm.open_mainfile(filepath=str(blend))
baseline = output / 'unchanged'
report = {'blender': bpy.app.version_string, 'baseline': export_project(project_folder, baseline), 'checks': []}
baseline_components = {c['id']: c for c in json.loads((baseline / 'export.json').read_text())['components']}
for component in project['components']:
    files = {kind: project_folder / component['files'][kind] for kind in ('rest', 'blend', 'indices')}
    files.update({s['id']: project_folder / s['file'] for s in component['streams'] if s['role'] == 'attributes'})
    export_files = dict(baseline_components[component['id']]['export_files'])
    export_files.update({s['id']: s['export_file'] for s in baseline_components[component['id']]['streams']
                         if s['role'] == 'attributes'})
    for kind, original in files.items():
        actual = baseline / export_files[kind]
        data = actual.read_bytes()
        identical = original.read_bytes() == data
        report['checks'].append({'component': component['id'], 'buffer': kind, 'identical': identical})
        assert identical, (component['id'], kind)

target = next(c for c in project['components'] if c['ib_hash'] == 'fdcaf230')
obj = next(o for o in bpy.context.scene.objects if o.get('ap_component') == target['id'])
obj.data.vertices[0].co.x += 0.01
uv = obj.data.uv_layers[0]
uv.data[0].uv.x += 0.125
for group in obj.vertex_groups:
    group.remove([1])
bone = obj.vertex_groups.get('Bone_0000') or obj.vertex_groups.new(name='Bone_0000')
bone.add([1], 1.0, 'REPLACE')
bm = bmesh.new()
bm.from_mesh(obj.data)
bm.faces.ensure_lookup_table()
bmesh.ops.duplicate(bm, geom=[bm.faces[0]])
bm.to_mesh(obj.data)
bm.free()
obj.data.update()
modified = output / 'modified'
report['modified'] = export_project(project_folder, modified)
manifest = json.loads((modified / 'export.json').read_text())
changed = next(c for c in manifest['components'] if c['id'] == target['id'])
assert changed['export_indices'] == target['index_count'] + 3
assert changed['export_vertices'] >= target['vertex_count'] + 3
rest = (modified / changed['export_files']['rest']).read_bytes()
original_rest = (project_folder / target['files']['rest']).read_bytes()
assert abs(struct.unpack_from('<f', rest)[0] - struct.unpack_from('<f', original_rest)[0] - 0.01) < 1e-7
weights = (modified / changed['export_files']['blend']).read_bytes()
assert struct.unpack_from('<4f4I', weights, 32) == (1., 0., 0., 0., 0, 0, 0, 0)
for component in manifest['components']:
    files = component['export_files']
    assert (modified / files['rest']).stat().st_size == component['export_vertices'] * 40
    assert (modified / files['blend']).stat().st_size == component['export_vertices'] * 32
    raw = (modified / files['indices']).read_bytes()
    assert max(struct.unpack(f'<{len(raw)//4}I', raw)) < component['export_vertices']
    for stream in component['streams']:
        if stream['role'] == 'attributes' and stream['stride']:
            assert (modified / stream['export_file']).stat().st_size == component['export_vertices'] * stream['stride']

# Editing a shared color expands the zero-stride source into a per-vertex stream.
bpy.ops.wm.open_mainfile(filepath=str(blend))
hair = next(c for c in project['components'] if c['ib_hash'] == '978fe28d')
obj = next(o for o in bpy.context.scene.objects if o.get('ap_component') == hair['id'])
obj.data.color_attributes[0].data[0].color = (0.2, 0.3, 0.4, 1.)
report['expanded'] = export_project(project_folder, output / 'expanded')
expanded = json.loads((output / 'expanded/export.json').read_text())
result = next(c for c in expanded['components'] if c['id'] == hair['id'])
assert next(s for s in result['streams'] if s['role'] == 'attributes')['stride'] == 20

# Extra palette influences cannot be silently dropped.
bpy.ops.wm.open_mainfile(filepath=str(blend))
obj = next(o for o in bpy.context.scene.objects if o.get('ap_component') == target['id'])
for group in obj.vertex_groups:
    group.remove([0])
for index in range(5):
    name = f'Bone_{index:04d}'
    group = obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
    group.add([0], 0.2, 'REPLACE')
try:
    export_project(project_folder, output / 'invalid')
except ValueError as error:
    assert 'one to four' in str(error), error
    report['invalid_weights_rejected'] = str(error)
else:
    raise AssertionError('Five influences were silently exported')
report['passed'] = True
(output / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print('APMI_REGRESSION=' + json.dumps({'passed': True, 'byte_equal_buffers': len(report['checks']), 'output': str(output)}))
