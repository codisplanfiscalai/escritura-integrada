"""Fail-closed tests for a single approved recovery, with no network/mutations."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import zipfile

from scripts.ci import recover_dev21 as r


class FakeGH:
    repository = r.REPOSITORY
    base = '/repos/' + repository
    token = 'ephemeral-test-token'

    def __init__(self):
        self.spec = r.load_spec()
        self.run = dict(id=r.RUN, run_attempt=2, status='completed', conclusion='failure',
                        path='.github/workflows/release.yml', head_branch='develop', head_sha=self.spec['trigger_sha'], run_number=21,
                        html_url='https://github.com/' + self.repository + '/actions/runs/' + str(r.RUN))
        self.jobs = [dict(name=name, status='completed', conclusion='success', run_id=r.RUN, head_sha=self.spec['trigger_sha'])
                     for name in sorted(r.GATES - {r.PUBLISH_JOB})]
        self.jobs.append(dict(name=r.PUBLISH_JOB, status='completed', conclusion='failure', steps=[
            dict(name=r.FAIL_STEP, conclusion='failure'),
            dict(name='Publicar tag e release do commit testado', conclusion='skipped'),
            dict(name='Publicar imagens por versão e digest', conclusion='success'),
            dict(name='Exportar imagens e comprovar carga offline', conclusion='success')]))
        self.refs = {'heads/develop': r.SOURCE, 'heads/main': self.spec['main_sha'], 'heads/' + r.BRANCH: 'a'*40,
                     'tags/develop': self.spec['previous_release']['target']}
        self.assets = copy.deepcopy(self.spec['previous_release']['assets'])
        self.rel = dict(id=self.spec['previous_release']['release_id'], body='<!-- escritura-ci:' + json.dumps(
            dict(version='0.8.0-dev.20', source_sha=self.refs['tags/develop'])) + ' -->')

    def ref(self, key):
        return self.refs[key]

    def commit_sha(self, ref):
        return ref

    def file(self, path, sha):
        return r.VERSION

    def request(self, method, path):
        assert method == 'GET'
        return self.run

    def pages(self, path, **kwargs):
        return self.assets if path.endswith('/assets') else self.jobs

    def release(self, tag):
        return self.rel


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGH()
        self.spec = self.gh.spec

    def test_approved_original_failure_is_evidence_not_success(self):
        proof = r.verify_original(self.gh, self.spec)
        self.assertEqual(proof['original_conclusion'], 'failure')
        self.assertEqual(len(proof['gates']), 6)

    def test_wrong_attempt_sha_run_branch_and_conclusion_rejected(self):
        for key, value in [('run_attempt', 3), ('head_sha', 'a'*40), ('id', 1), ('head_branch', 'main'), ('conclusion', 'success')]:
            with self.subTest(key=key):
                gh = FakeGH(); gh.run[key] = value
                with self.assertRaises(RuntimeError): r.verify_original(gh, self.spec)

    def test_missing_failed_duplicate_gate_rejected(self):
        for mode in ['missing', 'failed', 'duplicate', 'wrong-source']:
            gh = FakeGH()
            if mode == 'missing': gh.jobs.pop(0)
            if mode == 'failed': gh.jobs[0]['conclusion'] = 'failure'
            if mode == 'duplicate': gh.jobs.append(gh.jobs[0])
            if mode == 'wrong-source': gh.jobs[0]['head_sha'] = 'a'*40
            with self.subTest(mode=mode), self.assertRaises(RuntimeError): r.verify_original(gh, self.spec)

    def test_other_publish_failure_or_already_executed_publish_rejected(self):
        for mode in ['another', 'published']:
            gh = FakeGH()
            if mode == 'another': gh.jobs[-1]['steps'].append(dict(name='unexpected', conclusion='failure'))
            else: gh.jobs[-1]['steps'][1]['conclusion'] = 'success'
            with self.subTest(mode=mode), self.assertRaises(RuntimeError): r.verify_original(gh, self.spec)

    def test_exact_operational_context_and_both_branch_heads(self):
        env = dict(GITHUB_ACTIONS='true', GITHUB_REF='refs/heads/' + r.BRANCH, GITHUB_SHA='a'*40)
        with patch.dict(r.os.environ, env):
            r.verify_heads(self.gh, self.spec)
            for branch in ['main', 'develop', r.BRANCH]:
                gh = FakeGH(); gh.refs['heads/' + branch] = 'b'*40
                with self.subTest(branch=branch), self.assertRaises(RuntimeError): r.verify_heads(gh, self.spec)
        with patch.dict(r.os.environ, dict(env, GITHUB_REF='refs/heads/main')):
            with self.assertRaises(RuntimeError): r.verify_heads(self.gh, self.spec)

    def test_backup_exact_inventory_required(self):
        r.check_backup(self.gh, self.spec)
        for mode in ['new', 'missing', 'modified', 'tag']:
            gh = FakeGH()
            if mode == 'new': gh.assets.append(dict(id=111, name='new', size=1, digest='sha256:'+'a'*64))
            if mode == 'missing': gh.assets.pop()
            if mode == 'modified': gh.assets[0]['digest'] = 'sha256:'+'a'*64
            if mode == 'tag': gh.refs['tags/develop'] = r.SOURCE
            with self.subTest(mode=mode), self.assertRaises(RuntimeError): r.check_backup(gh, self.spec)

    def test_metadata_binds_id_digest_source_run_and_repository(self):
        item = self.spec['artifacts'][0]
        data = dict(item, expired=False, workflow_run=dict(id=r.RUN, head_sha=self.spec['trigger_sha'], head_branch='develop', repository_id=1448900908, head_repository_id=1448900908))
        r.verify_artifact_metadata(data, item, self.spec)
        for key in ['id', 'digest', 'name', 'size_in_bytes', 'expired']:
            wrong = dict(data, **{key: None})
            with self.subTest(key=key), self.assertRaises(RuntimeError): r.verify_artifact_metadata(wrong, item, self.spec)
        wrong = copy.deepcopy(data); wrong['workflow_run']['id'] = 123
        with self.assertRaises(RuntimeError): r.verify_artifact_metadata(wrong, item, self.spec)

    def test_browser_destination_preserves_two_sibling_suites(self):
        with tempfile.TemporaryDirectory() as d:
            archive = Path(d)/'browser.zip'; out=Path(d)/'out'
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('browser/report.json','{}'); z.writestr('browser-workspace-tabs/report.json','{}')
            r.safe_extract(archive,out)
            self.assertTrue((out/'browser/report.json').is_file())
            self.assertTrue((out/'browser-workspace-tabs/report.json').is_file())
            self.assertEqual(r.DESTINATIONS['browser-evidence'], 'artifacts/reports')
            with self.assertRaises(RuntimeError): r.safe_extract(archive,out)

    def test_zip_traversal_absolute_symlink_and_git_overwrite_rejected(self):
        for name in ['../escape', '/absolute', '.git/config', 'x\\escape', 'C:/drive']:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                a=Path(d)/'input.zip'
                with zipfile.ZipFile(a,'w') as z: z.writestr(name,'x')
                with self.assertRaises(RuntimeError): r.safe_extract(a,Path(d)/'out')
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'input.zip'; i=zipfile.ZipInfo('link'); i.external_attr=0o120777 << 16
            with zipfile.ZipFile(a,'w') as z: z.writestr(i,'target')
            with self.assertRaises(RuntimeError): r.safe_extract(a,Path(d)/'out')

    def test_signed_download_drops_credentials_and_checks_bytes(self):
        body=b'approved bytes'; digest='sha256:'+r.hashlib.sha256(body).hexdigest()
        requests=[]
        class Opener:
            def open(self, req, **kwargs):
                requests.append(req)
                if len(requests)==1:
                    raise HTTPError(req.full_url,302,'redirect',{'Location':'https://productionresultssa0.blob.core.windows.net/artifact?signature=fake'},None)
                return io.BytesIO(body)
        with tempfile.TemporaryDirectory() as d, patch.object(r,'build_opener',return_value=Opener()):
            target=Path(d)/'artifact.zip'
            r.download(self.gh,self.gh.base+'/actions/artifacts/1/zip',target,digest,len(body))
            self.assertEqual(target.read_bytes(),body)
            self.assertIn('Authorization',requests[0].headers)
            self.assertNotIn('Authorization',requests[1].headers)

    def test_bad_download_hash_removed(self):
        class Opener:
            def open(self,*args,**kwargs): return io.BytesIO(b'wrong')
        with tempfile.TemporaryDirectory() as d, patch.object(r,'build_opener',return_value=Opener()):
            target=Path(d)/'artifact.zip'
            with self.assertRaises(RuntimeError): r.download(self.gh,self.gh.base+'/actions/artifacts/1/zip',target,'sha256:'+'a'*64,5)
            self.assertFalse(target.exists())

    def test_untrusted_redirect_never_requested(self):
        class Opener:
            calls=0
            def open(self,req,**kwargs):
                self.calls+=1
                raise HTTPError(req.full_url,302,'redirect',{'Location':'https://evil.example/artifact'},None)
        opener=Opener()
        with tempfile.TemporaryDirectory() as d, patch.object(r,'build_opener',return_value=opener):
            with self.assertRaises(RuntimeError): r.download(self.gh,self.gh.base+'/actions/artifacts/1/zip',Path(d)/'a','sha256:'+'a'*64,1)
        self.assertEqual(opener.calls,1)

    def test_original_plan_identity_required(self):
        plan=dict(repository=r.REPOSITORY, version=r.VERSION, source_sha=r.SOURCE, run_id=r.RUN, run_number=21, branch='develop', channel='develop', tag='develop')
        r.verify_plan(plan,self.spec)
        for key in plan:
            with self.subTest(key=key), self.assertRaises(RuntimeError): r.verify_plan(dict(plan,**{key:None}),self.spec)

    def test_public_spec_has_no_private_backup_ids(self):
        self.assertNotIn('libfile_',r.SPEC_PATH.read_text())

    def test_workflow_has_no_build_version_bump_or_latest_write(self):
        workflow=(r.SPEC_PATH.parent/'workflows/recover-dev21.yml').read_text()
        for forbidden in ['release prepare', 'build_images.py', 'build_windows.py', 'build_macos.py', 'versioning set']:
            self.assertNotIn(forbidden,workflow)
        self.assertIn('needs: recover',workflow)
        self.assertIn('Recuperar assets dev.21',workflow)
        self.assertIn(r.SOURCE,workflow)
        self.assertIn('group: escritura-release-mutations',workflow)


if __name__ == '__main__': unittest.main()
