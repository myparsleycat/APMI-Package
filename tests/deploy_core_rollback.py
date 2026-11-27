"""Verify that an INI write failure restores the installed Core and permits a retry."""
from pathlib import Path
import runpy
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class DeploymentTest(unittest.TestCase):
    def test_failed_ini_activation_restores_core(self):
        with TemporaryDirectory(prefix='apmi-deploy-test-') as folder:
            source = Path(folder) / 'source'
            target = Path(folder) / 'target'
            for package in (source, target):
                (package / 'Core/APMI').mkdir(parents=True)
                for name in ('d3d11.dll', 'd3dcompiler_47.dll'):
                    (package / name).write_bytes(b'fixture runtime')
            (source / 'scripts').mkdir()
            script = source / 'scripts/deploy_core.py'
            shutil.copyfile(ROOT / 'scripts/deploy_core.py', script)
            (source / 'Core/APMI/main.ini').write_bytes(b'new core')
            (source / 'Core/APMI/API.ini').write_bytes(b'new API')
            core = target / 'Core/APMI'
            (core / 'main.ini').write_bytes(b'installed core')
            (core / 'Skinning.ini').write_bytes(b'old skinning')
            (core / 'custom.ini').write_bytes(b'custom')
            ini = target / 'd3dx.ini'
            original = b'[Include]\r\ninclude = Core\\APMI\\main.ini\r\n\r\n[Rendering]\r\n[Constants]\r\n'
            ini.write_bytes(original)

            replace = Path.replace
            write_text = Path.write_text

            def reject_active_replace(path, destination):
                if destination == ini:
                    raise PermissionError('fixture refused INI activation')
                return replace(path, destination)

            def reject_active_write(path, *args, **kwargs):
                if path == ini:
                    raise PermissionError('fixture refused INI activation')
                return write_text(path, *args, **kwargs)

            with patch.object(sys, 'argv', [str(script), str(target)]):
                with (
                    patch.object(Path, 'replace', reject_active_replace),
                    patch.object(Path, 'write_text', reject_active_write),
                    self.assertRaisesRegex(PermissionError, 'fixture refused INI activation'),
                ):
                    runpy.run_path(str(script), run_name='__main__')
                self.assertEqual(ini.read_bytes(), original)
                self.assertEqual({file.name: file.read_bytes() for file in core.iterdir()}, {
                    'main.ini': b'installed core', 'Skinning.ini': b'old skinning', 'custom.ini': b'custom',
                })
                runpy.run_path(str(script), run_name='__main__')

            self.assertEqual({file.name: file.read_bytes() for file in core.iterdir()}, {
                'main.ini': b'new core', 'API.ini': b'new API', 'custom.ini': b'custom',
            })
            self.assertIn(b'global $costume_mods = 1\r\n', ini.read_bytes())


if __name__ == '__main__':
    unittest.main()
