"""Durable, opt-in collection for both services, on the existing receipt/cursor store."""
import asyncio
import json
import time
import threading
import uuid
from datetime import datetime, timezone

from .core import DomainError, audit, company_row, digest, now, pack
from .db import request_context
from .permissions import decision, require
from .reception_configuration import configuration
from .reception_service import LEASE_SECONDS

SCOPE = 'reception-automation-v1'
PROVIDERS = ('nfe_distribution', 'nfse_adn')
DEFAULT_INTERVAL = 1440  # Minutes: 24 hours between completed collections.
BLOCK_REASONS = {
    'reception_not_configured': 'Cadastre o certificado A1 desta empresa antes de reagendar.',
    'reception_environment_disabled': 'Habilite este serviço e ambiente no cadastro do A1 antes de reagendar.',
    'reception_certificate_expired': 'O certificado está fora da validade. Atualize o A1 antes de reagendar.',
    'reception_certificate_identity': 'O certificado não corresponde à identidade exigida para esta empresa.',
    'reception_procuration_required': 'A consulta requer procuração/autorização válida para o certificado cadastrado.',
    'reception_credentials': 'Não foi possível carregar o A1. Confira o cadastro e a senha de proteção.',
    'reception_vault_unavailable': 'O cofre A1 está indisponível. Confira a configuração da instalação.',
    'reception_dependency_missing': 'O runtime A1 está incompleto. Confira a instalação.',
    'stale_reception_configuration': 'A configuração mudou. Confira os parâmetros e salve a automação novamente.',
    'forbidden': 'Permissão de acesso à empresa ou de recepção fiscal revogada.',
}



class ReceptionAutomation:
    def __init__(self, core, reception, clock=time.time):
        self.core, self.db, self.reception, self.clock = core, core.db, reception, clock
        self.stopping = threading.Event()

    def _row(self, conn, cid, provider):
        if provider not in PROVIDERS:
            raise DomainError('Serviço de automação inválido.')
        row = conn.execute('SELECT result_json FROM operations WHERE company_id=? AND scope=? AND key=?',
                           (cid, SCOPE, provider)).fetchone()
        return json.loads(row['result_json']) if row else {
            'version': 0, 'enabled': False, 'interval_minutes': DEFAULT_INTERVAL,
            'status': 'disabled', 'next_run_at': None, 'last_success_at': None,
            'run_id': None, 'pages': 0, 'downloaded': 0, 'lease_id': None,
            'lease_until': 0, 'attempt_id': None, 'failures': 0, 'last_error': None}

    def _write(self, conn, cid, provider, row):
        conn.execute('''INSERT INTO operations(company_id,scope,key,request_hash,result_json,created_at)
                        VALUES(?,?,?,?,?,?) ON CONFLICT(company_id,scope,key)
                        DO UPDATE SET request_hash=excluded.request_hash,result_json=excluded.result_json''',
                     (cid, SCOPE, provider, digest([cid, provider, row['version']]), pack(row), now()))

    def _authorize(self, conn, cid, uid, edit=False):
        require(conn, uid, cid, 'system.companies', 'edit' if edit else 'read')
        company_row(conn, cid)
        if edit:
            self.reception._access(conn, uid, cid, 'import')

    @staticmethod
    def public(row):
        fields = ('version', 'enabled', 'interval_minutes', 'status', 'environment',
                  'next_run_at', 'last_success_at', 'last_worker_at', 'pages',
                  'downloaded', 'last_error', 'last_receipt')
        return {key: row[key] for key in fields if key in row}

    def settings(self, cid, uid):
        with self.db.read() as conn:
            self._authorize(conn, cid, uid)
            return {'services': {p: self.public(self._row(conn, cid, p)) for p in PROVIDERS},
                    'can_edit': all(decision(conn, uid, cid, r, a)['allowed'] for r, a in
                        [('system.companies', 'edit'), ('fiscal.imports', 'read'), ('fiscal.imports', 'import')])}

    def save(self, cid, uid, actor, provider, payload):
        if not isinstance(payload, dict) or set(payload) != {'version', 'enabled', 'interval_minutes'}:
            raise DomainError('Informe versão, habilitação e intervalo em minutos.')
        if type(payload['enabled']) is not bool or type(payload['interval_minutes']) is not int or not 1 <= payload['interval_minutes'] <= 525600:
            raise DomainError('O intervalo deve ser um número inteiro de 1 a 525600 minutos.')
        with self.db.transaction() as conn:
            self._authorize(conn, cid, uid, True)
            old = self._row(conn, cid, provider)
            if type(payload['version']) is not int or payload['version'] != old['version']:
                raise DomainError('Automação alterada. Recarregue o cadastro.', 409, 'stale_version')
            if payload['enabled'] and old['lease_until'] > self.clock():
                raise DomainError('Aguarde o lote atual para alterar o agendamento. Você pode desabilitar a automação.', 409, 'reception_busy')
            company = company_row(conn, cid)
            selected = configuration(conn, cid, provider, self.reception.credentials)
            row = old | payload | {'version': old['version'] + 1, 'staff_id': uid,
                'target_tax_id': company['tax_id'], 'environment': selected['environment'],
                'configuration_revision': selected['revision'], 'lease_id': None, 'lease_until': 0,
                'last_error': None, 'failures': 0}
            if not payload['enabled']:
                row.update(status='disabled', next_run_at=None)
            elif (old.get('status') == 'blocked' or not old['enabled']
                  or old.get('configuration_revision') != selected['revision']):
                # Explicit re-enable resumes from the canonical cursor, never resets NSU.
                row.update(status='pending', next_run_at=self.clock(), attempt_id=None, run_id=None)
            else:
                row.update(status='pending' if old.get('run_id') else 'idle',
                           next_run_at=max(self.clock(), (old.get('last_success_at') or self.clock()) + payload['interval_minutes'] * 60)
                           if not old.get('run_id') else max(self.clock(), old.get('next_run_at') or 0))
            self._write(conn, cid, provider, row)
            audit(conn, cid, actor, 'configure', 'reception-automation', provider,
                  {'enabled': row['enabled'], 'interval_minutes': row['interval_minutes'], 'environment': row['environment']})
            return self.public(row)

    def _claim(self, cid, provider):
        with self.db.transaction() as conn:
            row = self._row(conn, cid, provider)
            stamp = self.clock()
            if not row['enabled'] or row['status'] == 'blocked' or row['lease_until'] > stamp or (row['next_run_at'] or 0) > stamp:
                return None
            try:
                self._authorize(conn, cid, row['staff_id'], True)
                selected = configuration(conn, cid, provider, self.reception.credentials)
                company = company_row(conn, cid)
                if selected['revision'] != row['configuration_revision'] or company['tax_id'] != row['target_tax_id']:
                    raise DomainError('Configuração alterada. Revise e salve a automação novamente.', 409, 'stale_reception_configuration')
                state = self.reception._state(conn, cid, provider + ':' + row['environment'] + ':' + row['target_tax_id'])
                due = max(state['next_allowed_at'], state['lease_until'])
                if due > stamp:
                    row.update(status='waiting', next_run_at=due)
                    self._write(conn, cid, provider, row)
                    return None
            except DomainError as error:
                row.update(status='blocked', last_error=BLOCK_REASONS.get(error.code, 'Permissão, empresa ou configuração alterada. Revise o cadastro e salve a automação.'))
                self._write(conn, cid, provider, row)
                return None
            if not row['run_id']:
                row.update(run_id=uuid.uuid4().hex, pages=0, downloaded=0,
                           period=datetime.fromtimestamp(stamp, timezone.utc).strftime('%Y-%m'))
            row.update(status='running', lease_id=uuid.uuid4().hex, lease_until=stamp + LEASE_SECONDS,
                       attempt_id=row['attempt_id'] or 'auto-' + uuid.uuid4().hex,
                       last_worker_at=stamp)
            self._write(conn, cid, provider, row)
            return row

    def _finish(self, cid, provider, claimed, result=None, error=None):
        with self.db.transaction() as conn:
            row = self._row(conn, cid, provider)
            if (row['version'] != claimed['version'] or row['lease_id'] != claimed['lease_id']
                    or row['lease_until'] <= self.clock() or not row['enabled']):
                return  # Disabled/reconfigured while the already-dispatched page committed.
            state = self.reception._state(conn, cid, provider + ':' + row['environment'] + ':' + row['target_tax_id'])
            stamp = self.clock()
            row.update(lease_id=None, lease_until=0)
            if error is not None:
                if error.code in {'reception_cooldown', 'reception_busy'}:
                    row.update(status='waiting', next_run_at=max(stamp + 60, state['next_allowed_at'], state['lease_until']))
                else:
                    row.update(status='blocked', last_error=BLOCK_REASONS.get(error.code, 'Consulta sem confirmação ou bloqueada. Confira o recibo anterior antes de reagendar.'))
            elif result['state'] == 'received' and result.get('cursor_advanced'):
                row['pages'] += 1
                row['downloaded'] += len(result.get('entries', []))
                row.update(attempt_id=None, last_receipt=result.get('receipt_key'), failures=0, last_error=None)
                if result.get('has_more'):
                    row.update(status='pending', next_run_at=max(stamp, state['next_allowed_at']))
                else:
                    row.update(status='idle', run_id=None, last_success_at=stamp,
                               next_run_at=max(stamp + row['interval_minutes'] * 60, state['next_allowed_at']))
            elif result['state'] == 'no_documents' or result['state'] == 'received' and not result.get('has_more'):
                row.update(status='idle', run_id=None, attempt_id=None, last_success_at=stamp,
                           last_receipt=result.get('receipt_key'), last_error=None, failures=0,
                           next_run_at=max(stamp + row['interval_minutes'] * 60, state['next_allowed_at']))
            elif result['state'] in {'remote_unavailable', 'cursor_synchronized'} or result.get('status_code') == '656':
                row['failures'] += 1
                row.update(status='waiting' if row['failures'] < 5 else 'blocked', attempt_id=None,
                           last_receipt=result.get('receipt_key'), last_error='Serviço indisponível ou aguardando intervalo. Cursor e originais preservados.',
                           next_run_at=max(stamp + row['interval_minutes'] * 60, state['next_allowed_at']))
            else:
                row.update(status='blocked', last_receipt=result.get('receipt_key'),
                           last_error='Resposta inconclusiva ou recusada. Confira o recibo; nenhuma nova tentativa automática foi enviada.')
            self._write(conn, cid, provider, row)

    def run_one(self, cid, provider):
        # Never inherit a browser's session/context in a background execution.
        token = request_context.set(None)
        try:
            claimed = self._claim(cid, provider)
            if claimed is None:
                return False
            try:
                result = self.reception.query(cid, {'provider': provider, 'environment': claimed['environment'],
                    'period': claimed['period'], 'idempotency_key': claimed['attempt_id']},
                    'reception-automation', claimed['staff_id'], expected_configuration=claimed['configuration_revision'])
            except DomainError as error:
                self._finish(cid, provider, claimed, error=error)
            except Exception:
                # Original receipt/lease survive; never log driver/credential text.
                self._finish(cid, provider, claimed, error=DomainError('Consulta sem confirmação.', 503, 'reception_uncertain'))
            else:
                self._finish(cid, provider, claimed, result=result)
            return True
        finally:
            request_context.reset(token)

    def tick(self):
        with self.db.read() as conn:
            candidates = [(r['company_id'], r['key']) for r in conn.execute(
                'SELECT company_id,key FROM operations WHERE scope=? ORDER BY company_id,key', (SCOPE,))]
        for cid, provider in candidates:
            if self.stopping.is_set():
                break
            try:
                self.run_one(cid, provider)  # One page per identity: fairness, no total-history cutoff.
            except Exception:
                pass  # Persistence failure retains durable attempt/lease for recovery.

    async def run(self):
        self.stopping.clear()
        try:
            while True:
                task = asyncio.create_task(asyncio.to_thread(self.tick))
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    self.stopping.set()
                    await task  # Finish the bounded in-flight page; no new company/page.
                    raise
                except Exception:
                    # A transient journal read failure must not terminate the worker.
                    await asyncio.sleep(30)
                    continue
                await asyncio.sleep(5)
        finally:
            self.stopping.set()
