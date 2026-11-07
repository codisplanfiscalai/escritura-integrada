"""Cliente REST pequeno: chamadas explícitas, sem shell e sem imprimir tokens."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class GitHubError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


class GitHub:
    def __init__(self, repository=None, token=None):
        self.repository = repository or os.environ.get('GITHUB_REPOSITORY', '')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', self.repository):
            raise GitHubError('GITHUB_REPOSITORY inválido ou ausente.')
        self.token = token if token is not None else os.environ.get('GH_TOKEN', os.environ.get('GITHUB_TOKEN', ''))
        self.base = '/repos/' + self.repository
        self.api_url = os.environ.get('GITHUB_API_URL', 'https://api.github.com').rstrip('/')
        if self.api_url != 'https://api.github.com':
            raise GitHubError('Este fluxo foi configurado para api.github.com; outro endpoint exige revisão explícita.')
        self.opener = build_opener(NoRedirect())

    def request(self, method, path, payload=None, *, missing=False, binary=None, content_type=None):
        if not path.startswith('/') or path.startswith('//'):
            raise GitHubError('Caminho REST inválido.')
        return self._request_url(method, self.api_url + path, payload, missing=missing, binary=binary, content_type=content_type)

    def _request_url(self, method, url, payload=None, *, missing=False, binary=None, content_type=None, content_length=None):
        if urlsplit(url).scheme != 'https' or urlsplit(url).hostname not in {'api.github.com', 'uploads.github.com'}:
            raise GitHubError('Host REST/upload não autorizado.')
        if method != 'GET' and not self.token:
            raise GitHubError('Token de execução ausente para a operação autenticada.')
        headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'escritura-integrada-ci'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        body = binary
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json; charset=utf-8'
        if content_type:
            headers['Content-Type'] = content_type
        if content_length is not None:
            headers['Content-Length'] = str(int(content_length))
        for attempt in range(3):
            try:
                with self.opener.open(Request(url, data=body, headers=headers, method=method), timeout=90) as response:
                    raw = response.read()
                    return json.loads(raw) if raw else None
            except HTTPError as exc:
                if exc.code == 404 and missing:
                    return None
                if method == 'GET' and exc.code in {429, 502, 503, 504} and attempt < 2:
                    time.sleep(min(2 ** (attempt + 1), 8))
                    continue
                try:
                    detail = json.loads(exc.read(8000)).get('message', 'Erro da API')
                except (ValueError, AttributeError):
                    detail = 'Erro da API'
                permission_hint = ''
                if method != 'GET' and exc.code in {403, 404}:
                    permission_hint = ' Confira permissions do workflow e se o alvo altera arquivos de workflow em relação à branch padrão; GITHUB_TOKEN não concede Workflows write.'
                raise GitHubError(f'GitHub {exc.code} em {method} {urlsplit(url).path}: {detail}.{permission_hint}', exc.code) from None
            except URLError as exc:
                raise GitHubError(f'Falha de conexão com a API do GitHub ({type(exc.reason).__name__}).') from None
        raise GitHubError('A API não concluiu a leitura.')

    def pages(self, path, *, key=None, params=None):
        params = dict(params or {})
        params['per_page'] = 100
        for page in range(1, 101):
            params['page'] = page
            response = self.request('GET', path + ('&' if '?' in path else '?') + urlencode(params))
            entries = response[key] if key else response
            if not isinstance(entries, list):
                raise GitHubError('Resposta paginada inesperada.')
            yield from entries
            if len(entries) < 100:
                return
        raise GitHubError('Paginação excedeu 10.000 registros; manutenção exige revisão.')

    def ref(self, name, missing=False):
        return self.request('GET', self.base + '/git/ref/' + quote(name, safe='/'), missing=missing)

    def commit_sha(self, reference):
        if reference is None:
            return None
        obj = reference['object']
        for _ in range(8):
            if obj['type'] == 'commit':
                return obj['sha']
            if obj['type'] != 'tag':
                raise GitHubError('Referência não aponta para commit/tag.')
            obj = self.request('GET', self.base + '/git/tags/' + obj['sha'])['object']
        raise GitHubError('Cadeia de tags excessivamente profunda.')

    def file(self, path, sha, missing=False):
        result = self.request('GET', self.base + '/contents/' + quote(path, safe='/') + '?' + urlencode({'ref': sha}), missing=missing)
        if result is None:
            return None
        if result.get('type') != 'file' or result.get('encoding') != 'base64':
            raise GitHubError('Manifest deve ser arquivo UTF-8 pequeno em base64.')
        return base64.b64decode(result['content']).decode('utf-8')

    def release(self, tag, missing=False):
        published = self.request('GET', self.base + '/releases/tags/' + quote(tag, safe=''), missing=True)
        if published is not None:
            return published
        # /releases/tags documents published releases. A failed upload leaves a
        # draft, visible through the authenticated list endpoint, to be resumed.
        matches = [item for item in self.pages(self.base + '/releases') if item.get('tag_name') == tag]
        if len(matches) > 1:
            raise GitHubError('Mais de uma release corresponde à tag ' + tag + '; revisão manual necessária.')
        if matches:
            return matches[0]
        if missing:
            return None
        raise GitHubError('Release não encontrada para a tag ' + tag + '.', 404)

    def upload(self, release, path: Path):
        url = release['upload_url'].split('{', 1)[0] + '?' + urlencode({'name': path.name})
        # Upload URLs are validated before the token is attached. Redirects are refused.
        # urllib/http.client streams a file object; an offline image archive must
        # not be copied into RAM. POST is intentionally never retried implicitly.
        with path.open('rb') as handle:
            return self._request_url('POST', url, binary=handle, content_type='application/octet-stream', content_length=path.stat().st_size)
