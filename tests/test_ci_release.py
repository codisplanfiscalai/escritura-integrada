"""Invariantes de versão, merge real e publicação, sem chamadas remotas."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.ci import release
from scripts.ci.dependencies import runtime_constraints
from scripts.ci.github_api import GitHub, GitHubError
from scripts.ci.merge import MergeError, git, merge_local
from scripts.ci.versioning import SemVer, VersionError, choose_version, dependency_hash, develop_version_after_main, manifest_versions, read_manifests, set_local, transform, verify_local


REPO = 'codisplanfiscalai/escritura-integrada'
A, B, C = ('a' * 40, 'b' * 40, 'c' * 40)


def manifests(version='0.4.0'):
    package = {'name': 'test-project', 'version': version, 'dependencies': {'dep': '1.2.3'}, 'scripts': {'build': 'vite build && node scripts/collect-notices.mjs'}}
    lock = {'name': 'test-project', 'version': version, 'lockfileVersion': 3, 'packages': {'': dict(package), 'node_modules/dep': {'version': '1.2.3'}}}
    return {'VERSION': version + '\n', 'app/__init__.py': '"""Application."""\n__version__ = "' + version + '"\n', 'frontend/package.json': json.dumps(package, indent=2) + '\n', 'frontend/package-lock.json': json.dumps(lock, indent=2) + '\n', 'package.json': json.dumps(package, indent=2) + '\n'}


def write_manifests(root, version='0.4.0'):
    for name, value in manifests(version).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')


def repo(root):
    git(root, 'init', '-b', 'main')
    git(root, 'config', 'core.autocrlf', 'false')
    write_manifests(root)
    (root / 'business.txt').write_text('baseline\n')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'initial')


def commit(root, message):
    git(root, 'add', '.')
    git(root, 'commit', '-m', message)
    return git(root, 'rev-parse', 'HEAD').stdout.strip()


def plan(branch='main', source=A, version=None):
    version = version or ('0.4.0' if branch == 'main' else '0.4.1-dev.3')
    return {'schema': 'escritura-ci-plan/1', 'repository': REPO, 'branch': branch, 'source_sha': source, 'version': version, 'channel': 'production' if branch == 'main' else 'develop', 'tag': 'v' + version if branch == 'main' else 'develop', 'run_id': 123, 'run_number': 3, 'run_attempt': 1}


def assets(root, item):
    prefix = 'EscrituraIntegrada-' + item['version'] + '-'
    path = root / (prefix + 'example.zip')
    path.write_bytes(b'unit-test-asset')
    release.write_json(root / (prefix + 'manifest.json'), {'repository': REPO, 'version': item['version'], 'source_sha': item['source_sha'], 'assets': [{'name': path.name, 'size': path.stat().st_size, 'sha256': release.file_hash(path)}]})
    (root / (prefix + 'SHA256SUMS.txt')).write_text(''.join(release.file_hash(p) + '  ' + p.name + '\n' for p in sorted(root.iterdir())), encoding='ascii')


class FakeGitHub:
    def __init__(self):
        self.repository, self.base, self.token = REPO, '/repos/' + REPO, 'test-token-not-real'
        self.refs = {'heads/main': A, 'heads/develop': B}
        self.files = {A: manifests(), B: manifests('0.4.1-dev.3')}
        self.trees = {A: self.files[A], B: self.files[B]}
        self.commits = {value: {'sha': value, 'tree': {'sha': value}, 'parents': [], 'message': 'initial'} for value in (A, B)}
        self.releases, self.asset_list, self.writes = {}, [], []
        self.fail_upload = self.fail_metadata = False
        self.sequence = 1

    def new_sha(self):
        self.sequence += 1
        return hashlib.sha1(str(self.sequence).encode()).hexdigest()

    def ref(self, name, missing=False):
        return {'ref': 'refs/' + name, 'object': {'type': 'commit', 'sha': self.refs[name]}} if name in self.refs else None

    def commit_sha(self, value):
        return value['object']['sha'] if value else None

    def file(self, path, source, missing=False):
        return self.files[source].get(path)

    def release(self, tag, missing=False):
        return self.releases.get(tag)

    def pages(self, path, **kwargs):
        if path.endswith('/commits'):
            return iter({'commit': {'message': c.get('message', '')}} for c in self.commits.values())
        if path.endswith('/assets'):
            return iter(list(self.asset_list))
        if path.endswith('/releases'):
            return iter(self.releases.values())
        raise AssertionError(path)

    def upload(self, target, path):
        if self.fail_upload:
            raise GitHubError('interrupted upload')
        item = {'name': path.name, 'id': len(self.asset_list) + 100, 'size': path.stat().st_size, 'digest': 'sha256:' + release.file_hash(path), 'state': 'uploaded'}
        self.asset_list.append(item)
        self.writes.append(('UPLOAD', path.name, None))
        return item

    def request(self, method, path, payload=None, **kwargs):
        endpoint = path.removeprefix(self.base)
        if method != 'GET':
            self.writes.append((method, endpoint, payload))
        if method == 'GET' and endpoint == '/git/matching-refs/tags/v':
            return [self.ref(name) for name in self.refs if name.startswith('tags/v')]
        if method == 'GET' and endpoint.startswith('/git/commits/'):
            return self.commits[endpoint.rsplit('/', 1)[1]]
        if method == 'POST' and endpoint == '/git/trees':
            value = self.new_sha()
            files = dict(self.trees[payload['base_tree']])
            files.update({item['path']: item['content'] for item in payload['tree']})
            self.trees[value] = files
            return {'sha': value}
        if method == 'POST' and endpoint == '/git/commits':
            value = self.new_sha()
            self.commits[value] = {'sha': value, 'tree': {'sha': payload['tree']}, 'parents': [{'sha': p} for p in payload['parents']], 'message': payload['message']}
            self.files[value] = self.trees[payload['tree']]
            return {'sha': value}
        if method == 'POST' and endpoint == '/git/refs':
            name = payload['ref'].removeprefix('refs/')
            if name in self.refs:
                raise GitHubError('reference exists', 422)
            self.refs[name] = payload['sha']
            return self.ref(name)
        if method == 'PATCH' and endpoint.startswith('/git/refs/'):
            name = endpoint.removeprefix('/git/refs/')
            if name.startswith('heads/'):
                assert payload['force'] is False
                if self.refs[name] not in [x['sha'] for x in self.commits[payload['sha']]['parents']]:
                    raise GitHubError('not fast-forward', 422)
            self.refs[name] = payload['sha']
            return self.ref(name)
        if method == 'POST' and endpoint == '/releases':
            item = dict(payload, id=7, upload_url='https://uploads.github.com/example{?name}', html_url='https://github.com/' + REPO + '/releases/tag/' + payload['tag_name'])
            self.releases[payload['tag_name']] = item
            return item
        if method == 'PATCH' and endpoint.startswith('/releases/'):
            if self.fail_metadata:
                raise GitHubError('metadata unavailable', 503)
            item = next(item for item in self.releases.values() if str(item['id']) == endpoint.rsplit('/', 1)[1])
            item.update(payload)
            return item
        if method == 'DELETE' and endpoint.startswith('/releases/assets/'):
            identifier = int(endpoint.rsplit('/', 1)[1])
            self.asset_list = [item for item in self.asset_list if item['id'] != identifier]
            return None
        if method == 'POST' and endpoint.endswith('/dispatches'):
            return None
        raise AssertionError((method, endpoint, payload))


class VersionTests(unittest.TestCase):
    def test_semver_precedence_and_invalid_numbers(self):
        values = ['1.0.0-alpha', '1.0.0-alpha.1', '1.0.0-alpha.beta', '1.0.0-beta', '1.0.0-beta.2', '1.0.0-beta.11', '1.0.0-rc.1', '1.0.0']
        for left, right in zip(values, values[1:]):
            self.assertLess(SemVer.parse(left).compare(SemVer.parse(right)), 0)
        for wrong in ('01.2.3', '1.2', '1.2.3-dev.01', 'v1.2.3'):
            with self.assertRaises(VersionError):
                SemVer.parse(wrong)

    def test_main_and_develop_are_monotonic(self):
        self.assertEqual(choose_version('main', '0.4.0-dev.1', '0.4.0-dev.1', [], 1), '0.4.0')
        self.assertEqual(choose_version('develop', '0.4.0', '0.4.0', ['0.4.0'], 5), '0.4.1-dev.1')
        self.assertEqual(choose_version('main', '0.4.0', '0.4.0', ['0.4.0'], 6), '0.4.1')
        self.assertEqual(choose_version('main', '0.4.0', '0.4.0', ['0.4.0'], 6, 'v0.4.0'), '0.4.0')
        self.assertEqual(choose_version('develop', '1.0.0-dev.1', '0.4.0', ['0.4.0'], 7), '1.0.0-dev.2')

    def test_develop_counter_belongs_to_core_not_workflow(self):
        self.assertEqual(choose_version('develop', '0.8.0-dev.25', '0.8.0', ['0.8.0'], 999), '0.8.1-dev.1')
        self.assertEqual(choose_version('develop', '0.8.1-dev.0', '0.8.0', ['0.8.0'], 999), '0.8.1-dev.1')
        self.assertEqual(choose_version('develop', '0.8.1-dev.1', '0.8.0', ['0.8.0'], 1000), '0.8.1-dev.2')
        self.assertEqual(choose_version('develop', '0.9.0-dev.0', '0.8.0', ['0.8.0'], 1001), '0.9.0-dev.1')
        self.assertEqual(choose_version('develop', '0.8.1-dev.29', '0.8.1', ['0.8.1'], 1002), '0.8.2-dev.1')

    def test_post_release_develop_preserves_higher_explicit_core(self):
        self.assertEqual(develop_version_after_main('0.4.0', None), '0.4.1-dev.0')
        self.assertEqual(develop_version_after_main('0.4.1', '0.4.1-dev.2'), '0.4.2-dev.0')
        self.assertEqual(develop_version_after_main('0.4.0', '0.5.0-dev.77'), '0.5.0-dev.77')

    def test_all_manifests_keep_dependencies_and_scripts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); write_manifests(root)
            before = dependency_hash(root)
            set_local(root, '0.4.1-dev.8')
            self.assertEqual(verify_local(root), '0.4.1-dev.8')
            self.assertEqual(before, dependency_hash(root))
            package = json.loads((root / 'frontend/package.json').read_text())
            self.assertEqual(package['dependencies'], {'dep': '1.2.3'})
            self.assertIn('collect-notices', package['scripts']['build'])
            lock = json.loads((root / 'frontend/package-lock.json').read_text())
            self.assertEqual(lock['packages']['node_modules/dep']['version'], '1.2.3')
            self.assertEqual(lock['packages']['']['version'], '0.4.1-dev.8')

    def test_constraints_keep_windows_marker_without_hash_mode(self):
        value = runtime_constraints('dep==1.0 \\\n --hash=sha256:abc\ncolorama==0.4.6 ; sys_platform == "win32" \\\n --hash=sha256:def\n')
        self.assertEqual(value, 'dep==1.0\ncolorama==0.4.6 ; sys_platform == "win32"\n')
        self.assertNotIn('--hash', value)


class MergeTests(unittest.TestCase):
    def test_two_release_develop_promotion_cycles_keep_ancestry_and_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); repo(root)
            git(root, 'checkout', '-b', 'develop')
            set_local(root, '0.4.1-dev.1')
            (root / 'feature.txt').write_text('feature 1\n')
            commit(root, 'develop feature')
            for number in (1, 2):
                git(root, 'checkout', 'main')
                # Promotion uses a real merge and must remain conflict-free in
                # the second cycle, after sync incorporated main's ancestry.
                git(root, 'merge', '--no-ff', '--no-edit', 'develop')
                set_local(root, f'0.4.{number}')
                (root / f'hotfix-{number}.txt').write_text(f'hotfix {number}\n')
                main_sha = commit(root, f'release {number}')
                git(root, 'checkout', 'develop')
                set_local(root, f'0.4.{number}-dev.{number + 10}')
                (root / f'next-{number}.txt').write_text(f'ongoing feature {number}\n')
                develop_sha = commit(root, f'ongoing {number}')
                result = merge_local(root, main_sha, develop_sha, f'0.4.{number + 1}-dev.0')
                self.assertEqual(result.parents, [develop_sha, main_sha])
                self.assertTrue(result.merged_main)
                git(root, 'update-ref', 'refs/heads/develop', result.commit, develop_sha)
                git(root, 'reset', '--hard', result.commit)
                self.assertEqual(verify_local(root), f'0.4.{number + 1}-dev.0')
                self.assertEqual((root / f'hotfix-{number}.txt').read_text(), f'hotfix {number}\n')
                self.assertTrue((root / f'next-{number}.txt').is_file())
                self.assertEqual(git(root, 'merge-base', '--is-ancestor', main_sha, result.commit, check=False).returncode, 0)
            git(root, 'checkout', 'main')
            self.assertEqual(git(root, 'merge', '--no-ff', '--no-edit', 'develop', check=False).returncode, 0)

    def test_code_conflict_stops_without_touching_branches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); repo(root)
            git(root, 'checkout', '-b', 'develop')
            (root / 'business.txt').write_text('develop change\n'); dev = commit(root, 'develop')
            git(root, 'checkout', 'main')
            (root / 'business.txt').write_text('main hotfix\n'); main = commit(root, 'main')
            with self.assertRaisesRegex(MergeError, 'Conflito de código'):
                merge_local(root, main, dev, '0.4.1-dev.0')
            self.assertEqual(git(root, 'rev-parse', 'develop').stdout.strip(), dev)
            self.assertEqual(git(root, 'rev-parse', 'main').stdout.strip(), main)

    def test_dependency_conflict_is_not_hidden_by_version_resolution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); repo(root)
            git(root, 'checkout', '-b', 'develop')
            set_local(root, '0.4.1-dev.2')
            path = root / 'frontend/package.json'
            data = json.loads(path.read_text()); data['dependencies']['dep'] = '3.0.0'; path.write_text(json.dumps(data, indent=2) + '\n')
            dev = commit(root, 'develop dependency')
            git(root, 'checkout', 'main'); set_local(root, '0.4.1')
            data = json.loads(path.read_text()); data['dependencies']['dep'] = '2.0.0'; path.write_text(json.dumps(data, indent=2) + '\n')
            main = commit(root, 'main dependency')
            with self.assertRaisesRegex(MergeError, 'Conflito além do número'):
                merge_local(root, main, dev, '0.4.2-dev.0')

    def test_one_sided_dependency_change_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); repo(root)
            git(root, 'checkout', '-b', 'develop'); set_local(root, '0.4.1-dev.2'); dev = commit(root, 'develop version')
            git(root, 'checkout', 'main'); set_local(root, '0.4.1')
            path = root / 'frontend/package.json'; data = json.loads(path.read_text()); data['dependencies']['dep'] = '2.0.0'; path.write_text(json.dumps(data, indent=2) + '\n')
            main = commit(root, 'main dependency')
            result = merge_local(root, main, dev, '0.4.2-dev.0')
            merged = json.loads(git(root, 'show', result.commit + ':frontend/package.json').stdout)
            self.assertEqual(merged['dependencies']['dep'], '2.0.0')
            self.assertEqual(merged['version'], '0.4.2-dev.0')


class ReleaseTests(unittest.TestCase):
    def test_reservation_prevents_oci_collision_after_a_later_code_push(self):
        gh = FakeGitHub()
        release.reserve(gh, plan())
        self.assertEqual(gh.refs['tags/v0.4.0'], A)
        gh.refs['heads/main'] = C
        gh.files[C] = manifests('0.4.0'); gh.trees[C] = gh.files[C]
        gh.commits[C] = {'sha': C, 'tree': {'sha': C}, 'parents': [{'sha': A}], 'message': 'new application code'}
        following = release.prepare(gh, branch='main', event_sha=C, run_number=4, run_id=124)
        self.assertEqual(following['version'], '0.4.1')
        self.assertEqual(gh.refs['tags/v0.4.0'], A)

    def test_prepare_commits_all_manifests_fast_forward_and_can_retry_own_commit(self):
        gh = FakeGitHub(); gh.files[A] = manifests('0.4.0-dev.1'); gh.trees[A] = gh.files[A]
        result = release.prepare(gh, branch='main', event_sha=A, run_number=1, run_id=99)
        self.assertEqual(result['version'], '0.4.0')
        self.assertNotEqual(result['source_sha'], A)
        self.assertTrue(all(v == '0.4.0' for v in manifest_versions(gh.files[result['source_sha']]).values()))
        retry = release.prepare(gh, branch='main', event_sha=A, run_number=1, run_id=99, run_attempt=2)
        self.assertEqual(retry['source_sha'], result['source_sha'])
        self.assertTrue(all(p['force'] is False for m, route, p in gh.writes if route.startswith('/git/refs/heads/')))

    def test_develop_retry_reuses_own_number_but_closed_cycle_is_rejected(self):
        gh = FakeGitHub()
        first = release.prepare(gh, branch='develop', event_sha=B, run_number=90, run_id=900)
        self.assertEqual(first['version'], '0.4.1-dev.4')
        writes = list(gh.writes)
        retry = release.prepare(gh, branch='develop', event_sha=B, run_number=90, run_id=900, run_attempt=2)
        self.assertEqual(retry['version'], first['version'])
        self.assertEqual(retry['source_sha'], first['source_sha'])
        self.assertEqual(writes, gh.writes)
        gh.files[A] = manifests('0.4.1')
        with self.assertRaises(release.StaleRun):
            release.prepare(gh, branch='develop', event_sha=B, run_number=90, run_id=900, run_attempt=3)
        self.assertEqual(writes, gh.writes)

    def test_counter_does_not_reuse_published_or_failed_preparation_after_merge(self):
        gh = FakeGitHub()
        gh.files[B] = manifests('0.4.1-dev.1'); gh.trees[B] = gh.files[B]
        gh.releases['develop'] = {'body': '<!-- escritura-ci:' + json.dumps({
            'version': '0.4.1-dev.8', 'source_sha': C}) + ' -->'}
        gh.commits[C] = {'message': 'chore(release): preparar 0.4.1-dev.9'}
        result = release.prepare(gh, branch='develop', event_sha=B, run_number=111, run_id=999)
        self.assertEqual(result['version'], '0.4.1-dev.10')
        self.assertTrue(release.guard(gh, result))

    def test_same_version_with_another_source_cannot_publish(self):
        gh = FakeGitHub()
        gh.releases['develop'] = {'body': '<!-- escritura-ci:' + json.dumps({
            'version': '0.4.1-dev.3', 'source_sha': C}) + ' -->'}
        with self.assertRaises(release.StaleRun):
            release.guard(gh, plan('develop', B))
        self.assertEqual(gh.writes, [])

    def test_reserved_stable_cycle_blocks_prerelease_publish(self):
        gh = FakeGitHub(); gh.refs['tags/v0.4.1'] = A
        with self.assertRaises(release.StaleRun):
            release.guard(gh, plan('develop', B))
        self.assertEqual(gh.writes, [])

    def test_stale_plan_and_stable_tag_collision_make_no_mutations(self):
        gh = FakeGitHub()
        with self.assertRaises(release.StaleRun):
            release.guard(gh, plan(source=C))
        gh.refs['tags/v0.4.0'] = C
        with self.assertRaisesRegex(release.ReleaseError, 'tag estável'):
            release.guard(gh, plan())
        self.assertEqual(gh.writes, [])

    def test_develop_must_remain_above_current_main(self):
        gh = FakeGitHub(); gh.files[A] = manifests('0.4.1')
        with self.assertRaises(release.StaleRun):
            release.guard(gh, plan('develop', B))
        self.assertEqual(gh.writes, [])

    def test_published_stable_is_never_rewritten(self):
        gh = FakeGitHub(); item = plan(); gh.refs['tags/v0.4.0'] = A
        gh.releases['v0.4.0'] = {'id': 5, 'draft': False, 'prerelease': False, 'html_url': 'https://example.invalid/stable'}
        with tempfile.TemporaryDirectory() as temporary:
            assets(Path(temporary), item)
            result = release.publish(gh, item, temporary, {})
        self.assertEqual(result['status'], 'already_published')
        self.assertEqual(gh.writes, [])

    def test_upload_failure_preserves_rolling_tag_and_previous_release(self):
        gh = FakeGitHub(); gh.refs['tags/develop'] = C; gh.fail_upload = True
        gh.releases['develop'] = {'id': 5, 'draft': False, 'prerelease': True, 'body': 'previous', 'upload_url': 'https://uploads.github.com/test'}
        with tempfile.TemporaryDirectory() as temporary:
            assets(Path(temporary), plan('develop', B))
            with self.assertRaises(GitHubError):
                release.publish(gh, plan('develop', B), temporary, {})
        self.assertEqual(gh.refs['tags/develop'], C)
        self.assertEqual(gh.releases['develop']['body'], 'previous')

    def test_metadata_failure_rolls_back_only_the_rolling_tag(self):
        gh = FakeGitHub(); gh.refs['tags/develop'] = C; gh.fail_metadata = True
        gh.releases['develop'] = {'id': 5, 'draft': False, 'prerelease': True, 'body': 'previous', 'upload_url': 'https://uploads.github.com/test'}
        with tempfile.TemporaryDirectory() as temporary:
            assets(Path(temporary), plan('develop', B))
            with self.assertRaises(GitHubError):
                release.publish(gh, plan('develop', B), temporary, {})
        self.assertEqual(gh.refs['tags/develop'], C)
        moved = [(path, data) for method, path, data in gh.writes if method == 'PATCH' and path.startswith('/git/refs/')]
        self.assertEqual([data['sha'] for path, data in moved], [B, C])
        self.assertTrue(all(path == '/git/refs/tags/develop' for path, data in moved))

    def test_success_keeps_one_develop_release_and_only_removes_owned_obsolete_assets(self):
        gh = FakeGitHub(); gh.refs['tags/develop'] = C
        gh.releases['develop'] = {'id': 5, 'draft': False, 'prerelease': True, 'body': 'previous', 'upload_url': 'https://uploads.github.com/test', 'html_url': 'https://example.invalid/develop'}
        gh.asset_list = [{'id': 1, 'name': 'EscrituraIntegrada-0.4.1-dev.1-old.zip'}, {'id': 2, 'name': 'manual-user-note.txt'}]
        with tempfile.TemporaryDirectory() as temporary:
            assets(Path(temporary), plan('develop', B))
            result = release.publish(gh, plan('develop', B), temporary, {})
        self.assertEqual(len(gh.releases), 1)
        self.assertEqual(gh.refs['tags/develop'], B)
        self.assertEqual(result['obsolete_prerelease_assets_removed'], ['EscrituraIntegrada-0.4.1-dev.1-old.zip'])
        self.assertIn('manual-user-note.txt', [item['name'] for item in gh.asset_list])

    def test_initial_stable_sync_creates_develop_and_explicitly_dispatches(self):
        gh = FakeGitHub(); del gh.refs['heads/develop']; gh.refs['tags/v0.4.0'] = A
        gh.releases['v0.4.0'] = {'id': 1, 'draft': False, 'prerelease': False}
        result = release.sync_develop(gh, plan())
        self.assertEqual(result['version'], '0.4.1-dev.0')
        self.assertTrue(result['created'])
        dispatch = [item for item in gh.writes if item[1].endswith('/dispatches')]
        self.assertEqual(len(dispatch), 1)
        self.assertEqual(dispatch[0][2]['inputs']['expected_sha'], gh.refs['heads/develop'])

    def test_draft_lookup_is_resumable_and_ambiguous_list_is_refused(self):
        gh = GitHub(REPO, 'not-a-real-token')
        draft = {'id': 5, 'tag_name': 'v0.4.0', 'draft': True}
        with patch.object(gh, 'request', return_value=None), patch.object(gh, 'pages', return_value=iter([draft])):
            self.assertEqual(gh.release('v0.4.0', missing=True), draft)
        with patch.object(gh, 'request', return_value=None), patch.object(gh, 'pages', return_value=iter([draft, dict(draft, id=6)])):
            with self.assertRaisesRegex(GitHubError, 'Mais de uma'):
                gh.release('v0.4.0', missing=True)


if __name__ == '__main__':
    unittest.main()
