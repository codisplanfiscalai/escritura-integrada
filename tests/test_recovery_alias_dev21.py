"""Narrow recovery alias guards, credential isolation and mutation boundaries."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from scripts.ci import recovery_alias_dev21 as recovery

IMAGE_ID = 'sha256:' + 'c' * 64
RAW = json.dumps({'config': {'digest': IMAGE_ID}}).encode()
MANIFEST = {'digest': recovery.IMAGE, 'raw': RAW}
SPEC = {'repository': recovery.REPOSITORY, 'source_sha': recovery.SOURCE,
        'version': recovery.VERSION, 'image_digest': recovery.IMAGE,
        'latest_digest_unchanged': recovery.LATEST, 'main_sha': recovery.MAIN,
        'original_run_id': recovery.ORIGINAL_RUN, 'original_run_attempt': 2}
ENV = {'GITHUB_ACTIONS': 'true', 'GITHUB_REF': 'refs/heads/' + recovery.BRANCH,
       'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': 'a' * 40}
PROOF = {'status': 'verified', 'version': recovery.VERSION, 'source_sha': recovery.SOURCE,
         'original_run_id': recovery.ORIGINAL_RUN, 'recovery_run_id': 123, 'recovery_sha': 'a' * 40,
         'assets': [{'name': 'EscrituraIntegrada-' + recovery.VERSION + '-manifest.json',
                     'size': 100, 'sha256': 'e' * 64}]}


class Registry:
    def __init__(self):
        self.values = {recovery.IMAGE: MANIFEST, recovery.VERSION: MANIFEST,
                       'latest': {'digest': recovery.LATEST}}
        self.writes = []

    def manifest(self, reference, missing=False):
        if missing:
            return self.values.get(reference)
        return self.values[reference]

    def put_alias(self, alias, manifest):
        self.writes.append(alias)
        self.values[alias] = manifest


class RecoveryAliasTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name) / 'alias.json'
        self.registry = Registry()
        self.spec = copy.deepcopy(SPEC)
        self.guard = patch.object(recovery, 'verify_recovery', return_value={'status': 'verified'})
        self.mock_guard = self.guard.start()
        self.addCleanup(self.guard.stop)
        self.pulls = []

    def pull(self, reference, plan, image_id):
        self.pulls.append((reference, os.environ.get('DOCKER_CONFIG')))
        self.assertEqual(image_id, IMAGE_ID)
        return {'image_id': image_id, 'pull_verified': True}

    def promote(self):
        return recovery.promote(self.spec, Mock(), self.registry, self.registry, self.output, pull=self.pull)

    def test_only_develop_is_written_with_real_anonymous_pull_context(self):
        with patch.dict(os.environ, {'DOCKER_CONFIG': '/original/config'}):
            result = self.promote()
            self.assertEqual(os.environ['DOCKER_CONFIG'], '/original/config')
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(self.registry.writes, ['develop'])
        self.assertEqual(len(self.pulls), 3)
        self.assertEqual(self.pulls[0][1], '/original/config')
        self.assertNotEqual(self.pulls[1][1], '/original/config')
        self.assertNotEqual(self.pulls[2][1], '/original/config')
        self.assertEqual(result['latest_before'], result['latest_after'])
        self.assertEqual(self.mock_guard.call_count, 2)

    def test_plan_rejects_other_version_digest_main_alias_and_attempt(self):
        for key, value in [('version', '0.8.0'), ('source_sha', 'b' * 40),
                           ('image_digest', recovery.LATEST), ('main_sha', 'b' * 40),
                           ('aliases', ['latest']), ('original_run_attempt', 1)]:
            with self.subTest(key=key):
                self.spec = dict(SPEC, **{key: value})
                with self.assertRaises(ValueError):
                    self.promote()
                self.assertFalse(self.registry.writes)

    def test_changed_latest_prevents_any_write(self):
        self.registry.values['latest'] = {'digest': recovery.IMAGE}
        with self.assertRaisesRegex(RuntimeError, 'latest changed'):
            self.promote()
        self.assertFalse(self.registry.writes)

    def test_changed_version_prevents_write(self):
        self.registry.values[recovery.VERSION] = {'digest': recovery.LATEST}
        with self.assertRaises(RuntimeError):
            self.promote()
        self.assertFalse(self.registry.writes)

    def test_guard_revocation_before_put_prevents_write(self):
        self.mock_guard.side_effect = [{}, RuntimeError('changed head')]
        with self.assertRaisesRegex(RuntimeError, 'changed head'):
            self.promote()
        self.assertFalse(self.registry.writes)

    def test_idempotent_already_promoted_is_verified_without_put(self):
        self.registry.values['develop'] = MANIFEST
        self.assertEqual(self.promote()['status'], 'verified')
        self.assertFalse(self.registry.writes)

    def test_uncertain_put_is_not_retried(self):
        self.registry.put_alias = Mock(side_effect=RuntimeError('uncertain result'))
        with self.assertRaises(RuntimeError):
            self.promote()
        self.registry.put_alias.assert_called_once()
        self.assertEqual(json.loads(self.output.read_text())['status'], 'failed')


class RecoveryProofTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, ENV)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.parent = SimpleNamespace(verify_original=Mock(), verify_heads=Mock(), verify_published=Mock())
        self.module_patch = patch.dict(sys.modules, {'scripts.ci.recover_dev21': self.parent})
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.gh = Mock(repository=recovery.REPOSITORY, base='/repos/' + recovery.REPOSITORY)
        self.gh.commit_sha.return_value = ENV['GITHUB_SHA']
        self.run_url = 'https://github.com/' + recovery.REPOSITORY + '/actions/runs/123'
        self.run = {'id': 123, 'run_attempt': 1, 'head_sha': ENV['GITHUB_SHA'],
                    'path': recovery.WORKFLOW, 'head_branch': recovery.BRANCH,
                    'status': 'in_progress', 'event': 'push', 'html_url': self.run_url}
        self.job = {'name': 'Recuperar assets dev.21', 'status': 'completed', 'conclusion': 'success'}
        self.asset = {'name': recovery.PROOF_NAME, 'digest': 'sha256:' + 'd' * 64}
        self.gh.request.return_value = self.run
        self.gh.release.return_value = {'id': 42, 'body': 'Recovery: ' + self.run_url}
        self.release_asset = {'name': PROOF['assets'][0]['name'], 'state': 'uploaded',
                              'size': 100, 'digest': 'sha256:' + 'e' * 64}
        self.assets = [self.asset, self.release_asset]
        self.gh.pages.side_effect = lambda path, **kwargs: [self.job] if path.endswith('/jobs') else self.assets
        self.proof_mock = patch.object(recovery, 'read_proof', return_value=copy.deepcopy(PROOF))
        self.proof = self.proof_mock.start()
        self.addCleanup(self.proof_mock.stop)

    def test_verified_original_and_current_recovery_are_both_required(self):
        result = recovery.verify_recovery(self.gh, SPEC)
        self.assertEqual(result['run_url'], self.run_url)
        self.parent.verify_original.assert_called_once_with(self.gh, SPEC)
        self.parent.verify_heads.assert_called_once_with(self.gh, SPEC)
        self.parent.verify_published.assert_called_once_with(self.gh, SPEC)

    def test_bad_workflow_and_original_job_failure_rejected(self):
        for key, value in [('path', '.github/workflows/other.yml'), ('event', 'workflow_dispatch'),
                           ('head_sha', 'b' * 40), ('run_attempt', 2)]:
            with self.subTest(key=key):
                self.gh.request.return_value = dict(self.run, **{key: value})
                with self.assertRaises(RuntimeError):
                    recovery.verify_recovery(self.gh, SPEC)
        self.gh.request.return_value = self.run
        self.job['conclusion'] = 'failure'
        with self.assertRaises(RuntimeError):
            recovery.verify_recovery(self.gh, SPEC)

    def test_receipt_from_another_run_or_source_rejected(self):
        for key, value in [('recovery_run_id', 9), ('source_sha', 'b' * 40), ('status', 'pending')]:
            with self.subTest(key=key):
                self.proof.return_value = dict(PROOF, **{key: value})
                with self.assertRaises(RuntimeError):
                    recovery.verify_recovery(self.gh, SPEC)

    def test_modified_deleted_extra_or_duplicate_remote_asset_rejected(self):
        for mode in ['digest', 'size', 'state', 'deleted', 'extra', 'duplicate']:
            original = copy.deepcopy(self.assets)
            with self.subTest(mode=mode):
                if mode == 'digest': self.assets[1]['digest'] = 'sha256:' + 'f' * 64
                elif mode == 'size': self.assets[1]['size'] = 99
                elif mode == 'state': self.assets[1]['state'] = 'new'
                elif mode == 'deleted': self.assets.pop()
                elif mode == 'extra': self.assets.append(dict(self.release_asset, name='unexpected'))
                elif mode == 'duplicate': self.assets.append(copy.deepcopy(self.release_asset))
                with self.assertRaises(RuntimeError):
                    recovery.verify_recovery(self.gh, SPEC)
            self.assets = original

    def test_invalid_or_duplicate_receipt_inventory_rejected(self):
        entry = PROOF['assets'][0]
        for inventory in [None, [], [entry, entry], [None],
                          [dict(entry, sha256='invalid')], [dict(entry, size=0)],
                          [dict(entry, name='another-version.zip')]]:
            with self.subTest(inventory=inventory):
                self.proof.return_value = dict(PROOF, assets=inventory)
                with self.assertRaises(RuntimeError):
                    recovery.verify_recovery(self.gh, SPEC)

    def test_receipt_and_link_are_mandatory(self):
        self.gh.release.return_value['body'] = ''
        with self.assertRaises(RuntimeError):
            recovery.verify_recovery(self.gh, SPEC)


class ReceiptDownloadTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.dumps(PROOF).encode()
        self.asset = {'id': 77, 'state': 'uploaded', 'size': len(self.raw),
                      'digest': 'sha256:' + hashlib.sha256(self.raw).hexdigest()}
        self.gh = SimpleNamespace(token='do-not-leak', base='/repos/' + recovery.REPOSITORY)

    def test_cross_host_redirect_strips_token(self):
        redirect = HTTPError('https://api.github.com/example', 302, 'redirect',
                             {'Location': 'https://release-assets.githubusercontent.com/a?signature=b'}, None)
        opener = Mock()
        opener.open.side_effect = [redirect, io.BytesIO(self.raw)]
        with patch.object(recovery, 'build_opener', return_value=opener):
            self.assertEqual(recovery.read_proof(self.gh, self.asset), PROOF)
        requests = [call.args[0] for call in opener.open.call_args_list]
        self.assertEqual(requests[0].get_header('Authorization'), 'Bearer do-not-leak')
        self.assertIsNone(requests[1].get_header('Authorization'))

    def test_unapproved_redirect_is_never_followed(self):
        opener = Mock()
        opener.open.side_effect = HTTPError('https://api.github.com/example', 302, 'redirect',
                                             {'Location': 'https://evil.example/a'}, None)
        with patch.object(recovery, 'build_opener', return_value=opener):
            with self.assertRaisesRegex(RuntimeError, 'redirect host'):
                recovery.read_proof(self.gh, self.asset)
        self.assertEqual(opener.open.call_count, 1)

    def test_wrong_receipt_hash_rejected(self):
        opener = Mock()
        opener.open.return_value = io.BytesIO(b'{}')
        with patch.object(recovery, 'build_opener', return_value=opener):
            with self.assertRaisesRegex(RuntimeError, 'size/hash'):
                recovery.read_proof(self.gh, self.asset)


if __name__ == '__main__':
    unittest.main()
