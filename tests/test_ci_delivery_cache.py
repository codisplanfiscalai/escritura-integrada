"""Synthetic negative proofs for delivery, immutable reuse and run-bound handoff."""
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_images as builds
from image_handoff import verify_handoff
from image_tools import image_plan, sha256_file, write_json
from scripts.ci.delivery_policy import delivery_mode, desktop_enabled
from scripts.ci.ghcr_publication import receipt
from scripts.ci.release import validate_plan, publish, ReleaseError
from scripts.ci.cleanup_actions import cleanup, select_caches
from scripts.ci.github_api import GitHubError
import test_develop_alias as full
from test_ci_artifacts_cache import CacheGitHub, cache, NOW


def release_env(job='publish'):
    return {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'codisplanfiscalai/escritura-integrada',
            'GITHUB_REF': 'refs/heads/develop', 'GITHUB_EVENT_NAME': 'push',
            'GITHUB_WORKFLOW_REF': 'codisplanfiscalai/escritura-integrada/.github/workflows/release.yml@refs/heads/develop',
            'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_JOB': job}


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.plan = image_plan((ROOT / 'VERSION').read_text().strip(), 'develop', 'a' * 40)
        self.env = release_env()
        self.manifest = copy.deepcopy(self.plan)
        self.manifest.update(status='validated', smoke={'status': 'passed'})
        self.archive()

    def archive(self, *, wrong_platform=False, extra_tag=False, wrong_revision=False):
        records = []
        with tarfile.open(self.dir / 'images.tar.gz', 'w:gz') as out:
            def add(name, raw):
                item = tarfile.TarInfo(name); item.size = len(raw)
                out.addfile(item, io.BytesIO(raw))
            for name, image in self.manifest['images'].items():
                labels = {'io.escritura.content-id': image['content_id'],
                          'org.opencontainers.image.version': self.plan['version'],
                          'org.opencontainers.image.revision': ('b' if wrong_revision else 'a') * 40}
                raw = json.dumps({'os': 'linux', 'architecture': 'arm64' if wrong_platform else 'amd64',
                                  'config': {'Labels': labels}}).encode()
                image['image_id'] = 'sha256:' + hashlib.sha256(raw).hexdigest()
                file = image['image_id'][7:] + '.json'; add(file, raw)
                records.append({'Config': file, 'RepoTags': [image['reference']] + (['unexpected:tag'] if extra_tag else []), 'Layers': []})
            add('manifest.json', json.dumps(records).encode())
        archive = self.dir / 'images.tar.gz'
        write_json(self.dir / 'handoff.json', {'schema': 'escritura-image-handoff/1', 'run_id': '123', 'run_attempt': '1',
                   'manifest': self.manifest, 'archive_sha256': sha256_file(archive), 'archive_size': archive.stat().st_size})

    def check(self, plan=None, env=None, run_id='123'):
        return verify_handoff(self.dir, plan or self.plan, run_id, env or self.env)

    def test_exact_run_and_rerun_accept_same_validated_images(self):
        result, archive = self.check()
        self.assertEqual(result['images'], self.manifest['images'])
        self.assertTrue(archive.is_file())
        self.check(env=dict(self.env, GITHUB_RUN_ATTEMPT='2'))

    def test_changed_commit_version_catalog_platform_or_build_inputs_fail(self):
        for key, value in [('source_sha', 'b' * 40), ('version', '9.9.9-dev.99'),
                           ('catalog_sha256', 'b' * 64), ('platform', 'linux/arm64')]:
            with self.subTest(key=key):
                changed = copy.deepcopy(self.plan); changed[key] = value
                with self.assertRaises(ValueError): self.check(plan=changed)
        changed = copy.deepcopy(self.plan); changed['images']['minio']['content_id'] = 'f' * 64
        with self.assertRaises(ValueError): self.check(plan=changed)

    def test_cross_run_pr_context_and_future_attempt_are_rejected(self):
        for values in ({'GITHUB_RUN_ID': '124'}, {'GITHUB_EVENT_NAME': 'pull_request'},
                       {'GITHUB_REF': 'refs/pull/1/merge'}, {'GITHUB_REPOSITORY': 'fork/other'},
                       {'GITHUB_RUN_ATTEMPT': '0'}, {'GITHUB_WORKFLOW_REF': 'other.yml'}, {'GITHUB_JOB': 'linux'}):
            with self.subTest(values=values), self.assertRaises(ValueError): self.check(env=dict(self.env, **values))
        with self.assertRaises(ValueError): self.check(run_id='124', env=dict(self.env, GITHUB_RUN_ID='124'))

    def test_corrupt_archive_bad_config_and_extra_tags_block_before_load(self):
        archive = self.dir / 'images.tar.gz'; original = archive.read_bytes()
        archive.write_bytes(original + b'tamper')
        with self.assertRaisesRegex(ValueError, 'corrompido'): self.check()
        for values in ({'wrong_platform': True}, {'extra_tag': True}, {'wrong_revision': True}):
            self.archive(**values)
            with self.subTest(values=values), self.assertRaises(ValueError): self.check()

    def test_failed_smoke_cannot_be_consumed(self):
        self.manifest['smoke']['status'] = 'failed'; self.archive()
        with self.assertRaises(ValueError): self.check()


class DeliveryTests(unittest.TestCase):
    def fixture(self):
        value = full.DevelopAliasTests(); value.setUp(); self.addCleanup(value.doCleanups)
        value.ci['delivery_mode'] = 'ghcr_only'; value.images['smoke'] = {'status': 'passed'}
        env = dict(value.env, GITHUB_JOB='publish')
        value.pub = receipt(value.ci, value.images, env)
        return value

    def test_pause_applies_only_develop_and_resume_is_explicit(self):
        self.assertFalse(desktop_enabled('develop'))
        for base in ('main', 'feature/chained', ''): self.assertTrue(desktop_enabled(base))
        with patch('scripts.ci.delivery_policy.DEVELOP_DESKTOP_ENABLED', True):
            self.assertEqual(delivery_mode('develop'), 'full')
            self.assertTrue(desktop_enabled('develop'))
        value = self.fixture(); value.ci.update(branch='main', channel='production', tag='v1.0.0', version='1.0.0')
        with self.assertRaises(ValueError): validate_plan(value.ci)

    def test_ghcr_promotion_keeps_live_head_run_and_non_desktop_gates(self):
        value = self.fixture()
        # No GitHub release/assets are required in the GHCR-only path.
        value.gh.release = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('GitHub release accessed'))
        context = value.context()
        result = full.auto.promote(context, value.gh, value.reg, value.reg, value.out, pull=value.pull)
        self.assertEqual(result['status'], 'published')
        self.assertEqual(value.reg.writes, ['develop'])
        self.assertEqual(result['protected_before'], result['protected_after'])

    def test_missing_failed_or_foreign_general_gate_never_promotes(self):
        for mutation in ('missing', 'failed', 'foreign'):
            value = self.fixture()
            job = next(j for j in value.gh.jobs if j['name'] == 'Linux, testes e interface')
            if mutation == 'missing': value.gh.jobs.remove(job)
            elif mutation == 'failed': job['conclusion'] = 'failure'
            else: job['run_id'] = 124
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                full.auto.promote(value.context(), value.gh, value.reg, value.reg, value.out, pull=value.pull)
            self.assertEqual(value.reg.writes, [])

    def test_receipt_rejects_cross_run_images_sha_main_and_stale_digest(self):
        for field, wrong in [('run_id', 124), ('images_sha256', 'f' * 64), ('source_sha', 'b' * 40), ('run_attempt', 2)]:
            value = self.fixture(); value.pub[field] = wrong
            with self.subTest(field=field), self.assertRaises(ValueError): value.context()
        value = self.fixture()
        value.images['images']['app']['digest'] = 'sha256:' + 'f' * 64
        with self.assertRaises(ValueError): value.context()
        with self.assertRaisesRegex(ReleaseError, 'suspensa'): publish(value.gh, value.ci, value.receipts, value.images)

    def test_head_advancing_still_blocks_develop_without_mutation(self):
        value = self.fixture(); value.gh.head = 'c' * 40
        with self.assertRaises(RuntimeError):
            full.auto.promote(value.context(), value.gh, value.reg, value.reg, value.out, pull=value.pull)
        self.assertEqual(value.reg.writes, [])


class CacheSafetyTests(unittest.TestCase):
    def test_open_pr_cache_is_kept_even_after_retention(self):
        remote = CacheGitHub([cache(1, 'refs/pull/55/merge'), cache(2, 'refs/heads/obsolete')])
        original = remote.pages
        def pages(path, **kwargs):
            if path.endswith('/pulls'): return iter([{'number': 55}])
            return original(path, **kwargs)
        remote.pages = pages
        result = cleanup(remote, execute=True, now=NOW)
        self.assertEqual(result['deleted'], [2])

    def test_access_changed_or_new_run_between_each_delete_is_preserved(self):
        remote = CacheGitHub([cache(1, 'refs/heads/old'), cache(2, 'refs/heads/old2')])
        original = remote.pages
        def pages(path, **kwargs):
            if remote.deletes:
                remote.entries[1]['last_accessed_at'] = NOW.isoformat()
            return original(path, **kwargs)
        remote.pages = pages
        result = cleanup(remote, execute=True, now=NOW)
        self.assertEqual(result['deleted'], [1]); self.assertEqual(result['skipped_after_refresh'], [2])

    def test_obsolete_runtime_families_cannot_accumulate_forever(self):
        entries = [cache(1, 'refs/heads/main', days=91), cache(2, 'refs/heads/develop', days=91),
                   cache(3, 'refs/tags/v0.4.0', days=91)]
        result = select_caches(entries, set(), now=NOW)
        self.assertEqual([x['id'] for x in result['candidates']], [1,2])
        # Active refs override even this outer idle limit.
        result = select_caches(entries, {'refs/heads/develop'}, now=NOW)
        self.assertEqual([x['id'] for x in result['candidates']], [1])

    def test_read_failure_deletes_nothing_and_main_retains_two_useful_variants(self):
        remote = CacheGitHub([cache(1, 'refs/heads/old')])
        original = remote.pages
        def pages(path, **kwargs):
            if path.endswith('/pulls'): raise RuntimeError('API unavailable')
            return original(path, **kwargs)
        remote.pages = pages
        with self.assertRaises(RuntimeError): cleanup(remote, execute=True, now=NOW)
        self.assertEqual(remote.deletes, [])
        entries = [cache(i, 'refs/heads/main', days=40+i, key='pip-linux-' + str(i)*64) for i in (1,2,3)]
        self.assertEqual([x['id'] for x in select_caches(entries, set(), now=NOW)['candidates']], [3])

    def test_replaced_cache_metadata_is_not_deleted(self):
        remote = CacheGitHub([cache(1, 'refs/heads/old')])
        original = remote.pages
        def pages(path, **kwargs):
            result = original(path, **kwargs)
            if remote.cache_reads > 1: remote.entries[0]['version'] = 'new-cache-version'
            return result
        remote.pages = pages
        result = cleanup(remote, execute=True, now=NOW)
        self.assertEqual(result['deleted'], [])
        self.assertEqual(result['skipped_after_refresh'], [1])

    def test_refresh_failure_keeps_partial_report_and_stops_later_deletions(self):
        remote = CacheGitHub([cache(1, 'refs/heads/old'), cache(2, 'refs/heads/old2')])
        original = remote.pages
        def pages(path, **kwargs):
            if remote.deletes: raise GitHubError('Rate limit during refresh', 403)
            return original(path, **kwargs)
        remote.pages = pages
        result = cleanup(remote, execute=True, now=NOW)
        self.assertEqual(remote.deletes, [1]); self.assertEqual(result['deleted'], [1])
        self.assertEqual(result['errors'][0]['stage'], 'refresh')
        self.assertEqual(result['errors'][0]['outcome'], 'not_attempted')

    def test_uncertain_delete_is_reported_once_without_retry(self):
        remote = CacheGitHub([cache(1, 'refs/heads/obsolete')])
        calls = []
        def request(method, path, **kwargs):
            calls.append((method, path))
            raise GitHubError('Connection lost after request')
        remote.request = request
        result = cleanup(remote, execute=True, now=NOW)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['deleted'], [])
        self.assertEqual(result['errors'][0]['outcome'], 'uncertain')
        self.assertIs(result['errors'][0]['retried'], False)

    def test_new_activity_before_second_delete_and_maximum_batch_are_respected(self):
        remote = CacheGitHub([cache(1, 'refs/heads/old'), cache(2, 'refs/heads/newly-active')])
        original = remote.pages
        def pages(path, **kwargs):
            if remote.deletes: remote.active_after_refresh = ('newly-active',)
            return original(path, **kwargs)
        remote.pages = pages
        result = cleanup(remote, execute=True, now=NOW)
        self.assertEqual(result['deleted'], [1]); self.assertEqual(result['skipped_after_refresh'], [2])
        result = select_caches([cache(i, 'refs/pull/999/merge') for i in range(1,105)], set(), now=NOW, max_delete=100)
        self.assertEqual(len(result['candidates']),100); self.assertEqual(result['deferred'],4)


class ImmutableReuseTests(unittest.TestCase):
    def test_digest_resolution_rejects_changed_manifest_and_missing_cache_is_optional(self):
        raw = json.dumps({'mediaType': 'application/vnd.oci.image.manifest.v1+json', 'config': {}})
        digest = 'sha256:' + hashlib.sha256(raw.encode()).hexdigest()
        responses = [subprocess.CompletedProcess([], 0, raw, ''), subprocess.CompletedProcess([], 0, json.dumps({'digest': digest}), '')]
        with patch.object(builds, 'run', side_effect=responses): self.assertEqual(builds.pinned_remote('image:content'), digest)
        responses[-1] = subprocess.CompletedProcess([], 0, json.dumps({'digest': 'sha256:' + 'f'*64}), '')
        with patch.object(builds, 'run', side_effect=responses), self.assertRaises(ValueError): builds.pinned_remote('image:content')
        missing = subprocess.CompletedProcess([], 1, '', 'denied')
        with patch.object(builds, 'run', return_value=missing): self.assertIsNone(builds.pinned_remote('image:content', optional=True))
        with patch.object(builds, 'run', return_value=missing), self.assertRaises(RuntimeError): builds.pinned_remote('image:content')

    def test_content_identity_changes_for_real_catalog_data_and_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for path in ('docker', 'app', 'frontend', 'scripts'):
                shutil.copytree(ROOT / path, root / path, ignore=shutil.ignore_patterns('__pycache__','node_modules','dist'))
            for path in ('Dockerfile', '.dockerignore', 'VERSION', 'requirements.txt'): shutil.copy2(ROOT / path, root / path)
            def plan(): return image_plan((root/'VERSION').read_text().strip(), 'develop', 'a'*40, root=root)['images']
            before = plan()
            data = root/'app/data/account-plan-default.json'; data.write_bytes(data.read_bytes()+b'\n')
            after = plan(); self.assertNotEqual(before['app']['content_id'], after['app']['content_id'])
            for name in ('base','redis','postgres','mysql','minio'): self.assertEqual(before[name]['content_id'], after[name]['content_id'])
            before = after
            source = root/'app/sped_generator/api.py'; source.write_bytes(source.read_bytes()+b'\n# input fixture\n')
            after = plan(); self.assertNotEqual(before['app']['content_id'], after['app']['content_id'])
            before = after
            lock = root/'docker/runtime.lock'; lock.write_bytes(lock.read_bytes()+b'\n# cache-invalidation fixture\n')
            after = plan()
            for name in ('base','app','minio'): self.assertNotEqual(before[name]['content_id'], after[name]['content_id'])
            for name in ('redis','postgres','mysql'): self.assertEqual(before[name]['content_id'], after[name]['content_id'])


class BuildCompositionTests(unittest.TestCase):
    def run_build(self, *, warm=False, handoff=False, invalid_handoff=False):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name); version = (ROOT/'VERSION').read_text().strip()
        (root/'VERSION').write_text(version)
        plan = image_plan(version, 'develop', 'a'*40)
        handed = copy.deepcopy(plan)
        for index, image in enumerate(handed['images'].values(),1): image['image_id'] = 'sha256:' + str(index)*64
        calls = []
        def run(command, **kwargs):
            command = [str(x) for x in command]; calls.append(command)
            result = subprocess.CompletedProcess(command, 0, '', '')
            if command[:3] == ['git','rev-parse','HEAD']: result.stdout = 'a'*40
            elif command[:3] == ['docker','buildx','inspect']: result.stdout = 'Driver: docker'
            elif len(command) > 1 and command[1] == 'scripts/smoke_images.py':
                write_json(command[-1], {'status':'passed'})
            return result
        def inspect(reference):
            image = next(x for x in handed['images'].values() if x['reference'] == reference)
            return {'platform':'linux/amd64','image_id':image['image_id'], 'digest':'sha256:'+'e'*64,
                    'labels':{'io.escritura.content-id':image['content_id'],
                              'org.opencontainers.image.revision':'a'*40,
                              'org.opencontainers.image.version':version}}
        argv = ['build_images.py','publish' if handoff else 'validate','--version',version,'--channel','develop',
                '--revision','a'*40,'--output',str(root/'out.json')]
        if handoff: argv += ['--handoff',str(root/'handoff')]
        with patch.object(sys,'argv',argv), patch.object(builds,'ROOT',root), patch.object(builds,'image_plan',return_value=copy.deepcopy(plan)), \
             patch.object(builds,'run',side_effect=run), patch.object(builds,'inspect_image',side_effect=inspect), \
             patch.object(builds,'pinned_remote',return_value='sha256:'+'e'*64 if warm else None), \
             patch.object(builds,'remote_exists',return_value=False), \
             patch.object(builds,'verify_handoff',side_effect=ValueError('stale') if invalid_handoff else None, return_value=(handed,root/'images.tar.gz')), \
             patch.object(builds,'public_pull_probe',return_value={'public_pullable':True}):
            if invalid_handoff:
                with self.assertRaises(ValueError): builds.main()
            else: self.assertEqual(builds.main(),0)
        return calls

    def test_cold_validate_builds_six_warm_validate_one_and_handoff_publish_zero(self):
        for options, expected in (({},6), ({'warm':True},1), ({'handoff':True},0)):
            calls = self.run_build(**options)
            self.assertEqual(sum(c[:3] == ['docker','buildx','build'] for c in calls), expected)
            self.assertEqual(sum(len(c)>1 and c[1]=='scripts/smoke_images.py' for c in calls), 1)
            if not options.get('handoff'): self.assertFalse(any(c[:2]==['docker','push'] for c in calls))
            if options.get('warm'):
                pulls=[c for c in calls if c[:2]==['docker','pull']]
                self.assertEqual(len(pulls),5); self.assertTrue(all('@sha256:' in c[-1] for c in pulls))

    def test_invalid_handoff_blocks_all_load_build_and_push_commands(self):
        calls = self.run_build(handoff=True,invalid_handoff=True)
        self.assertFalse(any(c[:3] in (['docker','image','load'],['docker','buildx','build']) or c[:2]==['docker','push'] for c in calls))
