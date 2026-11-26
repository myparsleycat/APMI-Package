"""Validate a deployed round-trip mod from exact live AP buffers through MCP."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from ap_tools.skinning import skin

parser = argparse.ArgumentParser()
parser.add_argument('--launcher', required=True, type=Path)
parser.add_argument('--export', dest='exported', required=True, type=Path)
parser.add_argument('--out', required=True, type=Path)
args = parser.parse_args()
args.out.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(args.launcher / 'tests'))
from mcp_integration import McpClient

project = json.loads((args.exported / 'export.json').read_text())
components = project['components']


def exported_buffer(component, key, legacy_name):
    if 'export_files' in component:
        return (args.exported / component['export_files'][key]).read_bytes()
    return (args.exported / 'Meshes' / component['id'] / legacy_name).read_bytes()


by_rest = {hashlib.sha256(exported_buffer(c, 'rest', 'Position.buf')).hexdigest(): c for c in components}
by_ib = {}
for c in components:
    key = hashlib.sha256(exported_buffer(c, 'indices', 'Index.buf')).hexdigest()
    by_ib.setdefault(key, []).append(c)
client = McpClient(args.launcher / 'dist', args.launcher / 'dist/data/settings.json', args.out / 'captures')
report = {'core': project['minimum_core'], 'dispatches': [], 'draws': [], 'captures': []}


def raw(number, slot):
    result = client.call('apmi_read_buffer', draw=number, slot=slot, save=True, whole=True, count=1)
    assert result['exact'], result
    return Path(result['saved']).read_bytes()


def pose_error(actual, expected):
    assert len(actual) == len(expected), (len(actual), len(expected))
    return max(abs(a[0] - b[0]) for a, b in zip(struct.iter_unpack('<f', actual), struct.iter_unpack('<f', expected)))


try:
    report['status'] = client.call('apmi_status')
    for _ in range(5):
        capture = client.call('apmi_capture_frame', contents='buffers', cb_data=True, budget_mb=256)
        report['captures'].append(capture.splitlines()[0])
        dispatches = client.call('apmi_list_draws', origin='xxmi', call='Dispatch', limit=100)
        poses = {}
        for number in map(int, re.findall(r'^#(\d+)\s', dispatches, re.M)):
            detail = client.call('apmi_get_draw', draw=number)
            if not {'cs-t0', 'cs-t1', 'cs-t2'}.issubset(detail.get('textures', {})):
                continue
            rest = raw(number, 'cs-t0')
            component = by_rest.get(hashlib.sha256(rest).hexdigest())
            if component is None:
                continue
            blend, bones = raw(number, 'cs-t1'), raw(number, 'cs-t2')
            assert blend == exported_buffer(component, 'blend', 'Blend.buf')
            expected = skin(rest, blend, bones, component.get('runtime_influences', 4), component['export_vertices'])
            poses.setdefault(component['id'], []).append((number, expected))
            report['dispatches'].append({'draw': number, 'component': component['id'], 'bones_bytes': len(bones),
                                         'shaders': detail['shaders'], 'args': detail['args']})
        if poses:
            report['capture'] = capture
            break
    if not poses:
        raise AssertionError('No matching exported skinning dispatch in five captured frames')

    text = client.call('apmi_list_draws', origin='xxmi', limit=100)
    report['listing'] = text
    for number in map(int, re.findall(r'^#(\d+)\s+DrawIndexed(?:Instanced)?\s+xxmi\b', text, re.M)):
        possible = by_ib.get(hashlib.sha256(raw(number, 'ib')).hexdigest(), [])
        if not possible:
            continue
        detail = client.call('apmi_get_draw', draw=number)
        actual = raw(number, 'vb0')
        scored = []
        for candidate in possible:
            for dispatch, expected in poses.get(candidate['id'], []):
                if dispatch < number and len(expected) == len(actual):
                    scored.append((pose_error(actual, expected), candidate))
        assert scored, (number, [c['id'] for c in possible], 'no matching captured compute input')
        error, component = min(scored, key=lambda item: item[0])
        assert error < 1e-5, (component['id'], error)
        observed = next(p for p in component['passes'] if all(detail['shaders'].get(stage) == value for stage,value in p['shaders'].items()))
        draw_result = {'draw': number, 'component': component['id'], 'max_error': error,
                       'shaders': detail['shaders'], 'buffers_exact': True}
        for slot, sid in observed['bindings'].items():
            stream = next(s for s in component['streams'] if s['id'] == sid)
            if stream['role'] == 'previous' and project['schema'] >= 4:
                previous = next(expected for dispatch, expected in reversed(poses[component['id']]) if dispatch < number)
                previous_error = pose_error(raw(number, slot), previous)
                assert previous_error < 1e-5, (component['id'], previous_error)
                draw_result['previous_pose_error'] = previous_error
            if stream['role'] == 'attributes' and 'runtime_file' in stream:
                path = args.exported
                if 'export_files' not in component:
                    path = path / 'Meshes' / component['id']
                expected = (path / stream['runtime_file']).read_bytes()
                assert detail['vb'][slot]['stride'] == stream['runtime_stride'], (number, slot, detail)
                assert raw(number, slot) == expected, (number, slot, 'attribute mismatch')
        report['draws'].append(draw_result)
    if not report['dispatches'] or not report['draws']:
        raise AssertionError(f'No matching exported skinning and draw pair: {text.splitlines()[0]}')
    report['passed'] = True
    print(json.dumps({'passed': True, 'dispatches': len(report['dispatches']), 'draws': len(report['draws']),
                      'components': len(set(d['component'] for d in report['draws'])),
                      'max_error': max(d['max_error'] for d in report['draws'])}))
finally:
    client.call('apmi_session', action='release')
    client.close()
    (args.out / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
