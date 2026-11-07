"""Gates de distribuição e retenção: fixtures locais, sem GitHub ou Docker reais."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.ci.artifacts import archive_source, assemble
from scripts.ci.cleanup_actions import cleanup, select_caches
from scripts.ci.merge import git
from scripts.ci.release import ReleaseError, file_hash, validate_assets, write_json
from test_ci_release import plan, repo


class ArtifactGatesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        repo(self.source)
        self.plan = plan(source=git(self.source, 'rev-parse', 'HEAD').stdout.strip())
        self.prefix = 'EscrituraIntegrada-' + self.plan['version'] + '-'
        self.windows, self.reports, self.deploy = [self.root / name for name in ('windows', 'reports', 'deploy')]
        for directory in (self.windows, self.reports, self.deploy):
            directory.mkdir()
        common = {'ok': True, 'version': self.plan['version'], 'source_sha': self.plan['source_sha']}
        write_json(self.reports / 'linux-checks.json', dict(common, tests_run=5))
        (self.reports / 'linux-checks.log').write_text('Fixture: all checks passed\n', encoding='utf-8')
        self.windows_zip = self.windows / (self.prefix + 'windows-x64.zip')
        with zipfile.ZipFile(self.windows_zip, 'w') as output:
            output.writestr('fixture.txt', 'Test fixture; not a Windows executable.')
        write_json(self.windows / 'windows-build.json', dict(common, smoke_executed=True, smoke_ok=True,
                   archive=self.windows_zip.name, sha256=file_hash(self.windows_zip)))
        write_json(self.windows / 'windows-smoke.json', dict(common, packaged=True, shutdown_complete=True,
                   supervisor={'forced_cleanup': False, 'remaining_processes': 0, 'root_exit_code': 0}))
        (self.windows / 'windows-smoke.png').write_bytes(b'fixture-screenshot-for-gate-test')
        images = {'version': self.plan['version'], 'source_sha': self.plan['source_sha'],
                  'channel': self.plan['channel'], 'status': 'published', 'public_pullable': False,
                  'smoke': {'status': 'passed'},
                  'images': {name: {'digest': 'sha256:' + '1' * 64} for name in ('app', 'base', 'redis', 'postgres', 'mysql', 'minio')}}
        self.images = self.root / 'images-published.json'
        write_json(self.images, images)
        write_json(self.reports / 'images-validated.json', dict(images, status='validated'))
        packages = []
        for environment in ('production', 'develop'):
            path = self.deploy / (self.prefix + environment + '-deploy.zip')
            with zipfile.ZipFile(path, 'w') as output:
                output.writestr('compose.yaml', '# unit test fixture\n')
            packages.append({'file': path.name, 'sha256': file_hash(path)})
        write_json(self.deploy / (self.prefix + 'deploy-manifest.json'), dict(common,
                   channel=self.plan['channel'], packages=packages))
        self.offline = self.deploy / (self.prefix + 'linux-amd64-images.tar.gz')
        self.offline.write_bytes(b'offline archive fixture; no actual container images')
        write_json(self.offline.with_suffix('.gz.manifest.json'), dict(common,
                   offline_load_verified=True, load_smoke={'status': 'passed'}, sha256=file_hash(self.offline)))

    def assemble(self, suffix='final'):
        return assemble(self.plan, root=self.source, windows_dir=self.windows, reports_dir=self.reports,
                        deploy_dir=self.deploy, images_manifest=self.images, output_dir=self.root / suffix)

    def mutate(self, path, **changes):
        value = json.loads(path.read_text(encoding='utf-8'))
        value.update(changes)
        write_json(path, value)

    def test_authenticated_images_are_allowed_and_final_checksums_detect_tampering(self):
        result = self.assemble()
        self.assertIs(result['public_pullable'], False)
        final = self.root / 'final'
        files, _, _ = validate_assets(self.plan, final)
        self.assertIn(self.prefix + 'windows-x64.zip', {item.name for item in files})
        asset = final / self.windows_zip.name
        asset.write_bytes(asset.read_bytes() + b'modified after assembly')
        with self.assertRaises(ReleaseError):
            validate_assets(self.plan, final)

    def test_wrong_commit_or_missing_gate_prevents_assembly(self):
        windows = self.windows / 'windows-build.json'
        original = windows.read_text(encoding='utf-8')
        cases = ({'source_sha': 'e' * 40}, {'ok': False}, {'smoke_executed': False}, {'smoke_ok': False})
        for number, change in enumerate(cases):
            with self.subTest(change=change):
                windows.write_text(original, encoding='utf-8')
                self.mutate(windows, **change)
                with self.assertRaises(ReleaseError):
                    self.assemble('rejected-' + str(number))
                self.assertFalse(list((self.root / ('rejected-' + str(number))).iterdir()))

    def test_orphan_cleanup_is_not_treated_as_healthy_binary(self):
        smoke = self.windows / 'windows-smoke.json'
        for number, supervisor in enumerate((
            {'forced_cleanup': True, 'remaining_processes': 0, 'root_exit_code': 0},
            {'forced_cleanup': False, 'remaining_processes': 1, 'root_exit_code': 0},
        )):
            with self.subTest(supervisor=supervisor):
                self.mutate(smoke, supervisor=supervisor)
                with self.assertRaisesRegex(ReleaseError, 'processos'):
                    self.assemble('orphan-' + str(number))

    def test_modified_windows_or_offline_payload_is_rejected_before_copy(self):
        original = self.windows_zip.read_bytes()
        self.windows_zip.write_bytes(original + b'changed')
        with self.assertRaisesRegex(ReleaseError, 'ZIP Windows'):
            self.assemble('wrong-windows')
        self.windows_zip.write_bytes(original)
        self.offline.write_bytes(b'changed offline payload')
        with self.assertRaisesRegex(ReleaseError, 'bundle offline'):
            self.assemble('wrong-offline')

    def test_source_zip_uses_committed_blobs_and_omits_untracked_files(self):
        committed_bytes = (self.source / 'business.txt').read_bytes()
        (self.source / 'business.txt').write_text('uncommitted change\n', encoding='utf-8')
        (self.source / 'untracked-private-fixture.txt').write_text('test-only data', encoding='utf-8')
        target = self.root / 'source.zip'
        archive_source(self.source, self.plan, target)
        base = 'EscrituraIntegrada-' + self.plan['version'] + '/'
        with zipfile.ZipFile(target) as archive:
            self.assertEqual(archive.read(base + 'business.txt'), committed_bytes)
            self.assertNotIn(base + 'untracked-private-fixture.txt', archive.namelist())
            self.assertEqual(archive.read(base + 'VERSION').decode().strip(), self.plan['version'])


NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)


def cache(identifier, ref, days=60, key=None):
    return {'id': identifier, 'ref': ref, 'key': key or 'pip-cache-' + str(identifier),
            'size_in_bytes': 100, 'last_accessed_at': (NOW - timedelta(days=days)).isoformat()}


class CacheGitHub:
    base = '/repos/example/project'
    repository = 'example/project'

    def __init__(self, entries, active=(), active_after_refresh=()):
        self.entries, self.active, self.active_after_refresh = entries, active, active_after_refresh
        self.cache_reads, self.deletes = 0, []

    def pages(self, endpoint, *, key=None, params=None):
        if endpoint.endswith('/actions/caches'):
            self.cache_reads += 1
            return iter(self.entries)
        if endpoint.endswith('/actions/runs'):
            branches = self.active_after_refresh if self.cache_reads > 1 else self.active
            return iter([{'head_branch': name, 'event': 'push', 'pull_requests': []} for name in branches]
                        if params['status'] == 'in_progress' else [])
        raise AssertionError(endpoint)

    def request(self, method, endpoint, **kwargs):
        self.assert_delete(method, endpoint)
        self.deletes.append(int(endpoint.rsplit('/', 1)[1]))

    @staticmethod
    def assert_delete(method, endpoint):
        if method != 'DELETE' or '/actions/caches/' not in endpoint:
            raise AssertionError((method, endpoint))


class CacheRetentionTests(unittest.TestCase):
    def test_dry_run_never_deletes_and_preserves_main_stable_and_active(self):
        entries = [cache(1, 'refs/heads/main'), cache(2, 'refs/tags/v0.4.0'),
                   cache(3, 'refs/heads/active-feature'), cache(4, 'refs/pull/17/merge')]
        remote = CacheGitHub(entries, active=('active-feature',))
        result = cleanup(remote, execute=False, now=NOW)
        self.assertEqual([item['id'] for item in result['candidates']], [4])
        self.assertEqual(remote.deletes, [])
        self.assertIs(result['stable_releases_touched'], False)

    def test_activity_is_rechecked_before_deleting_exact_cache_ids(self):
        remote = CacheGitHub([cache(7, 'refs/heads/newly-active'), cache(8, 'refs/heads/obsolete')],
                            active_after_refresh=('newly-active',))
        result = cleanup(remote, execute=True, now=NOW)
        self.assertEqual(remote.deletes, [8])
        self.assertEqual(result['skipped_after_refresh'], [7])
        self.assertEqual(result['deleted'], [8])

    def test_recent_develop_variants_and_unknown_dates_are_preserved(self):
        entries = [cache(index, 'refs/heads/develop', days=20 + index,
                         key='pip-windows-312-' + str(index) * 64) for index in (1, 2, 3)]
        unknown = cache(4, 'refs/heads/old-feature')
        unknown['last_accessed_at'] = 'not-a-date'
        entries.extend([unknown, cache(5, 'refs/pull/19/merge')])
        result = select_caches(entries, set(), now=NOW, protect_all_pr=True)
        self.assertEqual([item['id'] for item in result['candidates']], [3])


if __name__ == '__main__':
    unittest.main()
