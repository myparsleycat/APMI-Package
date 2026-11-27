"""Back up and deploy the AP Core into an existing user-selected XXMI package."""
import argparse
from contextlib import ExitStack
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
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


def enable_legacy_skinning(ini):
    newline = '\r\n' if '\r\n' in ini else '\n'
    declaration = 'global $costume_mods = 1' + newline
    constants = re.search(r'(?im)^[ \t]*\[[ \t]*Constants[ \t]*\][ \t]*(\r?\n|$)'
                          r'((?:(?!^[ \t]*\[)[\s\S])*)', ini)
    if constants is None:
        return ini.rstrip('\r\n') + newline * 2 + '[Constants]' + newline + declaration
    if re.search(r'(?im)^[ \t]*global(?:[ \t]+persist(?:ent)?)*[ \t]+\$costume_mods[ \t]*(?:=|\r?$)',
                 constants[2]):
        return ini
    start = constants.start(2)
    return ini[:start] + ('' if constants[1] else newline) + declaration + ini[start:]


def activate_package(target, backup, updated_ini):
    ini = target / 'd3dx.ini'
    core = target / 'Core/APMI'
    backup_core = backup / 'Core/APMI'
    with TemporaryDirectory(prefix='.apmi-deploy-', dir=target) as folder:
        staging = Path(folder)
        if not core.resolve().is_relative_to(target) or not staging.resolve().is_relative_to(target):
            raise ValueError('Core and staging paths must stay within the target package')
        staged_core = staging / 'APMI'
        previous_core = staging / 'previous-APMI'
        staged_ini = staging / ini.name
        if backup_core.is_dir():
            shutil.copytree(backup_core, staged_core)
        shutil.copytree(ROOT / 'Core/APMI', staged_core, dirs_exist_ok=True)
        for relative in ('Skinning.ini', 'Shaders/Skinning.hlsl'):
            (staged_core / relative).unlink(missing_ok=True)
        staged_ini.write_text(updated_ini, encoding='utf-8', newline='')

        if ini.read_bytes() != (backup / ini.name).read_bytes():
            raise ValueError('d3dx.ini changed during preparation; no files changed')
        try:
            with ExitStack() as rollback:
                if core.exists():
                    core.replace(previous_core)
                    rollback.callback(previous_core.replace, core)
                staged_core.replace(core)
                rollback.callback(core.replace, staged_core)
                staged_ini.replace(ini)
                rollback.pop_all()
        except OSError as error:
            error.add_note(f'Original package files are backed up at {backup}')
            raise


def deploy_core(target):
    ini = target / 'd3dx.ini'
    original = ini.read_bytes()
    text = original.decode('utf-8-sig')
    pattern = r'(?im)^([ \t]*include[ \t]*=[ \t]*)Core[\\/][ \t]*(?:EFMI|APMI)[\\/]main\.ini(?=[ \t]*\r?$)'
    updated, count = re.subn(pattern, lambda m: m[1] + 'Core\\APMI\\main.ini', text)
    if count != 1:
        raise ValueError('Expected one active EFMI/APMI Core include; no files changed')
    rendering = r'(?im)^\[Rendering\][ \t]*\r?\n(?:(?!^\[)[\s\S])*'
    updated, count = re.subn(rendering, lambda m: enable_constant_buffer_cache(m[0]), updated)
    if count != 1:
        raise ValueError('Expected one Rendering section; no files changed')
    updated = enable_legacy_skinning(updated)
    for filename in ('d3d11.dll', 'd3dcompiler_47.dll'):
        if (hashlib.sha256((target / filename).read_bytes()).digest()
                != hashlib.sha256((ROOT / filename).read_bytes()).digest()):
            raise ValueError('Target runtime differs from the tested runtime: ' + filename)
    backup = ROOT / 'build' / ('deployment-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6])
    backup.mkdir(parents=True)
    (backup / ini.name).write_bytes(original)
    shutil.copytree(target / 'Core', backup / 'Core')
    activate_package(target, backup, updated)
    core = target / 'Core/APMI'
    core_version = re.search(r'^data = "APMI ([^ "\r\n]+) \(F12: GUIDE\)"',
                             (core / 'main.ini').read_text(encoding='utf-8-sig'), re.MULTILINE)
    report = {'target': str(target), 'backup': str(backup),
              'core': 'APMIv1 ' + (core_version[1] if core_version else 'unknown'),
              'files': {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in core.rglob('*') if p.is_file()},
              'previous_ini_sha256': hashlib.sha256(original).hexdigest(),
              'active_ini_sha256': hashlib.sha256(ini.read_bytes()).hexdigest()}
    (backup / 'deployment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return {'target': str(target), 'backup': str(backup), 'files': len(report['files'])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('target', type=Path)
    target = parser.parse_args().target.resolve()
    if target == ROOT:
        raise ValueError('Target is the source package itself')
    lock = target / '.apmi-deploy.lock'
    try:
        lock.touch(exist_ok=False)
    except FileExistsError as error:
        raise RuntimeError(f'Deployment lock already exists at {lock}') from error
    try:
        print(json.dumps(deploy_core(target)))
    finally:
        lock.unlink()


if __name__ == '__main__':
    main()
