"""Additional transform/tangent checks and a neutral geometry preview in Blender."""
import json
from pathlib import Path
import struct
import sys
import math
import bpy
from mathutils import Vector, Matrix

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from ap_tools.blender_io import export_project

args = sys.argv[sys.argv.index('--') + 1:]
project, blend, output = map(lambda p: Path(p).resolve(), args)
output.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=str(blend))
manifest = json.loads((project / 'project.json').read_text())
component = next(c for c in manifest['components'] if c['ib_hash'] == 'fdcaf230')
obj = next(o for o in bpy.context.scene.objects if o.get('ap_component') == component['id'])
obj.scale.x = -1
bpy.context.view_layer.update()
report = {'mirrored': export_project(project, output / 'mirrored')}
original = struct.unpack('<3I', (project / component['files']['indices']).read_bytes()[:12])
mirrored = json.loads((output / 'mirrored/export.json').read_text())
mesh = next(c for c in mirrored['components'] if c['id'] == component['id'])
actual = struct.unpack('<3I', (output / 'mirrored' / mesh['export_files']['indices']).read_bytes()[:12])
assert original == tuple(reversed(actual)), (original, actual)
obj.scale.x = 1
bpy.context.view_layer.update()
report['normals'] = export_project(project, output / 'normals', recalculate_normals=True)
for file in (output / 'normals/Meshes').glob('*-Position.buf'):
    records = list(struct.iter_unpack('<10f', file.read_bytes()))
    assert all(math.isfinite(value) for row in records for value in row), file

# Review the original geometry with AP's native Y-up coordinates retained.
objects = [o for o in bpy.context.scene.objects if o.get('ap_component')]
corners = [o.matrix_world @ Vector(c) for o in objects for c in o.bound_box]
lo = Vector(tuple(min(p[i] for p in corners) for i in range(3)))
hi = Vector(tuple(max(p[i] for p in corners) for i in range(3)))
center, size = (lo + hi) / 2, max(hi - lo)
camera_data = bpy.data.cameras.new('AP validation camera')
camera = bpy.data.objects.new('AP validation camera', camera_data)
bpy.context.scene.collection.objects.link(camera)
camera.location = center + Vector((size * 0.55, size * 0.1, size * 2.5))
forward = (center - camera.location).normalized()
right = forward.cross(Vector((0, 1, 0))).normalized()
up = right.cross(forward).normalized()
camera.rotation_euler = Matrix((right, up, -forward)).transposed().to_euler()
camera_data.type = 'ORTHO'
camera_data.ortho_scale = size * 1.3
scene = bpy.context.scene
scene.camera = camera
scene.render.engine = 'BLENDER_WORKBENCH'
scene.render.resolution_x, scene.render.resolution_y = 640, 800
scene.render.resolution_percentage = 100
scene.display.shading.light = 'STUDIO'
scene.display.shading.color_type = 'SINGLE'
scene.display.shading.single_color = (0.65, 0.70, 0.78)
scene.display.shading.show_shadows = True
scene.display.shading.show_cavity = True
scene.display.shading.background_type = 'WORLD'
scene.world.color = (0.035, 0.04, 0.055)
scene.render.filepath = str(output / 'preview.png')
bpy.ops.render.render(write_still=True)
report.update(passed=True, preview=scene.render.filepath, bounds=[list(lo), list(hi)], blender=bpy.app.version_string)
(output / 'result.json').write_text(json.dumps(report, indent=2))
print('APMI_GEOMETRY=' + json.dumps(report))
