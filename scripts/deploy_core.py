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
report = {'target': str(target), 'backup': str(backup), 'core': 'APMIv1 0.3.0',
          'files': {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (target / 'Core/APMI').rglob('*') if p.is_file()},
          'previous_ini_sha256': hashlib.sha256(original).hexdigest(),
          'active_ini_sha256': hashlib.sha256(ini.read_bytes()).hexdigest()}
(backup / 'deployment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps({'target': str(target), 'backup': str(backup), 'files': len(report['files'])}))
