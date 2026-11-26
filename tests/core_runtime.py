"""Run generated INI against native Dispatch and DrawIndexed in a private XXMI worker."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from ap_tools.mod_export import write_mod


def only_call(client, origin, call, count=None, shader=None):
    args = {'origin': origin, 'call': call}
    if count is not None:
        args.update(min_index_count=count, max_index_count=count)
    if shader is not None:
        args['shader'] = shader
    text = client.call('apmi_list_draws', **args)
    numbers = re.findall(r'^#(\d+)\s', text, re.M)
    assert len(numbers) == 1, text
    return int(numbers[0])


def raw(client, draw, slot):
    result = client.call('apmi_read_buffer', draw=draw, slot=slot, count=1, save=True, whole=True)
    assert result['exact'], result
    return Path(result['saved']).read_bytes()


def skin_dispatches(client, origin):
    text = client.call('apmi_list_draws', origin=origin, call='Dispatch')
    numbers = [int(n) for n in re.findall(r'^#(\d+)\s', text, re.M)]
    matches = []
    for number in numbers:
        draw = client.call('apmi_get_draw', draw=number)
        if all(slot in draw.get('textures', {}) for slot in ('cs-t0', 'cs-t1', 'cs-t2')):
            matches.append(number)
    return matches


def set_motion_shader(runtime, motion_vs):
    (runtime / 'Mods' / 'Fixture.ini').write_text(
        f'[ShaderOverridePreviousPositionFixture]\nhash = {motion_vs}\nfilter_index = 2\n')


def start(fixture, mcp_case, client_type, shader, name, mod=None, motion_vs=None, *, instanced=False):
    folder, session, settings = mcp_case(name, frames=4000)
    runtime = Path(settings['RuntimeDirectory'])
    shutil.copy2(shader, folder / 'native-skin.cso')
    if mod:
        shutil.copytree(mod, runtime / 'Mods' / 'Model')
    if motion_vs:
        set_motion_shader(runtime, motion_vs)
    if instanced:
        ini = folder / 'APMIDx11Test.exe.ini'
        ini.write_text(ini.read_text(encoding='utf-16') + 'instanced=1\n', encoding='utf-16')
    worker = fixture.finish(fixture.launch(session), session, 'initialized')
    assert worker['McpReady'], worker
    settings_path = folder / 'settings.json'
    settings_path.write_text(json.dumps(settings))
    client = client_type(fixture.ROOT / 'dist', settings_path, folder / 'capture')
    return folder, runtime, worker['GamePid'], client


def export_mod(out, base, vertex_count, mixed_weights, draw_type='DrawIndexed'):
    mesh = out / 'Meshes' / 'test'
    mesh.mkdir(parents=True)
    positions = [(-0.25 + i / 256, 0, 0, 0, 0, 1, 1, 0, 0, 1) for i in range(vertex_count)]
    blend = (0.5, 0.5, 0., 0., 0, 1, 0, 0) if mixed_weights else (1., 0., 0., 0., 0, 0, 0, 0)
    indices = (0, 1, 2, 0, 2, vertex_count - 1)
    colors = struct.pack('<4f', 0.25, 0.5, 0.75, 1) * vertex_count
    (mesh / 'rest.buf').write_bytes(b''.join(struct.pack('<10f', *v) for v in positions))
    (mesh / 'blend.buf').write_bytes(struct.pack('<4f4I', *blend) * vertex_count)
    (mesh / 'indices.buf').write_bytes(struct.pack('<6I', *indices))
    (mesh / 'stream1.buf').write_bytes(colors)
    component = dict(base, id='test', vertex_count=3, index_count=3, first_index=0, base_vertex=0, bone_count=2,
                     influences=1, export_vertices=vertex_count, export_indices=6,
                     streams=[{'id': 'stream1', 'slot': 1, 'role': 'attributes', 'stride': 16, 'offset': 0},
                              {'id': 'stream2', 'slot': 3, 'role': 'previous', 'stride': 40}],
                     passes=[{'call': draw_type}])
    write_mod({'source': 'Owned D3D11 fixture'}, out, [component])
    ini = (out / 'mod.ini').read_text()
    assert '[TextureOverride_EntryPoint_Component0]' in ini and '[CommandList_Draw_Component0]' in ini
    assert f'Resource_{component["ib_hash"]}_3_0_Position' in ini
    assert not re.search(r'\b(?:cs-(?:t|cb|u)\d+|dispatch)\b', ini, re.I), ini
    return positions, colors, indices


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--launcher', required=True, type=Path)
    parser.add_argument('--native-shader', required=True, type=Path, help='Captured AP one-weight compute shader DXBC')
    args = parser.parse_args()
    os.environ['APMI_TEST_RUNTIME'] = str(ROOT)
    sys.path.insert(0, str(args.launcher.resolve() / 'tests'))
    import integration as fixture
    from mcp_integration import McpClient, mcp_case, show_fixture

    fixture.compile_fixtures()
    report = {'core': '0.2.2', 'scenarios': []}
    try:
        folder, runtime, pid, client = start(fixture, mcp_case, McpClient, args.native_shader, 'native-skin')
        try:
            capture = client.call('apmi_capture_frame', contents='buffers')
            draw = client.call('apmi_get_draw', draw=only_call(client, 'game', 'DrawIndexed', 3))
            native, = skin_dispatches(client, 'game')
            dispatch = client.call('apmi_get_draw', draw=native)
            base = {'ib_hash': draw['ib']['hash']}
            motion_vs = draw['shaders']['vs']
            report['native'] = dict(base, vs=motion_vs, cs=dispatch['shaders']['cs'], capture=capture)

            # Core creates the replacement buffers even when the original buffers already exist.
            export_mod(fixture.RUN / 'hot-load-mod', base, 65, False)
            shutil.copytree(fixture.RUN / 'hot-load-mod', folder / 'EFMI/Mods/Model')
            set_motion_shader(runtime, motion_vs)
            hide = show_fixture(pid)
            try:
                reload = client.call('apmi_reload_and_capture')
                assert reload['input']['key_down_observed'], reload
                client.call('apmi_capture_frame', contents='buffers')
                draw = only_call(client, 'xxmi', 'DrawIndexed', 6, shader=motion_vs)
                assert len(raw(client, draw, 'vb0')) == len(raw(client, draw, 'vb3')) == 65 * 40
                assert len(skin_dispatches(client, 'game')) == 1
                report['hot_reload'] = reload['capture']
            finally:
                hide()
        finally:
            client.close()

        for name, count, mixed in [('same-size', 3, False), ('expanded', 65, False),
                                   ('four-weight-shader', 65, True)]:
            draw_type = 'DrawIndexedInstanced' if mixed else 'DrawIndexed'
            mod = fixture.RUN / (name + '-mod')
            positions, colors, indices = export_mod(mod, base, count, mixed, draw_type)
            folder, runtime, pid, client = start(fixture, mcp_case, McpClient, args.native_shader,
                                                 name, mod, motion_vs, instanced=mixed)
            try:
                cap = client.call('apmi_capture_frame', contents='buffers')
                output = skin_dispatches(client, 'xxmi')
                if len(output) != 2:
                    listing = client.call('apmi_list_draws', call='Dispatch')
                    report['dispatch_details'] = [
                        client.call('apmi_get_draw', draw=int(n))
                        for n in re.findall(r'^#(\d+)\s', listing, re.M)
                    ]
                assert len(output) == 2, (output, cap)
                assert len(skin_dispatches(client, 'game')) == 1
                draw = only_call(client, 'xxmi', draw_type, 6, shader=motion_vs)
                assert 'no draw matches' in client.call('apmi_list_draws', origin='game', call=draw_type,
                                                         shader=motion_vs, min_index_count=3, max_index_count=3)
                if mixed:
                    details = client.call('apmi_get_draw', draw=draw)
                    assert details['args']['instance_count'] == 2 and details['args']['first_instance'] == 1, details
                pose = raw(client, draw, 'vb0')
                previous = raw(client, draw, 'vb3')
                assert len(pose) == len(previous) == count * 40, (len(pose), len(previous), count)
                assert raw(client, draw, 'vb1') == colors
                assert struct.unpack('<6I', raw(client, draw, 'ib')) == indices
                actual = list(struct.iter_unpack('<10f', pose))
                history = list(struct.iter_unpack('<10f', previous))
                translation = actual[0][0] - positions[0][0]
                assert abs(abs(translation) - 0.25) < 1e-6, translation
                error = max(abs(a - b) for arr, x in [(actual, translation), (history, -translation)]
                            for v, p in zip(arr, positions)
                            for a, b in zip(v, (p[0] + x, p[1] + (0.25 if mixed else 0), *p[2:])))
                assert error < 1e-6, (name, error)
                log = (runtime / 'd3d11_log.txt').read_text(errors='replace')
                assert not re.search(r'WARNING|ERROR|Failed to|Unrecognized', log, re.I), log[-2000:]
                report['scenarios'].append(dict(name=name, capture=cap, dispatch=output, draw=draw, draw_type=draw_type,
                                                vertices=count, current_bytes=len(pose), previous_bytes=len(previous),
                                                max_error=error))
                if name == 'expanded':
                    hide = show_fixture(pid)
                    try:
                        off = client.call('apmi_toggle_mods', state='off')
                        assert not off['mods_enabled'], off
                        client.call('apmi_capture_frame', contents='buffers')
                        only_call(client, 'game', 'DrawIndexed', 3)
                        assert len(skin_dispatches(client, 'game')) == 1
                        report['mods_off'] = off['state_evidence']
                    finally:
                        hide()
            finally:
                client.close()
        report['passed'] = True
    finally:
        fixture.cleanup()
        file = fixture.RUN / 'core-evidence.json'
        file.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print('Evidence:', file, flush=True)


if __name__ == '__main__':
    main()
