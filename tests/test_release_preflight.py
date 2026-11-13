import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('preflight', ROOT / 'modules/release_preflight.py')
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)

class ReleasePreflightTests(unittest.TestCase):
    def test_missing_and_empty_sidecars_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(preflight.inspect_bundle(root)['bundle_files_ready'])
            for name in preflight.REQUIRED_FILES:
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b'x')
            self.assertTrue(preflight.inspect_bundle(root)['bundle_files_ready'])
            (root / 'cloud/niblit-cloud.exe').write_bytes(b'')
            self.assertFalse(preflight.inspect_bundle(root)['bundle_files_ready'])

    def test_cli_exits_before_any_boot_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # A boot import would fail: the isolated entrypoint only has the
            # preflight module and an otherwise empty modules package.
            (root / 'modules').mkdir()
            (root / 'modules/__init__.py').write_text('')
            (root / 'modules/release_preflight.py').write_bytes((ROOT / 'modules/release_preflight.py').read_bytes())
            (root / 'main.py').write_bytes((ROOT / 'main.py').read_bytes())
            before = sorted(str(p.relative_to(root)) for p in root.rglob('*'))
            result = subprocess.run([sys.executable, '-B', str(root / 'main.py'), '--release-preflight', str(root)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads(result.stdout)
            self.assertFalse(report['services_started'])
            self.assertFalse(report['orders_submitted'])
            self.assertEqual(before, sorted(str(p.relative_to(root)) for p in root.rglob('*')))

if __name__ == '__main__':
    unittest.main()
