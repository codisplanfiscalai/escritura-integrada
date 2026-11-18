"""One-page capture shared by HTTP and future workers; same company/RBAC services.

State and idempotent run receipts use distinct namespaces in the existing
operations journal. Originals use stored_files. No new DB engine/schema is added.
"""
from __future__ import annotations

import base64
import json
import re
import time
import uuid

from .core import DomainError, audit, company_row, digest, now, pack, period
from .file_store import read_file, store_file
from .permissions import require
from .importers import ImportProblem
from .reception_adn import load_adn_json, read_adn_distribution, read_adn_absence
from .reception import (ADN_ENDPOINTS, NFE_ENDPOINTS, adn_rejection, adn_request,
                        nfe_request, read_nfe_distribution)
from .reception_credentials import _cnpj, query_cnpj
from .reception_vault import CompanyA1Vault
from .reception_configuration import require_configuration
from .reception_transport import MtlsTransport

STATE_SCOPE = 'fiscal-reception-state-v1'
RUN_SCOPE = 'fiscal-reception-run-v1'
LEASE_SECONDS = 600
# End-of-stream only, matching the national module's conservative policy.
# Positive pages continue immediately unless the server supplies Retry-After.
ADN_EMPTY_COOLDOWN_SECONDS = 3600
UF_CODES = dict(zip(['RO','AC','AM','RR','PA','AP','TO','MA','PI','CE','RN','PB','PE','AL','SE','BA','MG','ES','RJ','SP','PR','SC','RS','MS','MT','GO','DF'],
                    ['11','12','13','14','15','16','17','21','22','23','24','25','26','27','28','29','31','32','33','35','41','42','43','50','51','52','53']))


class ReceptionService:
    def __init__(self, core, credentials=None, transport=None, clock=time.time):
        self.core, self.db = core, core.db
        self.credentials = credentials or CompanyA1Vault(self.db)
        self.transport = transport or MtlsTransport()
        self.clock = clock

    def _access(self, conn, uid, cid, action='read'):
        require(conn, uid, cid, 'fiscal.imports', 'read')
        if action != 'read':
            require(conn, uid, cid, 'fiscal.imports', action)
        return company_row(conn, cid)

    def _operation(self, conn, cid, scope, key):
        return conn.execute('SELECT * FROM operations WHERE company_id=? AND scope=? AND key=?', (cid,scope,key)).fetchone()

    def _state(self, conn, cid, key):
        row = self._operation(conn, cid, STATE_SCOPE, key)
        return json.loads(row['result_json']) if row else {'cursor':'000000000000000','lease_id':None,'lease_until':0,'next_allowed_at':0}

    def _save_state(self, conn, cid, key, state):
        conn.execute('''INSERT INTO operations(company_id,scope,key,request_hash,result_json,created_at)
                        VALUES(?,?,?,?,?,?) ON CONFLICT(company_id,scope,key)
                        DO UPDATE SET result_json=excluded.result_json''', (cid,STATE_SCOPE,key,digest(key),pack(state),now()))

    def _key(self, value):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', value):
            raise DomainError('Informe uma chave idempotente de 8 a 100 letras, números, hífen ou sublinhado.')
        return value

    def _spec(self, provider, environment):
        endpoints = {'nfe_distribution': NFE_ENDPOINTS, 'nfse_adn': ADN_ENDPOINTS}
        if not isinstance(provider,str) or not isinstance(environment,str) or provider not in endpoints or environment not in endpoints[provider]:
            raise DomainError('Provedor ou ambiente de recepção inválido.', 400, 'reception_environment')

    def local_identity(self,cid,company,provider,environment):
        target=query_cnpj(company['tax_id'],provider)
        if provider == 'nfe_distribution' and company['state'] not in UF_CODES:
            raise DomainError('Informe a UF da empresa antes de consultar a distribuição NF-e.',409,'reception_company_uf')
        credential = self.credentials.load(cid, target, provider, environment)
        # Certificate relationship is checked independently of credential loader
        # so injected transports/workers cannot silently broaden company scope.
        if provider == 'nfse_adn':
            from .reception_credentials import adn_access_mode
            mode = adn_access_mode(target, credential.tax_id, credential.allow_procuration)
        else:
            if target[:8] != _cnpj(credential.tax_id)[:8]:
                raise DomainError('Certificado NF-e de outra raiz não é permitido.',409,'reception_certificate_identity')
            mode = 'CnpjBase' if target != credential.tax_id else 'InscricaoCertificado'
        return credential,mode

    def query(self, cid, payload, actor, uid, *, expected_configuration=None):
        if not isinstance(payload, dict) or set(payload) - {'provider','environment','period','idempotency_key'}:
            raise DomainError('Informe somente provedor, ambiente, competência e chave idempotente; certificados e URLs não são aceitos pela API.')
        provider, environment = payload.get('provider'), payload.get('environment')
        self._spec(provider, environment)
        competence, key = period(payload.get('period')), self._key(payload.get('idempotency_key'))
        with self.db.read() as conn:
            company = self._access(conn, uid, cid, 'import')
            target = query_cnpj(company['tax_id'],provider)
            revision=self.credentials.revision(conn,cid) if hasattr(self.credentials,'revision') else None
            identity = digest({'provider':provider,'environment':environment,'period':competence,'target':target})
            old = self._operation(conn,cid,RUN_SCOPE,key)
            if old:
                return self._repeat(old, identity)
            if expected_configuration is not None:
                require_configuration(conn,cid,provider,self.credentials,expected_configuration,environment)
        credential,mode=self.local_identity(cid,company,provider,environment)
        state_key = provider + ':' + environment + ':' + target
        lease = uuid.uuid4().hex
        with self.db.transaction() as conn:
            current = self._access(conn, uid, cid, 'import')
            if hasattr(self.credentials,'revision') and self.credentials.revision(conn,cid)!=revision:
                raise DomainError('A configuração A1 mudou. Reabra a consulta.',409,'stale_credential')
            if expected_configuration is not None:
                require_configuration(conn,cid,provider,self.credentials,expected_configuration,environment)
            if current['tax_id'] != target or current['state'] != company['state']:
                raise DomainError('Cadastro da empresa mudou; consulta não executada.',409,'stale_company')
            from .operational_settings import ensure_import_allowed
            ensure_import_allowed(conn,cid,0)
            old = self._operation(conn,cid,RUN_SCOPE,key)
            if old:
                return self._repeat(old,identity)
            state = self._state(conn,cid,state_key)
            stamp = self.clock()
            if state['lease_until'] > stamp:
                raise DomainError('Já existe consulta desta inscrição/provedor/ambiente em andamento ou aguardando recuperação.',409,'reception_busy')
            if state['next_allowed_at'] > stamp:
                raise DomainError('Aguarde o intervalo de consulta compartilhado desta empresa.',429,'reception_cooldown')
            cursor = state['cursor']
            # Reserve the external attempt before sending. An interrupted process
            # leaves a lease and idempotent uncertain run, never an advanced cursor.
            state.update(lease_id=lease,lease_until=stamp+LEASE_SECONDS,next_allowed_at=stamp+(3600 if provider=='nfe_distribution' else 0))
            self._save_state(conn,cid,state_key,state)
            conn.execute('INSERT INTO operations(company_id,scope,key,request_hash,result_json,created_at) VALUES(?,?,?,?,?,?)',
                         (cid,RUN_SCOPE,key,identity,pack({'state':'in_progress','provider':provider,'environment':environment,'period':competence,'cursor_before':cursor}),now()))
            audit(conn,cid,actor,'query-start','fiscal-reception',key,{'provider':provider,'environment':environment,'cursor':cursor})
        reply = None
        try:
            if provider == 'nfse_adn':
                plan = adn_request(target,environment,cursor,certificate_tax_id=credential.tax_id,allow_procuration=credential.allow_procuration)
            else:
                plan = nfe_request(target,UF_CODES[company['state']],environment,cursor)
            plan['provider'] = provider
            reply = self.transport.send(plan,credential)
            if not isinstance(reply.body,bytes) or len(reply.body)>20*1024*1024 or not 100 <= reply.status <= 599:
                raise DomainError('Resposta remota inválida; cursor preservado.',502,'reception_response_invalid')
            result, proposed, cooldown = self._interpret(provider,environment,cursor,reply,mode)
        except DomainError as exc:
            return self._finish(cid,uid,actor,key,identity,state_key,lease,target,competence,
                                {'state':'uncertain','code':exc.code},cursor,3600 if provider=='nfe_distribution' else 0,self._received_bytes(reply))
        except Exception:
            # Do not return driver messages, response bodies, paths or credentials.
            return self._finish(cid,uid,actor,key,identity,state_key,lease,target,competence,
                                {'state':'uncertain','code':'reception_transport_uncertain'},cursor,3600 if provider=='nfe_distribution' else 0,self._received_bytes(reply))
        return self._finish(cid,uid,actor,key,identity,state_key,lease,target,competence,result,proposed,cooldown,reply.body)

    def _received_bytes(self, reply):
        body = getattr(reply, 'body', None)
        return body if isinstance(body, bytes) and len(body) <= 20*1024*1024 else None

    def _repeat(self, row, identity):
        if row['request_hash'] != identity:
            raise DomainError('Chave idempotente já usada com outro alvo ou contexto.',409,'idempotency_conflict')
        result = json.loads(row['result_json'])
        if result['state'] == 'in_progress':
            raise DomainError('A tentativa anterior está em andamento ou tem resultado incerto; não será repetida automaticamente.',409,'reception_uncertain')
        return result | {'duplicate':True}

    def _interpret(self, provider, environment, cursor, reply, expected_mode):
        fallback=3600 if provider=='nfe_distribution' else 0
        metadata = {'http_status':reply.status,'expected_authorization_mode':expected_mode,
                    'authorization_verified':False,'cursor_advanced':False}
        if reply.status in {429,503,502,504}:
            return metadata|{'state':'remote_unavailable'},cursor,max(fallback,reply.retry_after)
        if 300 <= reply.status < 400:
            return metadata|{'state':'redirect_refused'},cursor,fallback
        if provider == 'nfe_distribution' and reply.status == 200:
            response = read_nfe_distribution(reply.body)
            if response['environment'] != ('1' if environment == 'production' else '2'):
                return metadata|{'state':'environment_mismatch'},cursor,fallback
            proposed = response['reported_last_nsu']
            if response['status_code'] in {'137','138'}:
                if proposed < cursor or any(entry['nsu'] <= cursor for entry in response['entries']):
                    return metadata|{'state':'nsu_mismatch'},cursor,fallback
                return metadata|{'state':'received','status_code':response['status_code'],
                                 'entries':[{k:v for k,v in entry.items() if k!='xml'} for entry in response['entries']],
                                 'review_pending':True,'has_more':proposed<response['reported_max_nsu'],
                                 'reported_max_nsu':response['reported_max_nsu']},proposed,max(response['cooldown_seconds'],reply.retry_after)
            if response['status_code']=='656' and proposed is not None and proposed>cursor:
                return metadata|{'state':'cursor_synchronized','status_code':'656','has_more':False,
                                 'documents_downloaded':False,'missing_documents_review':True,
                                 'synchronized_from':cursor,'synchronized_to':proposed},proposed,3600
            return metadata|{'state':'rejected','status_code':response['status_code']},cursor,max(3600,response['cooldown_seconds'])
        if provider == 'nfse_adn':
            try:
                payload = load_adn_json(reply.body)
                absence=read_adn_absence(payload,reply.status,environment)
                if absence is not None:
                    return metadata|absence,cursor,max(ADN_EMPTY_COOLDOWN_SECONDS,reply.retry_after)
                # Rejection defaults are never proof of authorization, even if
                # accompanied by an inconsistent success status/HTTP 200.
                if isinstance(payload,dict) and payload.get('Erros'):
                    rejection = adn_rejection(payload,cursor)
                    return metadata|{'state':rejection['state'],'error_codes':rejection['error_codes']},cursor,fallback
                if reply.status != 200:
                    raise ImportProblem('ADN_RESPONSE_UNSUPPORTED','Retorno ADN pendente.')
                response = read_adn_distribution(payload,cursor,environment,expected_mode)
                proposed = response.pop('reported_last_nsu')
                return metadata|response|{'state':'received'},proposed,max(0,reply.retry_after)
            except (ValueError,UnicodeError,RecursionError) as error:
                return metadata|{'state':'received_unparsed' if reply.status == 200 else 'unparsed_rejection',
                                 'code':getattr(error,'code','ADN_RESPONSE_INVALID'),'review_pending':True},cursor,fallback
        return metadata|{'state':'rejected'},cursor,fallback

    def _finish(self,cid,uid,actor,key,identity,state_key,lease,target,competence,result,proposed,cooldown,raw):
        with self.db.transaction() as conn:
            company = self._access(conn,uid,cid,'import')
            if company['tax_id'] != target:
                raise DomainError('Empresa alterada durante a consulta; cursor preservado.',409,'stale_company')
            state = self._state(conn,cid,state_key)
            if state['lease_id'] != lease or state['lease_until'] <= self.clock():
                raise DomainError('A reserva expirou ou mudou. Resultado não aplicado; cursor preservado.',409,'reception_lease_lost')
            from .operational_settings import ensure_import_allowed
            entries = result.get('entries',[])
            packet_bytes = sum(len(entry.get('xml',b'')) for entry in entries)
            ensure_import_allowed(conn,cid,len(raw or b'')+packet_bytes)
            provider,environment,_ = state_key.split(':')
            if provider == 'nfe_distribution':
                result['coordination'] = {
                    'scope':'shared_database_only','external_systems_coordinated':False,
                    'warning_code':'NFE_EXTERNAL_NSU_COORDINATION',
                    'warning':'Outros sistemas que consultem este CNPJ precisam compartilhar a sequência e os intervalos distNSU. A reserva do Escritura coordena somente esta base; combine a coleta ou importe os XMLs já obtidos.'}

            result.update(provider=provider,environment=environment,period=competence,receipt_key=key,target_tax_id=target,
                          cursor_before=state['cursor'],cursor_after=proposed,cursor_advanced=proposed!=state['cursor'])
            if raw:
                extension = '.xml' if provider == 'nfe_distribution' else '.json'
                file_id=store_file(self.db,conn,cid,int(competence[:4]),'originals','recepcao-'+key+extension,raw,actor)
                result.update(file_id=file_id,sha256=digest(raw),bytes=len(raw))
            elif proposed != state['cursor']:
                raise DomainError('Cursor só pode avançar após guardar o retorno íntegro.',409,'reception_original_required')
            # Packet originals and envelope share the cursor transaction. A
            # failed packet write rolls back ALL canonical files and the cursor.
            for entry in entries:
                xml = entry.pop('xml',None)
                if xml is not None:
                    entry['file_id'] = store_file(self.db,conn,cid,int(competence[:4]),'originals',
                        'adn-'+key+'-'+entry['nsu']+'.xml',xml,actor)
                if provider == 'nfse_adn' and proposed != state['cursor'] and not entry.get('file_id'):
                    raise DomainError('XML íntegro obrigatório antes de avançar NSU ADN.',409,'reception_original_required')
            state.update(cursor=proposed,lease_id=None,lease_until=0,next_allowed_at=self.clock()+max(0,cooldown),last_receipt=key)
            self._save_state(conn,cid,state_key,state)
            conn.execute('UPDATE operations SET result_json=? WHERE company_id=? AND scope=? AND key=? AND request_hash=?',
                         (pack(result),cid,RUN_SCOPE,key,identity))
            audit(conn,cid,actor,'query-finish','fiscal-reception',key,{k:v for k,v in result.items() if k!='entries'})
            return result

    def receipt(self,cid,key,uid,export=False):
        key=self._key(key)
        with self.db.read(snapshot=True) as conn:
            self._access(conn,uid,cid,'export' if export else 'read')
            row=self._operation(conn,cid,RUN_SCOPE,key)
            if not row:
                raise DomainError('Recepção não localizada nesta empresa.',404,'not_found')
            result=json.loads(row['result_json'])
            if export:
                if not result.get('file_id'):
                    raise DomainError('Tentativa sem original recebido disponível.',409,'reception_original_unavailable')
                file=read_file(conn,cid,result['file_id'])
                return result,file['content']
            return result

    def document(self,cid,key,number,uid):
        from .reception import adn_nsu
        try:
            number=adn_nsu(number)
        except ValueError:
            raise DomainError('NSU de documento inválido.',400,'ADN_NSU') from None
        with self.db.read(snapshot=True) as conn:
            self._access(conn,uid,cid,'export')
            row=self._operation(conn,cid,RUN_SCOPE,self._key(key))
            if not row:
                raise DomainError('Recepção não localizada nesta empresa.',404,'not_found')
            result=json.loads(row['result_json'])
            entry=next((item for item in result.get('entries',[]) if item.get('nsu')==number),None)
            if not entry:
                raise DomainError('XML não disponível neste recibo.',404,'not_found')
            if result.get('provider')=='nfe_distribution' and result.get('file_id'):
                envelope=read_file(conn,cid,result['file_id'])
                if envelope['sha256']!=result['sha256']:
                    raise DomainError('Integridade do retorno comprometida.',409,'file_integrity')
                packets=read_nfe_distribution(envelope['content'])
                packet=next((p for p in packets['entries'] if p['nsu']==number),None)
                if not packet or packet['sha256']!=entry['sha256']:
                    raise DomainError('Integridade do XML comprometida.',409,'file_integrity')
                return entry,packet['xml']
            if result.get('provider')!='nfse_adn' or not entry.get('file_id'):
                raise DomainError('XML não disponível neste recibo.',404,'not_found')
            file=read_file(conn,cid,entry['file_id'])
            if file['sha256']!=entry['sha256'] or len(file['content'])!=entry['bytes']:
                raise DomainError('Integridade do XML do recibo comprometida.',409,'file_integrity')
            return entry,file['content']

    def preview(self,cid,key,payload,actor,uid):
        result,raw=self._preview_source(cid,key,uid)
        if result['provider'] != 'nfe_distribution':
            raise DomainError('Recepção ADN preservada; consulte os XMLs disponíveis no recibo. Leitor de escrituração nacional ainda pendente.',409,'nfse_bookkeeping_reader_pending')
        if not isinstance(payload,dict) or set(payload)-{'period','options'}:
            raise DomainError('Informe somente competência e opções de revisão.')
        return self.core.preview_import(cid,{'filename':'recepcao-'+key+'.xml','period':payload.get('period'),
                    'options':payload.get('options',{}),'content_base64':base64.b64encode(raw).decode()},actor)

    def _preview_source(self,cid,key,uid):
        with self.db.read(snapshot=True) as conn:
            self._access(conn,uid,cid,'import')
            row=self._operation(conn,cid,RUN_SCOPE,self._key(key))
            if not row:
                raise DomainError('Recepção não localizada nesta empresa.',404,'not_found')
            result=json.loads(row['result_json'])
            if not result.get('file_id'):
                raise DomainError('Recepção sem original disponível.',409,'reception_original_unavailable')
            return result,read_file(conn,cid,result['file_id'])['content']
