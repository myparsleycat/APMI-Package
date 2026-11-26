"""Back up and deploy the AP Core into an existing user-selected XXMI package."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import uuid

ROOT = Path(__file__).resolve().parents[1]


def enable_constant_buffer_cache(rendering):
    setting = r'(?im)^([ \t]*cache_resource_data[ \t]*=[ \t]*)([^;\r\n]*)'

    def add_constant_buffer(match):
        flags = match[2].split()
        if {'all', 'constant_buffer'}.intersection(flag.lower() for flag in flags):
            return match[0]
        flags = [flag for flag in flags if flag.lower() != 'none']
        return match[1] + ' '.join([*flags, 'constant_buffer']) + (' ' if match[2].endswith(' ') else '')

    configured, count = re.subn(setting, add_constant_buffer, rendering)
    if count:
        return configured
    end = rendering.index('\n') + 1
    newline = '\r\n' if rendering[:end].endswith('\r\n') else '\n'
    return rendering[:end] + 'cache_resource_data = constant_buffer' + newline + rendering[end:]


parser = argparse.ArgumentParser()
parser.add_argument('target', type=Path)
args = parser.parse_args()
target = args.target.resolve()
if target == ROOT:
    raise ValueError('Target is the source package itself')
ini = target / 'd3dx.ini'
original = ini.read_bytes()
text = original.decode('utf-8-sig')
pattern = r'(?im)^(\s*include\s*=\s*)Core[\\/]\s*(?:EFMI|APMI)[\\/]main\.ini\s*$'
updated, count = re.subn(pattern, lambda m: m[1] + 'Core\\APMI\\main.ini', text)
if count != 1:
    raise ValueError('Expected one active EFMI/APMI Core include; no files changed')
rendering = r'(?im)^\[Rendering\][ \t]*\r?\n(?:(?!^\[)[\s\S])*'
updated, count = re.subn(rendering, lambda m: enable_constant_buffer_cache(m[0]), updated)
if count != 1:
    raise ValueError('Expected one Rendering section; no files changed')
for filename in ('d3d11.dll', 'd3dcompiler_47.dll'):
    if hashlib.sha256((target / filename).read_bytes()).digest() != hashlib.sha256((ROOT / filename).read_bytes()).digest():
        raise ValueError('Target runtime differs from the tested runtime: ' + filename)
backup = ROOT / 'build' / ('deployment-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6])
backup.mkdir(parents=True)
(backup / 'd3dx.ini').write_bytes(original)
shutil.copytree(target / 'Core', backup / 'Core')
shutil.copytree(ROOT / 'Core/APMI', target / 'Core/APMI', dirs_exist_ok=True)
for relative in ('Skinning.ini', 'Shaders/Skinning.hlsl'):
    # These files belonged to the first APMI prototype and are in the backup.
    old_file = target / 'Core/APMI' / relative
    old_file.unlink(missing_ok=True)
ini.write_text(updated, encoding='utf-8', newline='')
core_version = re.search(r'^data = "APMI ([^ "\r\n]+) \(F12: GUIDE\)"',
                         (target / 'Core/APMI/main.ini').read_text(encoding='utf-8-sig'), re.MULTILINE)
report = {'target': str(target), 'backup': str(backup),
          'core': 'APMIv1 ' + (core_version[1] if core_version else 'unknown'),
          'files': {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (target / 'Core/APMI').rglob('*') if p.is_file()},
          'previous_ini_sha256': hashlib.sha256(original).hexdigest(),
          'active_ini_sha256': hashlib.sha256(ini.read_bytes()).hexdigest()}
(backup / 'deployment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps({'target': str(target), 'backup': str(backup), 'files': len(report['files'])}))
