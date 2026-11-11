"""One-off dev.21 recovery promotion. Never changes latest or normal release guards."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from .github_api import GitHub, NoRedirect
from .image_aliases import Registry, pull_identity
from .release import write_json
from scripts.image_tools import DIGEST, GHCR_PREFIX

REPOSITORY = 'codisplanfiscalai/escritura-integrada'
SOURCE = '1c686036d7e337632a7eb7b204b016063f6df32f'
VERSION = '0.8.0-dev.21'
IMAGE = 'sha256:e875f7402e474717340e73d6a1e6bbc95fbc6d72d34320dd0ced133b05b45c76'
LATEST = 'sha256:1c3dc4deb644ac735fa5c49d3d8ca7e410143659a7cb51a2acb2fa0e64e66c59'
MAIN = '2ab5d4ea49858b1f9e8716fe46bb478e2d848c88'
ORIGINAL_RUN = 42978878696
BRANCH = 'ops/recover-release-dev21'
WORKFLOW = '.github/workflows/recover-dev21.yml'
PROOF_NAME = 'recovery-proof.json'


def validate_spec(spec):
    expected = {'repository': REPOSITORY, 'source_sha': SOURCE, 'version': VERSION,
                'image_digest': IMAGE, 'latest_digest_unchanged': LATEST,
                'main_sha': MAIN, 'original_run_id': ORIGINAL_RUN, 'original_run_attempt': 2}
    if any(spec.get(key) != value for key, value in expected.items()):
        raise ValueError('Recovery alias plan differs from the authorized dev.21 identities.')
    if 'aliases' in spec and spec['aliases'] != ['develop']:
        raise ValueError('Recovery can only promote develop.')


def read_proof(gh, asset):
    """Download a bounded release receipt; cross-host requests NEVER carry token."""
    asset_id = asset.get('id')
    if type(asset_id) is not int or asset_id <= 0 or asset.get('state') != 'uploaded':
        raise RuntimeError('Recovery receipt asset is not uploaded.')
    if not DIGEST.fullmatch(asset.get('digest', '')):
        raise RuntimeError('Recovery receipt asset lacks its SHA-256.')
    if not 0 < asset.get('size', 0) <= 1024 * 1024:
        raise RuntimeError('Recovery receipt has invalid size.')
    opener = build_opener(NoRedirect())
    headers = {'Accept': 'application/octet-stream', 'User-Agent': 'escritura-recovery-dev21'}
    if gh.token:
        headers['Authorization'] = 'Bearer ' + gh.token
    url = 'https://api.github.com' + gh.base + '/releases/assets/' + str(asset_id)
    try:
        response = opener.open(Request(url, headers=headers), timeout=60)
    except HTTPError as exc:
        if exc.code != 302:
            raise RuntimeError('Recovery receipt download failed, HTTP ' + str(exc.code)) from None
        target = exc.headers.get('Location', '')
        parsed = urlsplit(target)
        if (parsed.scheme != 'https' or parsed.hostname != 'release-assets.githubusercontent.com'
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise RuntimeError('Recovery receipt redirect host rejected.') from None
        # New request, deliberately no Authorization or cookies. Further redirects fail.
        response = opener.open(Request(target, headers={'User-Agent': headers['User-Agent']}), timeout=60)
    with response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) != asset['size'] or 'sha256:' + hashlib.sha256(raw).hexdigest() != asset['digest']:
        raise RuntimeError('Recovery receipt size/hash mismatch.')
    return json.loads(raw)


def verify_recovery(gh, spec):
    from .recover_dev21 import verify_original, verify_heads, verify_published
    validate_spec(spec)
    if gh.repository != REPOSITORY:
        raise RuntimeError('Wrong recovery repository.')
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REF') != 'refs/heads/' + BRANCH:
        raise RuntimeError('Recovery promotion requires its exact operational workflow.')
    run_id = os.environ.get('GITHUB_RUN_ID', '')
    attempt = os.environ.get('GITHUB_RUN_ATTEMPT', '')
    recovery_sha = os.environ.get('GITHUB_SHA', '')
    if not run_id.isdigit() or not attempt.isdigit() or len(recovery_sha) != 40:
        raise RuntimeError('Recovery workflow identity is missing.')
    verify_heads(gh, spec)
    verify_original(gh, spec)
    verify_published(gh, spec)
    if gh.commit_sha(gh.ref('heads/' + BRANCH)) != recovery_sha:
        raise RuntimeError('Recovery operational head changed.')
    path = gh.base + '/actions/runs/' + run_id
    run = gh.request('GET', path)
    expected = {'id': int(run_id), 'run_attempt': int(attempt), 'head_sha': recovery_sha,
                'path': WORKFLOW, 'head_branch': BRANCH, 'event': 'push', 'status': 'in_progress'}
    if any(run.get(key) != value for key, value in expected.items()):
        raise RuntimeError('Current recovery execution identity is not approved.')
    jobs = list(gh.pages(path + '/attempts/' + attempt + '/jobs', key='jobs'))
    matches = [job for job in jobs if job.get('name') == 'Recuperar assets dev.21']
    if len(matches) != 1 or matches[0].get('status') != 'completed' or matches[0].get('conclusion') != 'success':
        raise RuntimeError('Recovery publication job is not successful.')
    release = gh.release('develop')
    assets = list(gh.pages(gh.base + '/releases/' + str(release['id']) + '/assets'))
    proofs = [asset for asset in assets if asset.get('name') == PROOF_NAME]
    if len(proofs) != 1:
        raise RuntimeError('Release must contain exactly one recovery receipt.')
    proof = read_proof(gh, proofs[0])
    required = {'status': 'verified', 'version': VERSION, 'source_sha': SOURCE,
                'original_run_id': ORIGINAL_RUN, 'recovery_run_id': int(run_id),
                'recovery_sha': recovery_sha}
    if any(proof.get(key) != value for key, value in required.items()):
        raise RuntimeError('Published recovery receipt does not match this recovery.')
    inventory = proof.get('assets')
    if not isinstance(inventory, list) or not inventory:
        raise RuntimeError('Recovery receipt asset inventory is missing.')
    expected = {}
    prefix = 'EscrituraIntegrada-' + VERSION + '-'
    for entry in inventory:
        if not isinstance(entry, dict):
            raise RuntimeError('Recovery receipt asset entry is invalid.')
        name = entry.get('name', '')
        if (not isinstance(name, str) or not name.startswith(prefix) or Path(name).name != name
                or name in expected or type(entry.get('size')) is not int or entry['size'] <= 0
                or not isinstance(entry.get('sha256'), str)
                or not DIGEST.fullmatch('sha256:' + entry['sha256'])):
            raise RuntimeError('Recovery receipt asset identity is invalid or duplicated.')
        expected[name] = entry
    actual = {asset.get('name'): asset for asset in assets}
    if len(actual) != len(assets) or set(actual) != set(expected) | {PROOF_NAME}:
        raise RuntimeError('Current release inventory differs from the recovery receipt.')
    for name, entry in expected.items():
        asset = actual[name]
        if (asset.get('state') != 'uploaded' or asset.get('size') != entry['size']
                or asset.get('digest') != 'sha256:' + entry['sha256']):
            raise RuntimeError('Current release asset differs from the recovery receipt: ' + name)
    run_url = 'https://github.com/' + REPOSITORY + '/actions/runs/' + run_id
    if run.get('html_url') != run_url or run_url not in release.get('body', ''):
        raise RuntimeError('Release lacks the verified recovery run link.')
    return {'run_url': run_url, 'proof_digest': proofs[0]['digest'], 'original_run_id': ORIGINAL_RUN}


@contextmanager
def anonymous_docker():
    previous = os.environ.get('DOCKER_CONFIG')
    with tempfile.TemporaryDirectory(prefix='escritura-anonymous-') as directory:
        os.environ['DOCKER_CONFIG'] = directory
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop('DOCKER_CONFIG', None)
            else:
                os.environ['DOCKER_CONFIG'] = previous


def promote(spec, gh, registry, public, output, *, pull=pull_identity):
    report = {'status': 'checking', 'version': VERSION, 'source_sha': SOURCE,
              'alias': 'develop', 'digest': IMAGE}
    try:
        validate_spec(spec)
        report['recovery'] = verify_recovery(gh, spec)
        if registry.manifest('latest')['digest'] != LATEST:
            raise RuntimeError('latest changed before recovery promotion.')
        report['latest_before'] = LATEST
        source = registry.manifest(IMAGE)
        if source['digest'] != IMAGE or registry.manifest(VERSION)['digest'] != IMAGE:
            raise RuntimeError('Versioned image changed; promotion blocked.')
        image_id = json.loads(source['raw']).get('config', {}).get('digest', '')
        if not DIGEST.fullmatch(image_id):
            raise RuntimeError('Image config digest is invalid.')
        plan = {'version': VERSION, 'source_sha': SOURCE, 'digest': IMAGE}
        report['source_pull'] = pull(GHCR_PREFIX + '@' + IMAGE, plan, image_id)
        if public.manifest(IMAGE)['digest'] != IMAGE:
            raise RuntimeError('Image digest is not publicly readable.')
        with anonymous_docker():
            report['anonymous_source_pull'] = pull(GHCR_PREFIX + '@' + IMAGE, plan, image_id)
        previous = registry.manifest('develop', missing=True)
        report['previous_digest'] = previous['digest'] if previous else None
        # Revalidate all gates immediately before the only mutation.
        verify_recovery(gh, spec)
        if registry.manifest('latest')['digest'] != LATEST or registry.manifest(VERSION)['digest'] != IMAGE:
            raise RuntimeError('Registry changed during verification.')
        report['status'] = 'writing'
        write_json(output, report)
        if report['previous_digest'] != IMAGE:
            registry.put_alias('develop', source)
        if registry.manifest('develop')['digest'] != IMAGE or public.manifest('develop')['digest'] != IMAGE:
            raise RuntimeError('Published develop digest verification failed.')
        with anonymous_docker():
            report['anonymous_alias_pull'] = pull(GHCR_PREFIX + ':develop', plan, image_id)
        if registry.manifest('latest')['digest'] != LATEST or public.manifest('latest')['digest'] != LATEST:
            raise RuntimeError('latest changed during recovery promotion; no automatic rollback.')
        if registry.manifest(VERSION)['digest'] != IMAGE:
            raise RuntimeError('Versioned image changed after promotion.')
        report.update(status='verified', latest_after=LATEST)
        return report
    except Exception as exc:
        report.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        write_json(output, report)


def main():
    from .recover_dev21 import load_spec
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('artifacts/recovery-alias.json'))
    args = parser.parse_args()
    spec = load_spec()
    validate_spec(spec)
    credential = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if not credential:
        raise RuntimeError('Ephemeral GitHub workflow token is required.')
    registry, public = Registry(), Registry()
    registry.authenticate(actor=os.environ.get('GITHUB_ACTOR'), credential=credential)
    public.authenticate()
    promote(spec, GitHub(), registry, public, args.output)


if __name__ == '__main__':
    main()
