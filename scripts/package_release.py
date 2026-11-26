"""Build the APMI release zip and, with --key, its signature and release body."""
import argparse
import base64
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATHS = ('d3dx.ini', 'LICENSE', 'Core/APMI')
# Matches the desktop app's importer version rule: "global $version = 0.30" is 0.3.0.
VERSION_PATTERN = re.compile(r'^global \$version = (\d+)\.*(\d)(\d*)')


def read_version():
    for line in (ROOT / 'Core/APMI/main.ini').read_text(encoding='utf-8-sig').splitlines():
        match = VERSION_PATTERN.match(line)
        if match:
            return f'{match[1]}.{match[2]}.{match[3] or "0"}'
    raise ValueError('Core/APMI/main.ini has no global $version line')


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


parser = argparse.ArgumentParser()
parser.add_argument('--key', type=Path, help='ECDSA P-384 private key PEM used to sign the zip')
parser.add_argument('--notes', default='', help='Release notes placed above the signature')
parser.add_argument('--allow-dirty', action='store_true')
args = parser.parse_args()

if not args.allow_dirty and git('status', '--porcelain', '--', *PACKAGE_PATHS).strip():
    raise SystemExit('Package files have uncommitted changes; commit them or pass --allow-dirty')
flags = ('--cached', '--others', '--exclude-standard') if args.allow_dirty else ('--cached',)
files = sorted({name for name in git('ls-files', '-z', *flags, '--', *PACKAGE_PATHS).split('\0') if name})
version = read_version()
out = ROOT / 'build' / 'release'
out.mkdir(parents=True, exist_ok=True)
archive = out / f'APMI-PACKAGE-v{version}.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for name in files:
        if (ROOT / name).is_file():
            zf.write(ROOT / name, name)
print(f'{archive} ({len(files)} files)')

if args.key:
    der = subprocess.run(['openssl', 'dgst', '-sha256', '-sign', str(args.key), str(archive)],
                         check=True, capture_output=True).stdout
    signature = base64.b64encode(der).decode('ascii')
    (out / f'{archive.name}.sig').write_text(signature + '\n', encoding='ascii')
    body = out / f'release-v{version}.md'
    notes = f'{args.notes.strip()}\n\n' if args.notes.strip() else ''
    body.write_text(f'## APMI {version}\n\n{notes}## Signature\n- {signature}\n', encoding='utf-8', newline='\n')
    print(f'{body}')
