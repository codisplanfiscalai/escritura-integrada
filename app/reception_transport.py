"""Single bounded mTLS query, fixed official endpoints, no redirect or retry."""
from dataclasses import dataclass, field
import http.client
from http.client import HTTPSConnection
import ssl
import time
from urllib.parse import urlsplit

from .core import DomainError
from .importers import MAX_FILE_BYTES
from .reception import ADN_ENDPOINTS, NFE_ENDPOINTS


@dataclass(frozen=True)
class RemoteReply:
    status: int
    body: bytes = field(repr=False)
    retry_after: int = 0


class MtlsTransport:
    def send(self, plan, identity):
        url = urlsplit(plan['url'])
        allowed = {urlsplit(value).hostname for value in [*NFE_ENDPOINTS.values(), *ADN_ENDPOINTS.values()]}
        if url.scheme != 'https' or url.hostname not in allowed or url.port not in (None, 443) or url.username or url.password or url.fragment:
            raise DomainError('Destino da consulta não autorizado.', 400, 'reception_endpoint')
        # Plans are constructed by the service, never supplied by HTTP clients.
        provider = plan.get('provider')
        if provider == 'nfe_distribution':
            if plan['method'] != 'POST' or plan['url'] not in NFE_ENDPOINTS.values():
                raise DomainError('Operação NF-e não autorizada.', 400, 'reception_operation')
            from .reception import NFE_NS
            from .importers import _xml_tree
            root = _xml_tree(plan.get('body', b''))
            selectors = list(root.iter(f'{{{NFE_NS}}}distDFeInt'))
            if len(selectors) != 1 or [n.tag.rsplit('}',1)[-1] for n in selectors[0]] not in (['tpAmb','cUFAutor','CNPJ','distNSU'], ['tpAmb','cUFAutor','CPF','distNSU']):
                raise DomainError('Somente distribuição por NSU é permitida.', 400, 'reception_operation')
        elif provider == 'nfse_adn':
            import re
            if plan['method'] != 'GET' or plan.get('body') or not re.fullmatch(r'/contribuintes/DFe/[0-9]{15}', url.path):
                raise DomainError('Somente consulta ADN por NSU é permitida.', 400, 'reception_operation')
        else:
            raise DomainError('Provedor não autorizado.', 400, 'reception_operation')
        if identity.context.verify_mode != ssl.CERT_REQUIRED or not identity.context.check_hostname:
            raise DomainError('Validação TLS obrigatória.', 503, 'reception_tls')
        connection = HTTPSConnection(url.hostname, context=identity.context, timeout=10)
        deadline = time.monotonic() + 30
        try:
            headers = {'Accept': 'application/json' if provider == 'nfse_adn' else 'application/soap+xml',
                       'Accept-Encoding': 'identity', 'User-Agent': 'EscrituraIntegrada/Reception'}
            if plan.get('content_type'):
                headers['Content-Type'] = plan['content_type']
            path = url.path + ('?' + url.query if url.query else '')
            connection.request(plan['method'], path, body=plan.get('body'), headers=headers)
            reply = connection.getresponse()
            if reply.getheader('Content-Encoding', 'identity').lower() != 'identity':
                raise DomainError('Codificação HTTP da resposta não suportada; cursor preservado.', 502, 'reception_response_encoding')
            chunks, size = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                if connection.sock is not None:
                    connection.sock.settimeout(min(10, remaining))
                chunk = reply.read1(min(64*1024, MAX_FILE_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk); size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise DomainError('Resposta remota excede limite de tamanho; cursor preservado.', 502, 'reception_response_size')
            retry = reply.getheader('Retry-After', '')
            retry_after = min(int(retry), 86400) if retry.isascii() and retry.isdigit() and len(retry) < 8 else 0
            return RemoteReply(reply.status, b''.join(chunks), retry_after)
        except DomainError:
            raise
        except (OSError, http.client.HTTPException, ValueError):
            raise DomainError('Consulta remota não concluída. Resultado incerto; cursor preservado e intervalo de segurança aplicado.', 502, 'reception_transport_uncertain') from None
        finally:
            connection.close()
