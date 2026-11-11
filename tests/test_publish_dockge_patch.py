"""The operational publisher adds assets, never deletes/replaces originals."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts.ci import publish_dockge_patch as pub


class PublisherSafetyTests(unittest.TestCase):
    def plan(self):
        return {'id': 7, 'tag': 'v0.7.3', 'version': '0.7.3', 'source_sha': 'a' * 40,
                'assets': [{'id': 8, 'name': 'original.zip', 'size': 3, 'sha256': 'b' * 64,
                            'url': f'https://github.com/{pub.REPO}/releases/download/v0.7.3/original.zip'}]}

    def release(self):
        p = self.plan()
        return {'id': 7, 'tag_name': p['tag'], 'draft': False, 'immutable': False,
                'body': 'Version 0.7.3 source ' + p['source_sha'],
                'assets': [{'id': 8, 'name': 'original.zip', 'size': 3,
                            'digest': 'sha256:' + 'b' * 64, 'browser_download_url': p['assets'][0]['url']}]}

    def test_original_release_verified_by_id_sha_size_and_tag(self):
        with patch.object(pub, 'gh', side_effect=[self.release(), {'object': {'type': 'commit', 'sha': 'a' * 40}}]):
            self.assertEqual(pub.verify_release(self.plan())['id'], 7)

    def test_replaced_original_rejected(self):
        value = self.release()
        value['assets'][0]['id'] = 9
        with patch.object(pub, 'gh', side_effect=[value, {'object': {'type': 'commit', 'sha': 'a' * 40}}]):
            with self.assertRaisesRegex(ValueError, 'asset identity'):
                pub.verify_release(self.plan())

    def test_moved_tag_rejected(self):
        with patch.object(pub, 'gh', side_effect=[self.release(), {'object': {'type': 'commit', 'sha': 'c' * 40}}]):
            with self.assertRaisesRegex(ValueError, 'tag changed'):
                pub.verify_release(self.plan())

    def test_immutable_and_draft_releases_rejected(self):
        for field in ('immutable', 'draft'):
            value = self.release()
            value[field] = True
            with patch.object(pub, 'gh', return_value=value):
                with self.assertRaisesRegex(ValueError, 'mutable published'):
                    pub.verify_release(self.plan())

    def test_download_rejects_arbitrary_host_before_network(self):
        with patch.object(pub.urllib.request, 'urlopen') as network:
            with self.assertRaises(ValueError):
                pub.download('https://example.test/asset.zip')
            network.assert_not_called()

    def test_publish_requires_operational_branch(self):
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_REF': 'refs/heads/main'}, clear=True):
            with self.assertRaisesRegex(ValueError, 'operational'):
                pub.publish({}, Path('missing'), 'a' * 40)

    def test_different_existing_supplement_is_never_overwritten(self):
        data = b'new supplement'
        name = 'file-dockge-r1.zip'
        target = self.plan()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / target['tag']).mkdir()
            (output / target['tag'] / name).write_bytes(data)
            summary = {'tool_commit': 'c' * 40, 'releases': [{'id': target['id'], 'tag': target['tag'],
                'files': [{'name': name, 'sha256': pub.digest(data), 'size': len(data)}]}]}
            (output / 'publication.json').write_text(json.dumps(summary))
            live = self.release()
            live['assets'].append({'name': name, 'browser_download_url': 'public-source'})
            with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_REF': 'refs/heads/ops/dockge-release-patches'}, clear=True), patch.object(pub, 'verify_release', return_value=live), patch.object(pub, 'download', return_value=b'different'), patch.object(pub.subprocess, 'run') as mutation:
                with self.assertRaisesRegex(ValueError, 'no deletion or overwrite'):
                    pub.publish({'releases': [target]}, output, 'c' * 40)
                mutation.assert_not_called()


if __name__ == '__main__':
    unittest.main()
