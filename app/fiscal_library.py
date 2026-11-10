"""Shared informational references and explicitly imported company tax drafts."""
from decimal import Decimal
import json
import re
from .core import DomainError, REGIMES, audit, boolean, check_version, company_row, digest, integer, iso_date, now, pack, text
from .permissions import effect
from .db import request_context

TAXES = {'icms', 'ipi', 'iss', 'pis', 'cofins', 'ibs', 'cbs'}
SEGMENTS = {'commerce', 'industry', 'services', 'other'}
RULE_FIELDS = ('name','tax','direction','cfop','ncm','state','municipality','source')


def _admin(conn):
    ctx = request_context.get()
    if ctx and conn.execute('SELECT role FROM users WHERE id=?', (ctx['user_id'],)).fetchone()['role'] != 'admin':
        raise DomainError('Somente administrador altera a biblioteca global.',403,'forbidden')


def _rate(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{1,3}(?:\.\d{1,6})?',value) or Decimal(value)>100:
        raise DomainError('Alíquota informativa deve estar entre 0 e 100, com até seis casas decimais.')
    return format(Decimal(value),'f')


def _validity(data,required=False):
    start=iso_date(data.get('valid_from')) if required or data.get('valid_from') else ''
    end=iso_date(data['valid_to']) if data.get('valid_to') else ''
    if end and (not start or end<start): raise DomainError('Revise o intervalo de vigência.')
    return {'valid_from':start,'valid_to':end}


def _row(row):
    return {'id':row['id'],'version':row['version'],'code':row['code'],'active':bool(row['active']),
            'updated_at':row['updated_at']} | json.loads(row['data_json'])


def starter_patterns():
    """Structural models only: no rates, credits or legal commencement inferred."""
    return [{'code':regime+'-'+segment,'name':'Estrutura · '+regime.replace('_',' ')+' · '+segment,
             'regime':regime,'segment':segment,'valid_from':'','valid_to':'',
             'description':'Estrutura inicial sem alíquotas. Informe fundamento, vigência e tratamento de cada tributo.',
             'source':'Estrutura de trabalho do escritório; sem validação tributária',
             'rules':[{'name':tax.upper()+' · revisar incidência','tax':tax,'rate':None,'direction':'both',
                       'cfop':'','ncm':'','state':'','municipality':'','source':''} for tax in taxes]}
            for regime in sorted(REGIMES) for segment,taxes in [('commerce',['icms','pis','cofins']),
                ('industry',['icms','ipi','pis','cofins']),('services',['iss','pis','cofins'])]]


class FiscalLibraryMixin:
    def global_fiscal_catalogs(self,cid,kind='cfop',search='',page=1):
        if not isinstance(kind,str) or kind not in {'cfop','service'}: raise DomainError('Tabela global inválida.')
        page=integer(page,'Página')
        if page<1: raise DomainError('Página inválida.')
        query=text(search,'Pesquisa',False,200).casefold().strip()
        with self.db.read() as conn:
            company_row(conn,cid); effect(conn,cid,'fiscal.masters','read')
            records=[_row(r)|{'kind':kind} for r in conn.execute('SELECT * FROM global_fiscal_catalogs WHERE kind=? ORDER BY code',(kind,))]
            records=[r for r in records if not query or query in (r['code']+' '+r['description']).casefold()]
            return {'rows':records[(page-1)*50:page*50],'total':len(records),'page':page,'per_page':50,'informational_only':True}

    def save_global_fiscal_catalog(self,cid,payload,actor,item_id=None):
        with self.db.transaction() as conn:
            company_row(conn,cid); _admin(conn)
            old=conn.execute('SELECT * FROM global_fiscal_catalogs WHERE id=?',(item_id,)).fetchone() if item_id else None
            if item_id and not old: raise DomainError('Registro global não localizado.',404)
            previous=_row(old) if old else {}
            if old: check_version(old,payload)
            kind=old['kind'] if old else payload.get('kind')
            if not isinstance(kind,str) or kind not in {'cfop','service'}: raise DomainError('Tabela global inválida.')
            code=text(payload.get('code',previous.get('code')),'Código',True,50)
            if kind=='cfop':
                if old and code!=old['code']: raise DomainError('Código da referência oficial é preservado.')
                from .cfop import reference_index
                if code not in reference_index(): raise DomainError('CFOP fora da referência oficial; preserve a origem legada separadamente.')
            namespace=old['namespace'] if old else ''
            values=json.loads(old['data_json']) if old else {'source_rates_declared':[],'parameters_declared':{}}
            for key in ('description','source'):
                values[key]=text(payload.get(key,values.get(key)),key,True,1500)
            if kind=='service':
                system=text(payload.get('service_system',values.get('service_system')),'Tabela do serviço',True,100)
                jurisdiction=text(payload.get('jurisdiction',values.get('jurisdiction')),'Jurisdição',True,30)
                if system not in {'lc116','national_nfse','municipal'}: raise DomainError('Tabela do serviço inválida.')
                if (system=='municipal' and not re.fullmatch(r'\d{7}',jurisdiction)) or (system!='municipal' and jurisdiction!='BR'):
                    raise DomainError('Use código IBGE municipal ou BR para tabelas nacionais.')
                namespace=system+':'+jurisdiction
                values.update(service_system=system,jurisdiction=jurisdiction)
            values['direction']=payload.get('direction',values.get('direction','both'))
            if not isinstance(values['direction'],str) or values['direction'] not in {'incoming','outgoing','both'}: raise DomainError('Sentido inválido.')
            rates=payload.get('rates_declared',values.get('rates_declared',[]))
            if not isinstance(rates,list) or len(rates)>200: raise DomainError('Lista de alíquotas inválida.')
            values['rates_declared']=list(dict.fromkeys(_rate(r) for r in rates))
            values.update(_validity({k:payload.get(k,values.get(k,'')) for k in ('valid_from','valid_to')}))
            values['review_status']='informational'; values['informational_only']=True
            reason=text(payload.get('reason'),'Motivo da alteração global',True,1000)
            active=boolean(payload.get('active'),bool(previous.get('active',True)))
            if old:
                conn.execute('UPDATE global_fiscal_catalogs SET code=?,namespace=?,data_json=?,active=?,version=version+1,updated_at=? WHERE id=?',(code,namespace,pack(values),active,now(),item_id))
            else:
                item_id=conn.execute('INSERT INTO global_fiscal_catalogs(kind,code,namespace,data_json,active,updated_at) VALUES(?,?,?,?,?,?)',(kind,code,namespace,pack(values),active,now())).lastrowid
            saved=conn.execute('SELECT * FROM global_fiscal_catalogs WHERE id=?',(item_id,)).fetchone()
            self._save_fiscal_library_version(conn,'catalog',saved,actor)
            audit(conn,None,actor,'update' if old else 'create','global_fiscal_catalog',item_id,{'reason':reason,'before':previous,'after':values,'code':code})
            return _row(conn.execute('SELECT * FROM global_fiscal_catalogs WHERE id=?',(item_id,)).fetchone())|{'kind':kind}

    def fiscal_pattern_library(self,cid):
        with self.db.read() as conn:
            company_row(conn,cid); effect(conn,cid,'fiscal.parameters','read')
            return {'rows':[_row(r) for r in conn.execute('SELECT * FROM fiscal_patterns ORDER BY code')],
                    'starters':starter_patterns(),'segments':sorted(SEGMENTS),'review_required':True,
                    'warning':'Padrões são propostas. Importar cria regras inativas e não calcula ou autoriza créditos.'}

    def save_fiscal_pattern(self,cid,payload,actor,item_id=None):
        with self.db.transaction() as conn:
            company_row(conn,cid); _admin(conn)
            old=conn.execute('SELECT * FROM fiscal_patterns WHERE id=?',(item_id,)).fetchone() if item_id else None
            if item_id and not old: raise DomainError('Padrão não localizado.',404)
            if old: check_version(old,payload)
            code=text(payload.get('code'),'Código do padrão',True,100)
            regime=payload.get('regime'); segment=payload.get('segment')
            if not isinstance(regime,str) or regime not in REGIMES or not isinstance(segment,str) or segment not in SEGMENTS: raise DomainError('Selecione regime e segmento do padrão.')
            data={key:text(payload.get(key),key,key in {'name','source'},1000) for key in ('name','description','source')}
            data.update(regime=regime,segment=segment,**_validity(payload))
            data['activity']=text(payload.get('activity'),'Atividade declarada',False,200)
            data['cnae_prefix']=text(payload.get('cnae_prefix'),'Filtro CNAE',False,7)
            if data['cnae_prefix'] and not re.fullmatch(r'\d{2,7}',data['cnae_prefix']):
                raise DomainError('Filtro CNAE deve conter de dois a sete dígitos.')
            if old:
                lineage=json.loads(old['data_json']).get('derived_from')
                if lineage: data['derived_from']=lineage
                if payload.get('base_pattern_id') is not None or payload.get('base_version') is not None:
                    raise DomainError('A linhagem de um padrão publicado é preservada; derive outro padrão.')
            elif payload.get('base_pattern_id') is not None or payload.get('base_version') is not None:
                parent_id=integer(payload.get('base_pattern_id'),'Padrão de origem')
                parent_version=integer(payload.get('base_version'),'Versão de origem')
                parent=conn.execute('SELECT data_json FROM fiscal_library_versions WHERE entity_type=? AND entity_id=? AND version=?',('pattern',parent_id,parent_version)).fetchone()
                if not parent: raise DomainError('Versão do padrão de origem não localizada.',404)
                snapshot=_row(json.loads(parent['data_json']))
                data['derived_from']={'id':parent_id,'version':parent_version,'code':snapshot['code'],'fingerprint':digest(snapshot)}

            rules=payload.get('rules')
            if not isinstance(rules,list) or not 1<=len(rules)<=200: raise DomainError('Informe de 1 a 200 regras do padrão.')
            data['rules']=[]
            for original in rules:
                if not isinstance(original,dict): raise DomainError('Regra do padrão inválida.')
                rule={k:text(original.get(k),k,k in {'name','tax'},1000) for k in RULE_FIELDS}
                rule['tax']=rule['tax'].lower()
                if rule['tax'] not in TAXES: raise DomainError('Tributo do padrão inválido.')
                rule['direction']=rule['direction'] or 'both'
                if rule['direction'] not in {'incoming','outgoing','both'}: raise DomainError('Sentido da regra inválido.')
                for key,size in [('cfop',4),('ncm',8),('municipality',7)]:
                    if rule[key] and not re.fullmatch(rf'\d{{{size}}}',rule[key]): raise DomainError(f'{key}: código inválido.')
                from .cadastros import UFS
                if rule['state'] and rule['state'] not in UFS: raise DomainError('UF da regra inválida.')
                rule['rate']=_rate(original['rate']) if original.get('rate') not in (None,'') else None
                data['rules'].append(rule)
            active=boolean(payload.get('active'),True)
            reason=text(payload.get('reason'),'Motivo da publicação global',True,1000)
            if old:
                conn.execute('UPDATE fiscal_patterns SET code=?,data_json=?,active=?,version=version+1,updated_at=? WHERE id=?',(code,pack(data),active,now(),item_id))
            else:
                item_id=conn.execute('INSERT INTO fiscal_patterns(code,data_json,active,updated_at) VALUES(?,?,?,?)',(code,pack(data),active,now())).lastrowid
            saved=conn.execute('SELECT * FROM fiscal_patterns WHERE id=?',(item_id,)).fetchone()
            self._save_fiscal_library_version(conn,'pattern',saved,actor)
            audit(conn,None,actor,'update' if old else 'create','fiscal_pattern',item_id,{'reason':reason,'before':_row(old) if old else None,'after':data})
            return _row(conn.execute('SELECT * FROM fiscal_patterns WHERE id=?',(item_id,)).fetchone())

    def apply_fiscal_pattern(self,cid,item_id,payload,actor):
        reason=text(payload.get('reason'),'Motivo da importação',True,1000)
        responsible=text(payload.get('responsible'),'Responsável pela revisão',True,200)
        validity=_validity(payload,required=True)
        with self.db.transaction() as conn:
            effect(conn,cid,'fiscal.parameters','create')
            preview=self._fiscal_pattern_preview(conn,cid,item_id,payload)
            pattern=preview['pattern']
            row={'version':pattern['version']}
            segment=pattern['segment']
            fingerprint=digest({'id':item_id,'version':row['version'],'validity':validity,'segment':segment})
            previous=conn.execute('SELECT * FROM company_fiscal_pattern_imports WHERE company_id=? AND fingerprint=?',(cid,fingerprint)).fetchone()
            if payload.get('preview_hash')!=preview['preview_hash']:
                raise DomainError('A prévia mudou. Revise o padrão e a empresa antes de importar.',409,'stale_fiscal_pattern')
            if previous: return {'id':previous['id'],'duplicate':True,'rule_ids':json.loads(previous['rule_ids_json']),'review_required':True}
            ids=[]
            for original in pattern['rules']:
                copied=original|validity|{'regime':pattern['regime'],'status':'draft','active':False,'responsible':responsible,'source':original['source'] or pattern['source']}
                ids.append(self._save_rule(conn,cid,copied,actor)['id'])
            saved_id=conn.execute('INSERT INTO company_fiscal_pattern_imports(company_id,pattern_id,pattern_version,fingerprint,snapshot_json,rule_ids_json,created_at,created_by) VALUES(?,?,?,?,?,?,?,?)',
                (cid,item_id,row['version'],fingerprint,pack(pattern|{'segment_confirmed':segment,'activity_confirmed':preview['activity_confirmed'],'company_cnae':preview['company_cnae'],'reason':reason,'responsible':responsible,'company_validity':validity}),pack(ids),now(),actor)).lastrowid
            audit(conn,cid,actor,'apply','fiscal_pattern',item_id,{'import_id':saved_id,'version':row['version'],'rule_ids':ids,'segment':segment,'activity_confirmed':preview['activity_confirmed'],'company_cnae':preview['company_cnae'],'reason':reason,'status':'draft','active':False})
            return {'id':saved_id,'duplicate':False,'rule_ids':ids,'review_required':True,'status':'draft','active':False}

    def company_fiscal_pattern_imports(self,cid):
        with self.db.read() as conn:
            company=company_row(conn,cid); effect(conn,cid,'fiscal.parameters','read')
            records=[]
            for row in conn.execute('SELECT * FROM company_fiscal_pattern_imports WHERE company_id=? ORDER BY id DESC',(cid,)):
                snapshot=json.loads(row['snapshot_json']); warnings=[]
                if snapshot['regime']!=company['regime']:
                    warnings.append({'code':'regime_changed','reason':'Regime atual difere do padrão importado. Revise as cópias antes da pré-apuração.'})
                prefix=snapshot.get('cnae_prefix','')
                if prefix and not company['cnae'].startswith(prefix):
                    warnings.append({'code':'cnae_mismatch','reason':'CNAE principal atual não corresponde à condição da origem. As cópias precisam de revisão; este aviso não as desativa nem altera cálculos.'})
                elif company['cnae']!=snapshot.get('company_cnae',company['cnae']):
                    warnings.append({'code':'cnae_changed','reason':'CNAE principal alterado após a importação. Revise a aplicabilidade das cópias antes da pré-apuração.'})
                records.append(dict(row)|{'snapshot':snapshot,'rule_ids':json.loads(row['rule_ids_json']),
                    'warnings':warnings,'activity_enforced_in_assessment':False,'review_required':True})
            return records


    @staticmethod
    def _save_fiscal_library_version(conn,entity_type,row,actor):
        conn.execute('INSERT INTO fiscal_library_versions VALUES(?,?,?,?,?,?)',
                     (entity_type,row['id'],row['version'],pack(dict(row)),now(),actor))

    def fiscal_library_versions(self,cid,entity_type,item_id):
        with self.db.read() as conn:
            company_row(conn,cid); effect(conn,cid,'fiscal.masters' if entity_type=='catalog' else 'fiscal.parameters','read')
            return [{'version':r['version'],'snapshot':_row(json.loads(r['data_json'])),'created_at':r['created_at'],'created_by':r['created_by']}
                    for r in conn.execute('SELECT * FROM fiscal_library_versions WHERE entity_type=? AND entity_id=? ORDER BY version DESC',(entity_type,item_id))]

    def _fiscal_pattern_preview(self,conn,cid,item_id,payload):
        company=company_row(conn,cid)
        row=conn.execute('SELECT * FROM fiscal_patterns WHERE id=?',(item_id,)).fetchone()
        if not row: raise DomainError('Padrão não localizado.',404)
        pattern=_row(row); check_version(row,payload)
        if not pattern['active']: raise DomainError('Padrão global inativo.')
        if pattern['regime']!=company['regime']: raise DomainError('Regime do padrão difere do regime cadastrado da empresa.')
        segment=text(payload.get('segment'),'Segmento confirmado',True,30)
        if segment!=pattern['segment']: raise DomainError('Confirme o segmento da empresa para este padrão.')
        if pattern.get('activity') and text(payload.get('activity_confirmed'),'Atividade confirmada',True,200)!=pattern['activity']:
            raise DomainError('Confirme a atividade declarada pela empresa para este padrão.')
        cnae=company.get('cnae','')
        if pattern.get('cnae_prefix') and not cnae.startswith(pattern['cnae_prefix']):
            raise DomainError('CNAE cadastrado da empresa não corresponde ao filtro do padrão.')
        validity=_validity(payload,required=True)
        if (pattern['valid_from'] and validity['valid_from']<pattern['valid_from']) or (pattern['valid_to'] and (not validity['valid_to'] or validity['valid_to']>pattern['valid_to'])):
            raise DomainError('Vigência da empresa fora do intervalo do padrão.')
        existing=[dict(r) for r in conn.execute('SELECT id,version,name,tax,active FROM rules WHERE company_id=? AND superseded_by IS NULL ORDER BY id',(cid,))]
        preview={'pattern':pattern,'company_id':cid,'company_version':company['version'],'company_cnae':cnae,'activity_confirmed':payload.get('activity_confirmed',''),'reason':text(payload.get('reason'),'Motivo da importação',True,1000),'responsible':text(payload.get('responsible'),'Responsável pela revisão',True,200),'company_validity':validity,
                 'existing_rules':existing,'rules_to_create':len(pattern['rules']),'active':False,'status':'draft','review_required':True}
        return preview|{'preview_hash':digest(preview)}

    def preview_fiscal_pattern(self,cid,item_id,payload):
        with self.db.read() as conn:
            effect(conn,cid,'fiscal.parameters','read')
            return self._fiscal_pattern_preview(conn,cid,item_id,payload)
