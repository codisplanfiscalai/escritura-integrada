"""Recibo GHCR do mesmo run; não cria release nem distribui binários."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path

from scripts.image_tools import validate_manifest
from .delivery_policy import delivery_mode
from .github_api import GitHub
from .release import guard, validate_plan, write_json


def images_hash(images):
    return hashlib.sha256(json.dumps(images, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def receipt(plan, images, env):
    validate_plan(plan)
    if (plan.get('branch') != 'develop' or plan.get('delivery_mode') != 'ghcr_only'
            or delivery_mode('develop') != 'ghcr_only'):
        raise ValueError('Recibo exclusivo GHCR exige a pausa versionada em develop.')
    expected = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': plan['repository'],
                'GITHUB_REF': 'refs/heads/develop', 'GITHUB_JOB': 'publish',
                'GITHUB_WORKFLOW_REF': plan['repository'] + '/.github/workflows/release.yml@refs/heads/develop',
                'GITHUB_SHA': plan['trigger_sha'], 'GITHUB_RUN_ID': str(plan['run_id']),
                'GITHUB_RUN_NUMBER': str(plan['run_number'])}
    if any(env.get(k) != v for k, v in expected.items()) or env.get('GITHUB_EVENT_NAME') not in ('push', 'workflow_dispatch'):
        raise ValueError('Contexto de publicação não corresponde ao plano confiável.')
    attempt = env.get('GITHUB_RUN_ATTEMPT', '')
    if not attempt.isdecimal() or int(attempt) < plan['run_attempt']:
        raise ValueError('Tentativa inválida.')
    validate_manifest(images)
    if (any(images.get(k) != plan[k] for k in ('source_sha', 'version', 'channel'))
            or images.get('smoke', {}).get('status') != 'passed'):
        raise ValueError('Imagens ou smoke divergem do commit planejado.')
    return {'schema': 'escritura-ghcr-publication/1', 'status': 'published',
            **{k: plan[k] for k in ('repository', 'version', 'source_sha', 'trigger_sha', 'run_id', 'run_number', 'delivery_mode')},
            'run_attempt': int(attempt), 'images_sha256': images_hash(images),
            'desktop_binaries': False, 'github_release_created': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=Path('build/ci-plan.json'))
    parser.add_argument('--images', type=Path, default=Path('artifacts/images-published.json'))
    parser.add_argument('--output', type=Path, default=Path('artifacts/publication.json'))
    args = parser.parse_args()
    plan, images = (json.loads(p.read_text()) for p in (args.plan, args.images))
    result = receipt(plan, images, os.environ)
    guard(GitHub(), plan)  # develop advancing during the push still blocks publication/promotion.
    write_json(args.output, result)


if __name__ == '__main__':
    main()
