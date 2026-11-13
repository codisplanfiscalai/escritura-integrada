"""Intercâmbio contábil aditivo: prévia imutável, origem e confirmação atômica."""
import base64
import binascii
from functools import lru_cache
import json
from pathlib import Path
import re

from .core import DomainError, audit, boolean, company_row, digest, now, pack, select_one, text
from .permissions import effect


@lru_cache(maxsize=1)
def default_plan():
    return json.loads((Path(__file__).parent / 'data/account-plan-default.json').read_text(encoding='utf-8'))


FIELDS = ('access_code', 'classifier', 'name', 'nature', 'analytical', 'requires_cost_center', 'active', 'report_group', 'prosoft_code')


def account_values(account):
    if not isinstance(account, dict): raise DomainError('Conta inválida no plano.')
    values = {k: text(account.get(k), k, True, 200) for k in ('access_code', 'classifier', 'name', 'nature')}
    if values['nature'] not in {'debit', 'credit'}: raise DomainError('Natureza da conta deve ser debit ou credit.')
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)*', values['classifier']): raise DomainError('Classificador deve conter dígitos separados por pontos.')
    values['report_group'] = text(account.get('report_group', ''), 'Grupo do demonstrativo', False, 30)
    if values['report_group'] not in {'', 'asset', 'liability', 'equity', 'revenue', 'expense'}: raise DomainError('Grupo do demonstrativo inválido.')
    values['prosoft_code'] = text(account.get('prosoft_code', ''), 'Acesso Prosoft', False, 5)
    if values['prosoft_code'] and not re.fullmatch(r'[0-9]{1,5}', values['prosoft_code']): raise DomainError('Acesso Prosoft deve conter até cinco dígitos.')
    for flag, default in [('analytical', True), ('requires_cost_center', False), ('active', True)]:
        values[flag] = boolean(account.get(flag), default)
    prosoft = account.get('prosoft', {})
    if not isinstance(prosoft, dict): raise DomainError('Parâmetros Prosoft da conta devem ser um objeto.')
    return {k:v for k,v in account.items() if k not in {'id','version'}} | values | {'prosoft': prosoft}


class AccountPlansMixin:
    def _plan_state(self, conn, cid):
        company_row(conn, cid)
        accounts = []
        for row in conn.execute("SELECT a.*,COALESCE(m.prosoft_json,g.prosoft_json,'{}') AS prosoft_json,COALESCE(m.extras_json,g.extras_json,'{}') AS extras_json FROM effective_accounts a LEFT JOIN account_plan_metadata m ON m.account_id=a.id AND m.company_id=a.company_id LEFT JOIN global_account_entries g ON g.id=a.shared_entry_id WHERE a.company_id=? ORDER BY a.classifier,a.access_code", (cid,)):
            r = dict(row)
            accounts.append(json.loads(r['extras_json'] or '{}') | {k: bool(r[k]) if k in {'analytical','requires_cost_center','active'} else r[k] for k in FIELDS} | {'id':r['id'], 'version':r['version'], 'prosoft':json.loads(r['prosoft_json'] or '{}')})
        properties,_ = self._plan_properties(conn,cid)
        return accounts,properties

    def _plan_properties(self,conn,cid):
        saved=conn.execute('SELECT properties_json,extras_json FROM account_plan_properties WHERE company_id=?',(cid,)).fetchone()
        if saved:return json.loads(saved['properties_json']),json.loads(saved['extras_json'])
        shared=conn.execute('SELECT g.plan_json FROM company_account_plan_bindings b JOIN global_account_plans g ON g.id=b.global_plan_id WHERE b.company_id=?',(cid,)).fetchone()
        if not shared:return None,None
        plan=json.loads(shared['plan_json'])
        return plan['properties'],{k:v for k,v in plan.items() if k not in {'schema','properties','accounts','format','encoding'}}

    def _plan_preview(self, conn, cid, plan, template=False, identity_by_access=False):
        current, properties = self._plan_state(conn, cid)
        by_code = {r['access_code']:r for r in current}; by_classifier = {r['classifier']:r for r in current}
        created, preserved, conflicts = [], 0, []
        seen_codes, seen_classifiers = set(), set()
        for raw in plan['accounts']:
            r = account_values(raw)
            if r['access_code'] in seen_codes or (not identity_by_access and r['classifier'] in seen_classifiers):
                conflicts.append({'access_code':r['access_code'], 'classifier':r['classifier'], 'reason':'Acesso repetido ou classificador repetido no modo tradicional. Para subcontas distintas, revise a identidade por acesso ou publique uma versão global; todas as linhas permanecem na origem.'})
                continue
            seen_codes.add(r['access_code']); seen_classifiers.add(r['classifier'])
            matches = [x for x in (by_code.get(r['access_code']), None if identity_by_access else by_classifier.get(r['classifier'])) if x]
            if not matches:
                created.append(r); continue
            if template:
                preserved += 1; continue
            if len({x['id'] for x in matches}) == 1 and {k:v for k,v in matches[0].items() if k not in {'id','version'}} == r:
                preserved += 1; continue
            conflicts.append({'access_code':r['access_code'], 'classifier':r['classifier'], 'reason':'Acesso ou classificador já cadastrado com dados diferentes. Nenhuma conta será substituída.'})
        if properties is not None and properties != plan['properties'] and created:
            conflicts.append({'access_code':'', 'reason':'Propriedades do plano diferem das já importadas nesta empresa. Revise a máscara e os grupos antes de combinar planos.'})
        _,extras=self._plan_properties(conn,cid)
        incoming_extras={k:v for k,v in plan.items() if k not in {'schema','properties','accounts','format','encoding'}}
        if not template and extras is not None and extras!=incoming_extras:
            conflicts.append({'access_code':'','reason':'Metadados gerais da origem diferem do plano atual. Guarde a carga completa como referência; os metadados existentes não serão substituídos.'})
        state_hash = digest({'accounts':current, 'properties':properties, 'extras':extras})
        return {'created':len(created), 'preserved':preserved, 'conflicts':conflicts, 'can_confirm':not conflicts,
                'state_hash':state_hash, 'to_create':created}

    def preview_account_plan(self, cid, payload, actor):
        from .operational_settings import ensure_import_allowed
        with self.db.read() as conn: ensure_import_allowed(conn, cid)
        from .account_plan_codec import decode_plan, PlanCodecError
        format = text(payload.get('format', 'native'), 'Formato', True, 30)
        options = payload.get('options', {})
        if not isinstance(options, dict): raise DomainError('Opções do plano devem ser um objeto.')
        if options.get('identity_mode', 'traditional') not in {'traditional','access'}: raise DomainError('Modo de identidade do plano inválido.')
        if format == 'default':
            raw = pack(default_plan()).encode('utf-8'); filename = 'plano-padrao-escritura.json'
            try: plan = decode_plan(raw, 'native', {})
            except PlanCodecError as exc: raise DomainError(str(exc))
        else:
            filename = text(payload.get('filename'), 'Nome do arquivo', True, 200)
            content = payload.get('content_base64')
            if not isinstance(content, str) or len(content) > 20_000_000: raise DomainError('Arquivo de plano inválido ou maior que 15 MB.')
            try: raw = base64.b64decode(content, validate=True)
            except (ValueError, binascii.Error): raise DomainError('Conteúdo base64 inválido.')
            if not raw or len(raw)>15_000_000: raise DomainError('Informe um arquivo de até 15 MB.')
            try: plan = decode_plan(raw, format, options)
            except PlanCodecError as exc: raise DomainError(str(exc))
        if not 1 <= len(plan['accounts']) <= 50000: raise DomainError('O plano deve conter de 1 a 50.000 contas.')
        with self.db.transaction() as conn:
            effect(conn, cid, 'accounting.accounts', 'read')
            ensure_import_allowed(conn, cid, len(raw))
            result = self._plan_preview(conn, cid, plan, format == 'default', options.get('identity_mode') == 'access')
            fingerprint = digest({'raw':digest(raw), 'format':format, 'options':options, 'state':result['state_hash'], 'plan':plan})
            batch = conn.execute('INSERT INTO account_plan_batches(company_id,filename,format,sha256,original,options_json,plan_json,preview_hash,state_hash,status,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (cid,filename,format,digest(raw),raw,pack(options),pack(plan),fingerprint,result['state_hash'],'preview',now(),actor)).lastrowid
            audit(conn,cid,actor,'preview','account_plan',batch,{'sha256':digest(raw),'format':format,'records':len(plan['accounts'])})
            return {k:v for k,v in result.items() if k not in {'to_create','state_hash','conflicts'}} | {'conflicts':result['conflicts'][:100], 'conflict_count':len(result['conflicts']), 'id':batch,'preview_hash':fingerprint,'filename':filename,'record_count':len(plan['accounts']),
                'accounts':plan['accounts'][:100], 'properties':plan['properties'], 'warnings':plan.get('warnings',[])[:100], 'warning_count':len(plan.get('warnings',[])), 'encoding':plan.get('encoding'), 'sha256':digest(raw)}

    def confirm_account_plan(self, cid, item_id, payload, actor):
        reason = text(payload.get('reason'), 'Motivo da importação', True, 1000)
        if payload.get('properties_reviewed') is not True: raise DomainError('Confirme a máscara, grupos e propriedades do plano.')
        with self.db.transaction() as conn:
            batch = select_one(conn,'account_plan_batches',cid,item_id)
            from .operational_settings import ensure_import_allowed
            ensure_import_allowed(conn, cid, len(batch['original']))
            if payload.get('preview_hash') != batch['preview_hash']: raise DomainError('A prévia informada não corresponde ao lote.',409,'stale_preview')
            if batch['status'] in {'confirmed','reference'}: return json.loads(batch['confirmation_json']) | {'duplicate':True}
            mode=payload.get('activation_mode','activate')
            if mode not in {'activate','reference'}:raise DomainError('Modo de importação inválido.')
            if mode=='reference':
                plan=json.loads(batch['plan_json'])
                confirmed={'id':item_id,'created':0,'preserved':0,'record_count':len(plan['accounts']),'reference_only':True}
                conn.execute("UPDATE account_plan_batches SET status='reference',confirmation_json=? WHERE id=? AND company_id=?",(pack(confirmed),item_id,cid))
                audit(conn,cid,actor,'import-reference','account_plan',item_id,confirmed|{'reason':reason,'sha256':batch['sha256']})
                return confirmed
            effect(conn,cid,'accounting.accounts','create')
            from .global_account_plans import assert_own_plan
            assert_own_plan(conn,cid)
            plan = json.loads(batch['plan_json']); result = self._plan_preview(conn,cid,plan,batch['format']=='default',json.loads(batch['options_json']).get('identity_mode')=='access')
            if result['state_hash']!=batch['state_hash']: raise DomainError('O plano da empresa mudou. Gere uma nova prévia.',409,'stale_preview')
            if result['conflicts']: raise DomainError('Há conflitos de acesso, classificação ou propriedades. Nenhuma conta foi gravada.',409,'account_plan_conflict')
            for row in result['to_create']:
                values = [row[k] for k in FIELDS]
                aid = conn.execute(f"INSERT INTO accounts(company_id,{','.join(FIELDS)}) VALUES({','.join('?' for _ in range(len(FIELDS)+1))})",(cid,*values)).lastrowid
                extras={k:v for k,v in row.items() if k not in {*FIELDS,'prosoft'}}
                conn.execute('INSERT INTO account_plan_metadata(company_id,account_id,prosoft_json,extras_json,batch_id) VALUES(?,?,?,?,?)',(cid,aid,pack(row['prosoft']),pack(extras),item_id))
            extras={k:v for k,v in plan.items() if k not in {'schema','properties','accounts','format','encoding'}}
            conn.execute('INSERT INTO account_plan_properties(company_id,properties_json,extras_json) VALUES(?,?,?) ON CONFLICT(company_id) DO NOTHING',(cid,pack(plan['properties']),pack(extras)))
            confirmed = {'id':item_id,'created':result['created'],'preserved':result['preserved'],'record_count':len(plan['accounts'])}
            conn.execute("UPDATE account_plan_batches SET status='confirmed',confirmation_json=? WHERE id=? AND company_id=?",(pack(confirmed),item_id,cid))
            audit(conn,cid,actor,'import','account_plan',item_id,confirmed | {'reason':reason,'sha256':batch['sha256'],'properties':plan['properties']})
            return confirmed

    def account_plan_batches(self,cid):
        with self.db.read() as conn:
            company_row(conn,cid)
            return [dict(r) for r in conn.execute('SELECT id,filename,format,sha256,status,created_at,created_by FROM account_plan_batches WHERE company_id=? ORDER BY id DESC LIMIT 100',(cid,))]

    def export_account_plan(self,cid,payload,actor,confirm=False):
        from .account_plan_codec import encode_plan, PlanCodecError
        format = text(payload.get('format','native'),'Formato',True,30)
        if format not in {'native','prosoft-import','prosoft-export'}: raise DomainError('Formato de exportação inválido.')
        code = text(payload.get('plan_code','0000'),'Código do plano',True,4)
        if not re.fullmatch(r'[0-9]{4}',code): raise DomainError('Código do plano deve conter quatro dígitos.')
        with self.db.transaction() as conn:
            effect(conn,cid,'accounting.accounts','read')
            accounts, saved = self._plan_state(conn,cid)
            if not 1<=len(accounts)<=50000:raise DomainError('O plano deve conter de 1 a 50.000 contas para exportação.')
            properties = payload.get('properties',saved or default_plan()['properties'])
            if not isinstance(properties,dict): raise DomainError('Propriedades do plano devem ser um objeto.')
            _,extras=self._plan_properties(conn,cid)
            plan = (extras or {}) | {'schema':'escritura-account-plan/v1','properties':properties,'accounts':[{k:v for k,v in r.items() if k not in {'id','version'}} for r in accounts]}
            try: raw, manifest = encode_plan(plan,format,{'allow_ascii':payload.get('allow_ascii') is True})
            except PlanCodecError as exc: raise DomainError(str(exc))
            changes = manifest.get('text_changes',manifest.get('changes',[]))
            manifest['text_changes']=changes; manifest['records']=manifest.get('records',len(raw.splitlines()))
            manifest['needs_ascii_review']=bool(changes) and payload.get('allow_ascii') is not True
            manifest['homologated_in_destination']=False
            fingerprint = digest({'sha256':digest(raw),'accounts':accounts,'properties':properties,'format':format,'plan_code':code})
            filename = f'plano-escritura-{cid}.json' if format=='native' else (f'CTBPLANO{code}.TXT' if format=='prosoft-import' else f'PLANO-{code}.TXT')
            result = {'preview_hash':fingerprint,'filename':filename,'sha256':digest(raw),'manifest':manifest,'sample':raw.decode('utf-8' if format=='native' else 'ascii').splitlines()[:5]}
            if not confirm:return result
            if payload.get('preview_hash')!=fingerprint: raise DomainError('O plano ou as opções mudaram. Gere nova prévia.',409,'stale_preview')
            if manifest['needs_ascii_review']: raise DomainError('Revise e aceite as alterações para ASCII antes de exportar.')
            if payload.get('destination_reviewed') is not True: raise DomainError('Confirme o plano, a máscara e a empresa no destino.')
            audit(conn,cid,actor,'export','account_plan',code,{'format':format,'sha256':digest(raw),'records':len(accounts),'text_changes':len(changes)})
            return result | {'content_base64':base64.b64encode(raw).decode('ascii')}
