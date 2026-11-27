"""Exercise the legacy output override in an isolated D3D11 runtime."""
import argparse
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SHADER = '''
RWByteAddressBuffer Output : register(u0);
Texture1D<float4> IniParams : register(t120);

[numthreads(1, 1, 1)]
void main() {
    Output.Store(0, IniParams.Load(int2(178, 0)).x ? 0x21 : 0x11);
}
'''
MOD = '''
[ShaderRegexFixtureSkinning]
shader_model = cs_5_0
pre run = CommandList\\APMIv1\\CheckSkinning

[TextureOverrideLegacyInput]
hash = 49b4669b
pre run = CommandList\\APMIv1\\CheckLegacySkinningOutput

[TextureOverrideLegacyOutput]
hash = 045f0633
handling = skip
clear = cs-u0 0x42
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', required=True, type=Path, help='Directory containing the XXMI DLLs')
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix='apmi-legacy-') as directory:
        runtime = Path(directory)
        mods = runtime / 'Mods'
        mods.mkdir()
        for dll in args.runtime.glob('*.dll'):
            shutil.copy2(dll, runtime / dll.name)
        if not (runtime / 'd3d11.dll').is_file():
            parser.error('--runtime must contain d3d11.dll')
        shutil.copy2(ROOT / 'build/skin_gpu.exe', runtime)
        shutil.copytree(ROOT / 'Core', runtime / 'Core')
        ini = (ROOT / 'd3dx.ini').read_text(encoding='utf-8')
        for key, value in (('target', 'skin_gpu.exe'), ('skip_early_includes_load', '0'), ('hunting', '0')):
            ini = re.sub(rf'(?m)^{key}[ \t]*=.*$', f'{key} = {value}', ini)
        (runtime / 'test.hlsl').write_text(SHADER, encoding='ascii')
        for name, size in (('blend.buf', 32), ('bones.buf', 64)):
            (runtime / name).write_bytes(bytes(size))

        cases = (
            ('enabled', 1, 0, True, 0x42),
            ('same output hash with different input', 1, 0, False, 0x21),
            ('disabled', 1, 1, True, 0x11),
            ('reenabled', 1, 2, True, 0x42),
            ('leave legacy disabled after two toggles', 0, 2, True, 0x11),
            ('missing global declaration', None, 0, True, 0x11),
        )
        for name, costume_mods, toggles, matched_input, expected in cases:
            declaration = '' if costume_mods is None else f'global $costume_mods = {costume_mods}\n'
            (runtime / 'd3dx.ini').write_text(ini.replace('global $costume_mods = 1\n', declaration), encoding='utf-8')
            # The output descriptor stays the same even when the input data changes.
            (runtime / 'rest.buf').write_bytes(bytes(40) if matched_input else b'\x01' + bytes(39))
            constants = '[Constants]\n' + 'run = CommandList\\APMIv1\\ToggleMods\n' * toggles
            if costume_mods is not None:
                constants += 'x178 = $costume_mods\n'
            (mods / 'Fixture.ini').write_text(
                constants + MOD, encoding='ascii')
            subprocess.run([str(runtime / 'skin_gpu.exe'), 'test.hlsl', 'rest.buf', 'blend.buf', 'bones.buf',
                            'result.buf'], cwd=runtime, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            actual, = struct.unpack_from('<I', (runtime / 'result.buf').read_bytes())
            assert actual == expected, f'{name}: GPU wrote {actual:#x}, expected {expected:#x}'
            print(f'{name}: GPU wrote {actual:#x}')


if __name__ == '__main__':
    main()
