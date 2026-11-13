"""Live-release alias promotion: provenance, full rechecks, assets and reruns."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.ci import develop_alias as auto
from scripts.ci import image_aliases as aliases
from scripts.image_tools import IMAGE_NAMES
from test_image_aliases import FakeGitHub, FakeRegistry, plan, SOURCE, DIGEST, IMAGE_ID, MANIFEST


class AutomaticGitHub(FakeGitHub):
    def __init__(self, value):
        super().__init__(value)
        self.main, self.pre = 'b' * 40, True
        self.run_status, self.run_result = 'in_progress', None
        self.run_extra = {'id': 123, 'run_attempt': 1, 'run_number': 22, 'head_sha': SOURCE,
                          'event': 'push', 'repository': {'full_name': self.repository},
                          'head_repository': {'full_name': self.repository}}
        for job in self.jobs:
            job.update(run_id=123, run_attempt=1, head_sha=SOURCE)
        self.assets, self.jobs_path = [], None

    def ref(self, name):
        return {'sha': self.main} if name == 'heads/main' else super().ref(name)

    def release(self, tag):
        return dict(super().release(tag), id=99, prerelease=self.pre)

    def request(self, method, path):
        return dict(super().request(method, path), **self.run_extra)

    def pages(self, path, **kwargs):
        if path.endswith('/assets'):
            return iter(self.assets)
        self.jobs_path = path
        return super().pages(path, **kwargs)


class DevelopAliasTests(unittest.TestCase):
    def setUp(self):
        self.p = plan()
        self.ci = {'schema': 'escritura-ci-plan/1', 'repository': aliases.REPOSITORY,
                   'branch': 'develop', 'channel': 'develop', 'tag': 'develop',
                   'version': self.p['version'], 'source_sha': SOURCE, 'trigger_sha': SOURCE,
                   'run_id': 123, 'run_attempt': 1, 'run_number': 22,
                   'proceed': True, 'needs_release': True, 'already_released': False}
        self.env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': aliases.REPOSITORY,
                    'GITHUB_REF': 'refs/heads/develop', 'GITHUB_JOB': 'promote-develop',
                    'GITHUB_WORKFLOW_REF': aliases.REPOSITORY + '/.github/workflows/release.yml@refs/heads/develop',
                    'GITHUB_EVENT_NAME': 'push', 'GITHUB_SHA': SOURCE,
                    'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_RUN_NUMBER': '22'}
        images = {}
        for name in IMAGE_NAMES:
            repo = aliases.GHCR_PREFIX + ('' if name == 'app' else '-' + name)
            images[name] = {'repository': repo, 'tag': self.p['version'], 'reference': repo + ':' + self.p['version'],
                            'digest': DIGEST, 'image_id': IMAGE_ID, 'public_pullable': True}
        self.images = {'schema_version': 1, 'channel': 'develop', 'version': self.p['version'],
                       'source_sha': SOURCE, 'platform': 'linux/amd64', 'status': 'published',
                       'public_pullable': True, 'images': images}
        self.pub = {'status': 'published', 'release_id': 99, 'version': self.p['version'], 'source_sha': SOURCE}
        self.gh, self.reg = AutomaticGitHub(self.p), FakeRegistry(self.p)
        self.reg.values['latest'] = dict(MANIFEST, digest='sha256:' + 'f' * 64)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / 'report.json'
        self.receipts = Path(self.tmp.name) / 'receipts'
        self.receipts.mkdir()
        self.pulls = []
        self.make_receipts()

    def make_receipts(self):
        prefix = 'EscrituraIntegrada-' + self.p['version'] + '-'
        name = prefix + 'app.zip'
        manifest = {'schema_version': 1,
                    **{k: self.ci[k] for k in ('repository', 'version', 'source_sha', 'channel', 'tag', 'run_id', 'run_number')},
                    'images': self.images['images'], 'assets': [{'name': name, 'size': 10, 'sha256': 'a' * 64}]}
        raw = json.dumps(manifest).encode()
        manifest_name, sums_name = prefix + 'manifest.json', prefix + 'SHA256SUMS.txt'
        sums = ('a' * 64 + '  ' + name + '\n' + hashlib.sha256(raw).hexdigest() + '  ' + manifest_name + '\n').encode()
        self.gh.assets = [{'name': name, 'state': 'uploaded', 'size': 10, 'digest': 'sha256:' + 'a' * 64}]
        for filename, data in ((manifest_name, raw), (sums_name, sums)):
            (self.receipts / filename).write_bytes(data)
            self.gh.assets.append({'name': filename, 'state': 'uploaded', 'size': len(data), 'digest': 'sha256:' + hashlib.sha256(data).hexdigest()})

    def context(self):
        return auto.DevelopContext(self.ci, self.images, self.pub, self.env, receipts=self.receipts)

    def pull(self, reference, plan, image_id):
        self.pulls.append(reference)
        return {'image_id': image_id, 'pull_verified': True}

    def promote(self, *, pull=None, public=None):
        return auto.promote(self.context(), self.gh, self.reg, public or self.reg, self.out, pull=pull or self.pull)

    def test_success_protected_snapshots_latest_projection_and_public_pull(self):
        old = copy.deepcopy(self.reg.values['latest'])
        report = self.promote()
        self.assertEqual(report['status'], 'published')
        self.assertEqual(self.reg.writes, ['develop'])
        self.assertEqual(self.reg.values['latest'], old)
        self.assertEqual(report['protected_before'], report['protected_after'])
        self.assertEqual(self.gh.jobs_path, self.gh.base + '/actions/runs/123/jobs')
        self.assertEqual(len(self.pulls), 2)

    def test_closed_cycle_before_or_during_pull_never_promotes(self):
        for during_pull in (False, True):
            self.setUp()
            before = copy.deepcopy(self.reg.values['latest'])
            if not during_pull:
                self.gh.main_version = '0.8.0'
            def pull(*args):
                self.gh.main_version = '0.8.0'
                return self.pull(*args)
            with self.subTest(during_pull=during_pull), self.assertRaisesRegex(RuntimeError, 'Ciclo develop encerrado'):
                self.promote(pull=pull)
            self.assertEqual(self.reg.writes, [])
            self.assertEqual(self.reg.values['latest'], before)

    def test_dynamic_main_latest_and_missing_latest_are_allowed(self):
        self.gh.main = 'd' * 40
        self.reg.values.pop('latest')
        self.assertEqual(self.promote()['status'], 'published')

    def test_github_context_and_plan_are_exact(self):
        for key, value in [('GITHUB_ACTIONS', 'false'), ('GITHUB_REPOSITORY', 'fork/repo'), ('GITHUB_REF', 'refs/heads/main'),
                           ('GITHUB_JOB', 'publish'), ('GITHUB_EVENT_NAME', 'pull_request'), ('GITHUB_RUN_ID', '124'),
                           ('GITHUB_RUN_ATTEMPT', '0'), ('GITHUB_RUN_NUMBER', '23'), ('GITHUB_SHA', 'e' * 40), ('GITHUB_WORKFLOW_REF', 'other')]:
            env = dict(self.env, **{key: value})
            with self.subTest(key=key), self.assertRaises((ValueError, RuntimeError)):
                auto.DevelopContext(self.ci, self.images, self.pub, env, receipts=self.receipts)
        self.assertEqual(self.reg.writes, [])

    def test_plan_images_publication_mismatches_block(self):
        for attr, key, value in [('ci', 'schema', 'bad'), ('ci', 'branch', 'main'), ('ci', 'run_id', True),
                                 ('ci', 'needs_release', False), ('images', 'source_sha', 'e' * 40),
                                 ('images', 'version', '0.8.0-dev.99'), ('images', 'status', 'validated'),
                                 ('images', 'public_pullable', False), ('pub', 'status', 'failed'),
                                 ('pub', 'version', '0.8.0-dev.99'), ('pub', 'source_sha', 'e' * 40)]:
            obj = getattr(self, attr); original = obj[key]; obj[key] = value
            with self.subTest(attr=attr, key=key), self.assertRaises((ValueError, RuntimeError)):
                self.promote()
            obj[key] = original
        self.assertEqual(self.reg.writes, [])

    def test_all_seven_gates_require_unique_completed_success(self):
        original = copy.deepcopy(self.gh.jobs)
        for index in range(len(original)):
            for variant in ('missing', 'duplicate', 'failure', 'in_progress'):
                self.gh.jobs = copy.deepcopy(original)
                if variant == 'missing': self.gh.jobs.pop(index)
                elif variant == 'duplicate': self.gh.jobs.append(self.gh.jobs[index])
                elif variant == 'failure': self.gh.jobs[index]['conclusion'] = 'failure'
                else: self.gh.jobs[index]['status'] = 'in_progress'
                with self.subTest(index=index, variant=variant), self.assertRaisesRegex(RuntimeError, 'Gate'):
                    self.promote()
        self.assertEqual(self.reg.writes, [])

    def test_run_identity_and_gate_provenance(self):
        for key, value in [('id', 124), ('head_sha', 'e' * 40), ('run_attempt', 2), ('head_branch', 'main'),
                           ('path', 'other.yml'), ('event', 'workflow_dispatch'), ('status', 'completed'),
                           ('conclusion', 'failure'), ('repository', {'full_name': 'fork/repo'}), ('head_repository', {'full_name': 'fork/repo'})]:
            original = dict(self.gh.run_extra); self.gh.run_extra[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): self.promote()
            self.gh.run_extra = original
        for changes in ({'run_id': 999}, {'run_attempt': 0}, {'run_attempt': 2}, {'head_sha': 'e' * 40}):
            original = dict(self.gh.jobs[0]); self.gh.jobs[0].update(changes)
            with self.subTest(changes=changes), self.assertRaisesRegex(RuntimeError, 'Gate'): self.promote()
            self.gh.jobs[0] = original
        self.assertEqual(self.reg.writes, [])

    def test_final_job_rerun_no_rebuild_and_latest_failure_wins(self):
        self.env['GITHUB_RUN_ATTEMPT'] = '2'; self.gh.run_extra['run_attempt'] = 2
        self.assertEqual(self.promote()['status'], 'published')
        self.reg.writes.clear()
        self.assertEqual(self.promote()['status'], 'published')
        self.assertEqual(self.reg.writes, [])
        self.gh.jobs[0].update(run_attempt=2, conclusion='failure')
        with self.assertRaisesRegex(RuntimeError, 'Gate'): self.promote()
        self.assertEqual(self.reg.writes, [])

    def mutate_proof(self, target):
        if target == 'tag': self.gh.tag_head = 'e' * 40
        elif target == 'head': self.gh.head = 'e' * 40
        elif target == 'marker_version': self.gh.marker['version'] = '0.8.0-dev.99'
        elif target == 'marker_source': self.gh.marker['source_sha'] = 'e' * 40
        elif target == 'marker_run': self.gh.marker['run_id'] = 124
        elif target == 'run': self.gh.run_status = 'completed'
        elif target == 'gate': self.gh.jobs[0]['conclusion'] = 'failure'
        elif target == 'asset': self.gh.assets.pop()
        elif target == 'main': self.gh.main = 'e' * 40
        elif target == 'latest': self.reg.values['latest'] = MANIFEST
        elif target == 'version_digest': self.reg.values[self.p['version']] = dict(MANIFEST, digest='sha256:' + 'e' * 64)
        else: raise AssertionError(target)

    def test_entire_proof_rechecked_after_slow_pull_before_any_put(self):
        for target in ('tag', 'head', 'marker_version', 'marker_source', 'marker_run', 'run', 'gate', 'asset', 'main', 'latest', 'version_digest'):
            self.setUp()
            def pull(*args):
                self.mutate_proof(target)
                return self.pull(*args)
            with self.subTest(target=target), self.assertRaises(RuntimeError): self.promote(pull=pull)
            self.assertEqual(self.reg.writes, [])

    def test_entire_proof_rechecked_after_put_without_rollback(self):
        for target in ('tag', 'head', 'marker_version', 'marker_source', 'marker_run', 'run', 'gate', 'asset', 'main', 'latest', 'version_digest'):
            self.setUp()
            original = self.reg.put_alias
            def put(*args):
                original(*args); self.mutate_proof(target)
            self.reg.put_alias = put
            with self.subTest(target=target), self.assertRaises(RuntimeError): self.promote()
            self.assertEqual(self.reg.writes, ['develop'])
            self.assertEqual(json.loads(self.out.read_text())['status'], 'failed')

    def test_prepared_commit_parent_and_trailers_are_exact(self):
        trigger = 'e' * 40
        self.ci['trigger_sha'] = self.env['GITHUB_SHA'] = self.gh.run_extra['head_sha'] = trigger
        for job in self.gh.jobs: job['head_sha'] = trigger
        commit = {'parents': [{'sha': trigger}], 'message': 'prepare\n\nEscritura-CI-Run: 123\nEscritura-CI-Trigger: ' + trigger}
        original = self.gh.request
        self.gh.request = lambda method, path: commit if '/git/commits/' in path else original(method, path)
        self.assertEqual(self.promote()['status'], 'published'); self.reg.writes.clear()
        for changes in ({'parents': [{'sha': SOURCE}]}, {'message': 'bad'}, {'parents': [{'sha': trigger}, {'sha': SOURCE}]}):
            good = copy.deepcopy(commit); commit.update(changes)
            with self.assertRaisesRegex(RuntimeError, 'preparado'): self.promote()
            commit.clear(); commit.update(good)
        self.assertEqual(self.reg.writes, [])

    def test_assets_uploaded_unique_complete_with_exact_hash_and_size(self):
        original = copy.deepcopy(self.gh.assets)
        for target in ('missing', 'duplicate', 'size', 'digest', 'state', 'extra_current'):
            self.gh.assets = copy.deepcopy(original)
            if target == 'missing': self.gh.assets.pop()
            elif target == 'duplicate': self.gh.assets.append(self.gh.assets[0])
            elif target == 'extra_current': self.gh.assets.append(dict(self.gh.assets[0], name=self.gh.assets[0]['name'] + '.extra'))
            elif target == 'size': self.gh.assets[0]['size'] = 99
            elif target == 'digest': self.gh.assets[0]['digest'] = 'sha256:' + 'e' * 64
            else: self.gh.assets[0]['state'] = 'starter'
            with self.subTest(target=target), self.assertRaises(RuntimeError): self.promote()
            self.assertEqual(self.reg.writes, [])
        self.gh.assets = original + [{'name': 'EscrituraIntegrada-0.8.0-dev.1-receipt.json'}]
        self.assertEqual(self.promote()['status'], 'published')
        self.assertEqual(len(self.gh.assets), 4)

    def test_receipts_identity_duplicate_entries_and_checksums(self):
        for target in ('run_id', 'version', 'source_sha', 'duplicate', 'checksum', 'manifest_digest'):
            self.make_receipts(); path = next(self.receipts.glob('*-manifest.json')); data = json.loads(path.read_text())
            if target == 'checksum':
                sums = next(self.receipts.glob('*-SHA256SUMS.txt')); sums.write_text(sums.read_text() + sums.read_text().splitlines()[0] + '\n')
            else:
                if target == 'duplicate': data['assets'].append(data['assets'][0])
                elif target == 'manifest_digest': data['created_at'] = 'changed'
                else: data[target] = 999 if target == 'run_id' else 'wrong'
                path.write_text(json.dumps(data))
            with self.subTest(target=target), self.assertRaises(ValueError): self.context()

    def test_uncertain_put_not_retried_and_failure_report(self):
        self.reg.fail_put = True
        with self.assertRaises(RuntimeError): self.promote()
        self.assertEqual(self.reg.writes, ['develop'])
        report = json.loads(self.out.read_text())
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(report['protected_before'], report['protected_after'])

    def test_public_source_and_alias_reads_required(self):
        public = FakeRegistry(self.p)
        public.values[DIGEST] = dict(MANIFEST, digest='sha256:' + 'e' * 64)
        with self.assertRaises(RuntimeError): self.promote(public=public)
        self.assertEqual(self.reg.writes, [])
        with self.assertRaises(RuntimeError): self.promote(public=FakeRegistry(self.p))
        self.assertEqual(self.reg.writes, ['develop'])
        self.assertEqual(json.loads(self.out.read_text())['status'], 'failed')

    def test_image_id_and_release_identity(self):
        for target in ('image_id', 'release_id', 'prerelease'):
            self.setUp()
            if target == 'image_id': self.images['images']['app']['image_id'] = 'sha256:' + 'e' * 64; self.make_receipts()
            elif target == 'release_id': self.pub['release_id'] = 100
            else: self.gh.pre = False
            with self.subTest(target=target), self.assertRaises(RuntimeError): self.promote()
            self.assertEqual(self.reg.writes, [])

    def test_automatic_registry_never_puts_latest_and_operational_requires_completed(self):
        for alias in ('latest', 'main', self.p['version']):
            with self.assertRaises(ValueError): auto.DevelopRegistry().put_alias(alias, MANIFEST)
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'}):
            with self.assertRaisesRegex(RuntimeError, 'original'):
                aliases.promote(self.p, self.gh, self.reg, self.reg, self.out, pull=self.pull)
        self.assertEqual(self.reg.writes, [])

    def test_workflow_develop_only_locked_minimal_permissions_fail_closed(self):
        text = (Path(__file__).resolve().parents[1] / '.github/workflows/release.yml').read_text()
        job = text.split('  promote-develop:\n')[1].split('  sync-develop:')[0]
        self.assertIn("github.ref == 'refs/heads/develop'", job)
        for gate in ('prepare', 'linux', 'windows', 'macos', 'docker', 'publish'):
            self.assertIn("needs." + gate + ".result == 'success'", job)
        for required in ('group: escritura-release-mutations', 'contents: read', 'actions: read', 'packages: write', '--receipts artifacts/release'):
            self.assertIn(required, job)
        report_upload = job.split('          name: develop-alias-report\n')[1]
        self.assertIn('          overwrite: true\n', report_upload)
        for forbidden in ('contents: write', 'continue-on-error', 'workflow_run', 'docker build', 'latest', 'run-id:', 'github-token:'):
            self.assertNotIn(forbidden, job)


if __name__ == '__main__':
    unittest.main()
