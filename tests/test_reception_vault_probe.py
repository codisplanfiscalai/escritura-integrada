"""Exercise Docker fixture logic locally; this does not claim Docker execution."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.probes import reception_vault_fixture as fixture


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux fixture; not a portable DPAPI/Apple recovery')
class VaultProbeTests(unittest.TestCase):
    def test_fixture_recovers_two_companies_with_separate_key_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            for name in ('original', 'vault', 'missing', 'wrong', 'backup', 'key-copy', 'recovered', 'restored-vault'):
                (root / name).mkdir(mode=0o700)
            with patch.dict(os.environ, {'ESCRITURA_RECEPTION_VAULT_DIR': str(root / 'vault')}), patch.object(fixture, 'VAULT', root / 'vault'):
                self.assertEqual(2, fixture.seed(root / 'original')['companies'])
                self.assertFalse(fixture.check(root / 'original')['key_missing_refused'])
            for name, action in [('missing', lambda d: fixture.check(d, missing=True)), ('wrong', fixture.wrong_key)]:
                with patch.dict(os.environ, {'ESCRITURA_RECEPTION_VAULT_DIR': str(root / name)}), patch.object(fixture, 'VAULT', root / name):
                    self.assertTrue(action(root / 'original')['key_missing_refused'])
            with patch.object(fixture, 'VAULT', root / 'key-copy'):
                self.assertTrue(fixture.backup(root / 'backup', root / 'original', root / 'vault')['encrypted_database_backup'])
            with patch.dict(os.environ, {'ESCRITURA_RECEPTION_VAULT_DIR': str(root / 'restored-vault')}), patch.object(fixture, 'VAULT', root / 'restored-vault'):
                result = fixture.restore(root / 'recovered', root / 'backup', root / 'key-copy')
                self.assertEqual(2, result['companies'])
                self.assertFalse(result['key_missing_refused'])


if __name__ == '__main__':
    unittest.main()
