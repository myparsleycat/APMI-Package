"""Run with blender --background --factory-startup --python blender_ap.py -- ..."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy
from ap_tools.blender_io import import_project, export_project

parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['import', 'export', 'roundtrip'])
parser.add_argument('project', type=Path)
parser.add_argument('--blend', type=Path)
parser.add_argument('--out', type=Path)
parser.add_argument('--recalculate-normals', action='store_true')
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
if args.action in ('import', 'roundtrip'):
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    import_project(args.project)
    if args.blend:
        args.blend.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(args.blend.resolve()))
elif args.blend:
    bpy.ops.wm.open_mainfile(filepath=str(args.blend.resolve()))
if args.action in ('export', 'roundtrip'):
    if not args.out:
        raise ValueError('--out is required for export')
    result = export_project(args.project, args.out, args.recalculate_normals)
    print('APMI_RESULT=' + json.dumps(result))
