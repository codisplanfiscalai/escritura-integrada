"""Promoção GHCR sem rede: identidade, gates, canais e falhas parciais."""
from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from scripts.ci import image_aliases as aliases

SOURCE = 'a' * 40
IMAGE_ID = 'sha256:' + 'c' * 64
RAW = json.dumps({'schemaVersion': 2, 'config': {'digest': IMAGE_ID}, 'layers': []}).encode()
DIGEST = 'sha256:' + hashlib.sha256(RAW).hexdigest()
MANIFEST = {'raw': RAW, 'digest': DIGEST, 'media_type': aliases.MEDIA_TYPES[0]}


def plan(stable=False):
    return {'schema_version': 1, 'repository': aliases.REPOSITORY,
            'version': '0.7.3' if stable else '0.8.0-dev.19', 'source_sha': SOURCE,
            'digest': DIGEST, 'release_run_id': 123, 'aliases': ['latest' if stable else 'develop']}


class FakeGitHub:
    repository = aliases.REPOSITORY
    base = '/repos/' + repository

    def __init__(self, value):
        self.plan = value
        self.branch = 'main' if value['aliases'] == ['latest'] else 'develop'
        self.head = SOURCE
        self.tag_head = SOURCE
        self.marker = {'version': value['version'], 'source_sha': SOURCE, 'run_id': 123}
        self.draft = False
        self.run_status, self.run_result = 'completed', 'success'
        self.jobs = [{'name': name, 'status': 'completed', 'conclusion': 'success'} for name in aliases.GATES]

    def ref(self, name):
        return {'sha': self.tag_head if name.startswith('tags/') else self.head}

    def commit_sha(self, reference):
        return reference['sha']

    def release(self, tag):
        return {'draft': self.draft, 'body': '<!-- escritura-ci:' + json.dumps(self.marker) + ' -->', 'html_url': 'https://github.com/example/release'}

    def file(self, path, sha):
        return self.plan['version'] + '\n'

    def request(self, method, path):
        return {'status': self.run_status, 'conclusion': self.run_result,
                'path': '.github/workflows/release.yml', 'head_branch': self.branch,
                'html_url': 'https://github.com/example/run'}

    def pages(self, *args, **kwargs):
        return iter(self.jobs)


class FakeRegistry:
    def __init__(self, value):
        self.values = {DIGEST: MANIFEST, value['version']: MANIFEST}
        self.writes = []
        self.fail_put = False

    def manifest(self, reference, missing=False):
        value = self.values.get(reference)
        if value is None and not missing:
            raise RuntimeError('Manifesto não encontrado.')
        return value

    def put_alias(self, alias, manifest):
        self.writes.append(alias)
        if self.fail_put:
            raise RuntimeError('Falha de envio simulada.')
        self.values[alias] = manifest


class ImageAliasTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name) / 'report.json'
        self.plan = plan()
        self.gh = FakeGitHub(self.plan)
        self.registry = FakeRegistry(self.plan)
        self.pull_calls = []

    def pull(self, reference, plan, image_id):
        self.pull_calls.append(reference)
        self.assertEqual(image_id, IMAGE_ID)
        return {'image_id': image_id, 'pull_verified': True}

    def promote(self, public=None):
        return aliases.promote(self.plan, self.gh, self.registry, public or self.registry, self.output, pull=self.pull)

    def test_channels_are_strict_even_if_override_is_supplied(self):
        self.assertEqual(aliases.validate_plan(plan()), 'develop')
        self.assertEqual(aliases.validate_plan(plan(True)), 'main')
        for bad in ({'aliases': ['latest'], 'allow_prerelease_latest': True}, {'aliases': ['develop', 'latest']}, {'aliases': ['other']}, {'aliases': ['develop', 'develop']}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                aliases.validate_plan(dict(plan(), **bad))
        with self.assertRaises(ValueError):
            aliases.validate_plan(dict(plan(True), aliases=['develop']))

    def test_invalid_plan_never_writes(self):
        for key, value in [('repository', 'other/repo'), ('source_sha', 'short'), ('digest', 'sha256:short'), ('release_run_id', True), ('version', ' latest '), ('version', '0.8.0-rc.1')]:
            with self.subTest(key=key):
                self.plan = dict(plan(), **{key: value})
                with self.assertRaises((ValueError, RuntimeError)):
                    self.promote()
                self.assertEqual(self.registry.writes, [])

    def test_success_copies_same_bytes_and_verifies_public_pull(self):
        report = self.promote()
        self.assertEqual(report['status'], 'published')
        self.assertEqual(self.registry.values['develop']['raw'], RAW)
        self.assertEqual(self.registry.writes, ['develop'])
        self.assertEqual(self.pull_calls, [aliases.GHCR_PREFIX + '@' + DIGEST, aliases.GHCR_PREFIX + ':develop'])
        self.assertTrue(report['aliases']['develop']['public_pullable'])
        self.assertEqual(self.registry.values[self.plan['version']]['digest'], DIGEST)

    def test_idempotent_alias_does_not_write(self):
        self.registry.values['develop'] = MANIFEST
        self.promote()
        self.assertEqual(self.registry.writes, [])

    def test_failure_before_mutation_has_report(self):
        self.gh.head = 'b' * 40
        with self.assertRaisesRegex(RuntimeError, 'head'):
            self.promote()
        report = json.loads(self.output.read_text())
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(self.registry.writes, [])

    def test_wrong_release_or_tag_does_not_write(self):
        for changed in ('marker', 'draft', 'tag_head'):
            self.gh = FakeGitHub(self.plan)
            if changed == 'marker':
                self.gh.marker['run_id'] = 999
            else:
                setattr(self.gh, changed, True if changed == 'draft' else 'b' * 40)
            with self.subTest(changed=changed), self.assertRaises(RuntimeError):
                self.promote()
            self.assertEqual(self.registry.writes, [])

    def test_failed_running_or_missing_gate_does_not_write(self):
        for state, result in [('in_progress', None), ('completed', 'failure')]:
            self.gh.run_status, self.gh.run_result = state, result
            with self.assertRaises(RuntimeError):
                self.promote()
        self.gh = FakeGitHub(self.plan)
        self.gh.jobs.pop()
        with self.assertRaisesRegex(RuntimeError, 'Gate'):
            self.promote()
        self.assertEqual(self.registry.writes, [])

    def test_changed_version_digest_does_not_write(self):
        self.registry.values[self.plan['version']] = dict(MANIFEST, digest='sha256:' + 'd' * 64)
        with self.assertRaisesRegex(RuntimeError, 'divergentes'):
            self.promote()
        self.assertEqual(self.registry.writes, [])

    def test_head_changed_after_pull_does_not_write(self):
        original = self.pull
        def pull(*args):
            self.gh.head = 'b' * 40
            return original(*args)
        self.pull = pull
        with self.assertRaisesRegex(RuntimeError, 'head'):
            self.promote()
        self.assertEqual(self.registry.writes, [])

    def test_uncertain_write_is_recorded_and_not_retried(self):
        self.registry.fail_put = True
        with self.assertRaisesRegex(RuntimeError, 'simulada'):
            self.promote()
        report = json.loads(self.output.read_text())
        self.assertEqual(self.registry.writes, ['develop'])
        self.assertEqual(report['aliases']['develop']['status'], 'writing')
        self.assertEqual(report['status'], 'failed')

    def test_failed_public_verification_preserves_published_status(self):
        public = FakeRegistry(self.plan)
        with self.assertRaisesRegex(RuntimeError, 'não encontrado'):
            self.promote(public)
        report = json.loads(self.output.read_text())
        self.assertEqual(report['aliases']['develop']['status'], 'published')
        self.assertEqual(report['aliases']['develop']['digest'], DIGEST)
        self.assertEqual(report['status'], 'failed')

    def test_pull_requires_exact_version_sha_id_platform_and_digest(self):
        good = {'Id': IMAGE_ID, 'Os': 'linux', 'Architecture': 'amd64',
                'RepoDigests': [aliases.GHCR_PREFIX + '@' + DIGEST],
                'Config': {'Labels': {'org.opencontainers.image.version': self.plan['version'], 'org.opencontainers.image.revision': SOURCE}}}
        mutations = [('Id', 'wrong'), ('Os', 'windows'), ('Architecture', 'arm64'), ('RepoDigests', [])]
        candidates = [good] + [dict(good, **{k: v}) for k, v in mutations]
        labels = copy.deepcopy(good)
        labels['Config']['Labels']['org.opencontainers.image.revision'] = 'b' * 40
        candidates.append(labels)
        for index, candidate in enumerate(candidates):
            result = subprocess.CompletedProcess([], 0, json.dumps([candidate]))
            with patch('scripts.ci.image_aliases.subprocess.run', return_value=result):
                if index == 0:
                    self.assertTrue(aliases.pull_identity('reference', self.plan, IMAGE_ID)['pull_verified'])
                else:
                    with self.assertRaises(RuntimeError):
                        aliases.pull_identity('reference', self.plan, IMAGE_ID)

    def test_operational_plans_and_workflow_are_isolated(self):
        root = Path(__file__).resolve().parents[1]
        for name, branch in [('develop', 'develop'), ('latest', 'main')]:
            value = json.loads((root / '.github' / ('ghcr-aliases-' + name + '.json')).read_text())
            self.assertEqual(aliases.validate_plan(value), branch)
            self.assertEqual(value['aliases'], [name])
        workflow = (root / '.github/workflows/image-aliases.yml').read_text()
        self.assertIn('branches: [ops/ghcr-aliases]', workflow)
        self.assertIn('group: escritura-release-mutations', workflow)
        self.assertNotIn('scripts.ci.release prepare', workflow)
        self.assertNotIn('scripts.ci.release sync-develop', workflow)
        self.assertNotIn('contents: write', workflow)

    def test_registry_only_treats_404_as_missing(self):
        registry = aliases.Registry()
        registry.token = 'synthetic-token'
        for status in (403, 404, 500):
            error = HTTPError('https://ghcr.io/example', status, 'synthetic', {}, io.BytesIO())
            with patch.object(registry.opener, 'open', side_effect=error):
                if status == 404:
                    self.assertIsNone(registry.manifest('develop', missing=True))
                else:
                    with self.assertRaises(RuntimeError):
                        registry.manifest('develop', missing=True)

    def test_registry_refuses_redirect_and_never_writes_versioned_tag(self):
        registry = aliases.Registry()
        registry.token = 'synthetic-token'
        error = HTTPError('https://ghcr.io/example', 307, 'redirect', {'Location': 'https://other.invalid'}, io.BytesIO())
        with patch.object(registry.opener, 'open', side_effect=error) as request:
            with self.assertRaises(RuntimeError):
                registry.manifest('develop')
            self.assertEqual(request.call_count, 1)
        with self.assertRaises(ValueError):
            registry.put_alias('0.8.0-dev.19', MANIFEST)

    def test_registry_put_network_error_is_not_retried(self):
        registry = aliases.Registry()
        registry.token = 'synthetic-token'
        with patch.object(registry.opener, 'open', side_effect=URLError('connection interrupted')) as request:
            with self.assertRaisesRegex(RuntimeError, 'incerto'):
                registry.put_alias('develop', MANIFEST)
            self.assertEqual(request.call_count, 1)

    def test_manifest_requires_exact_digest_and_supported_media_type(self):
        class Response(io.BytesIO):
            pass
        registry = aliases.Registry()
        registry.token = 'synthetic-token'
        for digest, media in [(DIGEST, aliases.MEDIA_TYPES[0]), ('sha256:' + 'e' * 64, aliases.MEDIA_TYPES[0]), (DIGEST, 'application/vnd.oci.image.index.v1+json')]:
            response = Response(RAW)
            response.headers = {'Docker-Content-Digest': digest, 'Content-Type': media}
            with patch.object(registry.opener, 'open', return_value=response):
                if digest == DIGEST and media in aliases.MEDIA_TYPES:
                    self.assertEqual(registry.manifest('develop')['raw'], RAW)
                else:
                    with self.assertRaises(RuntimeError):
                        registry.manifest('develop')


if __name__ == '__main__':
    unittest.main()
