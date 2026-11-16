"""Admin-only bridge to an explicitly installed local preparation executor.

This process has no Docker authority. Downloading an image never means cutover.
"""
from __future__ import annotations

import json
import os
import re
import socket

from fastapi import Body, Request

from . import __version__
from .core import DomainError
from .permissions import require

MAX_REPLY = 65536


class ExecutorClient:
    def __init__(self, path):
        self.path = path

    def call(self, action, **payload):
        if not self.path:
            raise DomainError('Executor externo não configurado. Instalação e permissões no host dependem do administrador.', 503, 'executor_unavailable')
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(120 if action in ('check', 'check-current', 'status') else 4)
                client.connect(self.path)
                client.sendall(json.dumps({'action': action, **payload}).encode() + b'\n')
                with client.makefile('rb') as stream:
                    raw = stream.readline(MAX_REPLY + 1)
                if len(raw) > MAX_REPLY or not raw.endswith(b'\n'):
                    raise ValueError('protocol')
                reply = json.loads(raw)
                if type(reply) is not dict or type(reply.get('status')) is not int or type(reply.get('data')) is not dict:
                    raise ValueError('protocol')
                if reply['status'] != 200:
                    # Only the reviewed executor protocol supplies these messages.
                    raise DomainError(reply['data'].get('detail', 'Executor recusou a operação.'), reply['status'], reply['data'].get('code', 'executor_error'))
                return reply['data']
        except (OSError, ValueError, KeyError) as exc:
            raise DomainError('Executor indisponível ou resposta inválida. Consulte o histórico antes de repetir um download; o resultado pode estar pendente.', 503, 'executor_unavailable') from exc


def fields(payload, expected):
    if type(payload) is not dict or set(payload) != set(expected):
        raise DomainError('Campos inválidos para esta operação.', 422, 'invalid_request')
    return payload


def register(application, core):
    application.state.docker_executor = ExecutorClient(os.environ.get('ESCRITURA_UPDATE_SOCKET', ''))

    def invoke(request, action, **payload):
        # Recheck live credentials/role at admission, including global GET routes.
        with core.db.read() as conn:
            require(conn, request.state.session['user']['id'], None, admin=True)
        if application.state.demo:
            raise DomainError('Preparação Docker indisponível no modo de demonstração.', 403, 'forbidden')
        return application.state.docker_executor.call(action, **payload)

    @application.get('/api/docker-updates')
    def status(request: Request):
        if not application.state.docker_executor.path:
            # This is application metadata, not an assertion about a Docker image.
            return {'configured': False, 'application_version': __version__, 'installed': None,
                    'jobs': [], 'cutover_supported': False, 'preparation_supported': False,
                    'limitation': 'Executor externo não configurado. Imagem/digest não verificados; atualização da aplicação ainda indisponível.'}
        return {**invoke(request, 'status'), 'application_version': __version__}

    @application.post('/api/docker-updates/check')
    def check(request: Request, payload: dict = Body(...)):
        fields(payload, [])
        return invoke(request, 'check-current')

    @application.post('/api/docker-updates/prepare')
    def prepare(request: Request, payload: dict = Body(...)):
        fields(payload, ['plan_id', 'idempotency_key'])
        if any(not isinstance(v, str) or not re.fullmatch(r'[a-f0-9]{32}', v) for v in payload.values()):
            raise DomainError('Identificador de preparação inválido.', 422, 'invalid_request')
        return invoke(request, 'prepare', **payload, actor=str(request.state.session['user']['id']))
