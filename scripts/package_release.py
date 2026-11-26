"""Build the APMI release zip and, with --key, its signature and release body."""
import argparse
import base64
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATHS = ('d3dx.ini', 'LICENSE', 'Core/APMI')
MAIN_INI = 'Core/APMI/main.ini'
# Matches the desktop app's importer version rule: "global $version = 0.30" is 0.3.0.
VERSION_PATTERN = re.compile(r'^global \$version = (\d+)\.*(\d)(\d*)')
SEMVER_PATTERN = re.compile(r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$')
VERSION_LINE = re.compile(r'^global \$version = [^\r\n]*', re.MULTILINE)
NOTIFICATION_LINE = re.compile(r'^data = "APMI [^"\r\n]* \(F12: GUIDE\)"', re.MULTILINE)
# Fixed entry timestamps make the archive bytes depend only on file contents.
ZIP_DATE = (1980, 1, 1, 0, 0, 0)


def read_version():
    for line in (ROOT / MAIN_INI).read_text(encoding='utf-8-sig').splitlines():
        match = VERSION_PATTERN.match(line)
        if match:
            return f'{match[1]}.{match[2]}.{match[3] or "0"}'
    raise ValueError(f'{MAIN_INI} has no global $version line')


def encode_version(version):
    """Return the main.ini float for X.Y.Z.

    Mods compare $required_version against $version as floats, so the minor and
    patch numbers must stay single digits: 0.3.10 would encode as 0.310 == 0.31.
    """
    match = SEMVER_PATTERN.match(version)
    if not match:
        raise SystemExit(f'Version {version!r} is not X.Y.Z')
    major, minor, patch = match.groups()
    if int(minor) > 9 or int(patch) > 9:
        raise SystemExit(f'Version {version} cannot be encoded in main.ini: minor and patch must be 0-9')
    return f'{major}.{minor}{patch}'


def versioned_main_ini(text, version):
    for pattern, replacement in ((VERSION_LINE, f'global $version = {encode_version(version)}'),
                                 (NOTIFICATION_LINE, f'data = "APMI {version} (F12: GUIDE)"')):
        text, count = pattern.subn(replacement, text)
        if count != 1:
            raise SystemExit(f'{MAIN_INI} must contain exactly one line matching {pattern.pattern!r}, found {count}')
    return text


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


parser = argparse.ArgumentParser()
parser.add_argument('--key', type=Path, help='ECDSA P-384 private key PEM used to sign the zip')
parser.add_argument('--version', help='Release version X.Y.Z written into the packaged main.ini; defaults to the version in main.ini')
notes_group = parser.add_mutually_exclusive_group()
notes_group.add_argument('--notes', default='', help='Release notes placed above the signature')
notes_group.add_argument('--notes-file', type=Path, help='UTF-8 file with release notes placed above the signature')
parser.add_argument('--output-dir', type=Path, default=ROOT / 'build' / 'release')
parser.add_argument('--allow-dirty', action='store_true')
args = parser.parse_args()

if not args.allow_dirty and git('status', '--porcelain', '--', *PACKAGE_PATHS).strip():
    raise SystemExit('Package files have uncommitted changes; commit them or pass --allow-dirty')
flags = ('--cached', '--others', '--exclude-standard') if args.allow_dirty else ('--cached',)
files = sorted({name for name in git('ls-files', '-z', *flags, '--', *PACKAGE_PATHS).split('\0') if name})
version = args.version or read_version()
out = args.output_dir
out.mkdir(parents=True, exist_ok=True)
archive = out / f'APMI-PACKAGE-v{version}.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for name in files:
        path = ROOT / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        if name == MAIN_INI and args.version:
            data = versioned_main_ini(data.decode('utf-8'), version).encode('utf-8')
        entry = zipfile.ZipInfo(name, date_time=ZIP_DATE)
        entry.compress_type = zipfile.ZIP_DEFLATED
        entry.external_attr = 0o644 << 16
        zf.writestr(entry, data, compresslevel=9)
print(f'{archive} ({len(files)} files)')

if args.key:
    der = subprocess.run(['openssl', 'dgst', '-sha256', '-sign', str(args.key), str(archive)],
                         check=True, capture_output=True).stdout
    signature = base64.b64encode(der).decode('ascii')
    (out / f'{archive.name}.sig').write_text(signature + '\n', encoding='ascii', newline='\n')
    body = out / f'release-v{version}.md'
    notes = (args.notes_file.read_text(encoding='utf-8') if args.notes_file else args.notes).strip()
    notes = f'{notes}\n\n' if notes else ''
    body.write_text(f'## APMI {version}\n\n{notes}## Signature\n- {signature}\n', encoding='utf-8', newline='\n')
    print(f'{body}')
