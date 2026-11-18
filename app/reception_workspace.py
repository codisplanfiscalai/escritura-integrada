"""Local reception workspace. Reads receipts without certificates or fiscal network."""
import json
import csv
import io
import re
import uuid
from .core import DomainError,audit,company_row,digest,now,pack
from .permissions import require,decision
from .reception_service import RUN_SCOPE
from .file_store import read_file
from .reception import read_nfe_distribution
from .reception_metadata import classify
from .reception_archive import project,select,detail,matches,decorate
from .reception_vault import CompanyA1Vault,ENVS
from .reception_configuration import SETTINGS,preferences,configuration,require_configuration

CAPABILITIES={
 'nfe_distribution':{'remote_available':True,'coverage':'Distribuição NF-e modelo 55. Consulta real/homologação externa não comprovadas nesta reconstrução.'},
 'nfse_adn':{'remote_available':True,'coverage':'Consulta e download ADN por NSU, com certificado da empresa e ambientes independentes da NF-e.'}
}

class ReceptionWorkspace:
    def __init__(self,core,reception):
        self.core,self.db,self.reception=core,core.db,reception
    def preferences(self,conn,cid):
        return preferences(conn,cid)
    def settings(self,cid,uid):
        with self.db.read() as conn:
            require(conn,uid,cid,'system.companies','read');company=company_row(conn,cid)
            result={'preferences':self.preferences(conn,cid),'cursors':self.cursor_settings(conn,cid,company),'can_edit':decision(conn,uid,cid,'system.companies','edit')['allowed']}
        return result|{'credential':CompanyA1Vault(self.db).status(cid,uid),'password_api_supported':False,'a3_available':False,'cpf_available':False}
    def cursor_settings(self,conn,cid,company):
        """Read the live automatic cursors; never maintain a separate manual copy."""
        result={}
        for provider,environments in ENVS.items():
            result[provider]={}
            for environment in environments:
                state=self.reception._state(conn,cid,provider+':'+environment+':'+company['tax_id'])
                result[provider][environment]=self.cursor_snapshot(cid,company['tax_id'],provider,environment,state)
        return result
    def cursor_snapshot(self,cid,target,provider,environment,state):
        return {'cursor':state['cursor'],'revision':digest({'company':cid,'target':target,
                'provider':provider,'environment':environment,'state':state}),
                'busy':state['lease_until']>self.reception.clock(),'next_allowed_at':state['next_allowed_at']}
    def adjust_cursor(self,cid,uid,actor,payload):
        from .reception import nsu,adn_nsu
        from .reception_credentials import query_cnpj
        from .importers import ImportProblem
        if not isinstance(payload,dict) or set(payload)!={'provider','environment','cursor','expected_revision','confirmed'}:
            raise DomainError('Informe serviço, ambiente, NSU, revisão e confirmação do ajuste.')
        provider,environment=payload['provider'],payload['environment']
        self.reception._spec(provider,environment)
        if payload['confirmed'] is not True:
            raise DomainError('Confirme o ajuste manual: avançar pode deixar documentos anteriores fora das próximas consultas.')
        if not isinstance(payload['cursor'],str):
            raise DomainError('Informe o NSU como texto decimal, sem pontuação.')
        try:new=(nsu if provider=='nfe_distribution' else adn_nsu)(payload['cursor'])
        except ImportProblem as error:raise DomainError(str(error)) from None
        with self.db.transaction() as conn:
            require(conn,uid,cid,'system.companies','edit')
            company=company_row(conn,cid)
            target=query_cnpj(company['tax_id'],provider)
            key=provider+':'+environment+':'+target
            state=self.reception._state(conn,cid,key)
            current=self.cursor_snapshot(cid,target,provider,environment,state)
            if current['busy']:
                raise DomainError('Existe consulta em andamento. Aguarde sua conclusão antes de ajustar o NSU.',409,'reception_busy')
            if payload['expected_revision']!=current['revision']:
                raise DomainError('O NSU foi atualizado ou a empresa mudou. Recarregue os parâmetros antes de ajustar.',409,'stale_reception_cursor')
            if new==state['cursor']:return current
            adjustment=uuid.uuid4().hex
            record={'provider':provider,'environment':environment,'target_tax_id':target,
                    'cursor_before':state['cursor'],'cursor_after':new,'documents_changed':False,
                    'direction':'forward' if int(new)>int(state['cursor']) else 'backward'}
            # Retain all originals, receipts and official cooldown. An expired
            # worker can no longer commit against this new state/lease.
            state.update(cursor=new,lease_id=None,lease_until=0,last_manual_adjustment=adjustment)
            self.reception._save_state(conn,cid,key,state)
            conn.execute('INSERT INTO operations(company_id,scope,key,request_hash,result_json,created_at) VALUES(?,?,?,?,?,?)',
                         (cid,'reception-nsu-adjustment-v1',adjustment,digest(record),pack(record),now()))
            audit(conn,cid,actor,'adjust-nsu','fiscal-reception',adjustment,record)
            return self.cursor_snapshot(cid,target,provider,environment,state)
    def save_settings(self,cid,uid,actor,payload):
        if not isinstance(payload,dict) or set(payload)!={'version','nfe_environment','nfse_environment'}:
            raise DomainError('Informe somente versão e ambientes padrão.')
        for provider,key in [('nfe_distribution','nfe_environment'),('nfse_adn','nfse_environment')]:
            if not isinstance(payload[key],str) or payload[key] not in ENVS[provider]:raise DomainError('Ambiente inválido.')
        with self.db.transaction() as conn:
            require(conn,uid,cid,'system.companies','edit');company_row(conn,cid)
            old=self.preferences(conn,cid)
            if type(payload['version']) is not int or old['version']!=payload['version']:raise DomainError('Configuração alterada. Recarregue o cadastro.',409,'stale_version')
            result=payload|{'version':old['version']+1}
            conn.execute('''INSERT INTO operations(company_id,scope,key,request_hash,result_json,created_at) VALUES(?,?,?,?,?,?)
                ON CONFLICT(company_id,scope,key) DO UPDATE SET request_hash=excluded.request_hash,result_json=excluded.result_json''',(cid,SETTINGS,'defaults',digest(result),pack(result),now()))
            audit(conn,cid,actor,'configure','reception-preferences',cid,result)
            return result
    def validate_filters(self,provider,environment,year,query,offset,direction,competence):
        if provider not in ENVS or environment not in ENVS[provider]:raise DomainError('Serviço/ambiente inválido.')
        if type(year) is not int or not 1900<=year<=2199 or type(offset) is not int or not 0<=offset<=100000 or not isinstance(query,str) or len(query)>120:raise DomainError('Filtro ou página inválidos.')
        if direction not in {'','issued','received','both','unknown'} or not isinstance(competence,str) or competence and (len(competence)!=7 or competence[4]!='-' or not competence.replace('-','').isdigit() or not 1<=int(competence[5:])<=12):
            raise DomainError('Direção ou competência declarada inválidas.')
    def rows(self,conn,cid,provider,environment,year=None):
        patterns=['%"provider":"'+provider+'",%','%"environment":"'+environment+'",%']
        rows=conn.execute('''SELECT key,result_json,created_at FROM operations WHERE company_id=? AND scope=?
            AND result_json LIKE ? AND result_json LIKE ? ORDER BY created_at DESC,key DESC''',(cid,RUN_SCOPE,*patterns))
        for row in rows:
            result=json.loads(row['result_json'])
            if result.get('provider')==provider and result.get('environment')==environment and (year is None or str(result.get('period',''))[:4]==str(year)):
                yield row,result
    def occurrences(self,conn,cid,provider,environment,target):
        cache={}
        for row,result in self.rows(conn,cid,provider,environment):
            for entry in self.local_entries(conn,cid,result,target,cache):
                safe={k:entry[k] for k in ('nsu','schema','kind','document_type','access_key','generation_time','bytes','direction','company_roles','issuer_name','issuer_tax_id','issue_date','declared_competence','number','xml_access_key','sha256','content_verified') if k in entry}
                yield safe|{'receipt_key':row['key'],'received_at':row['created_at'],'reference_period':result['period'],
                    'target_tax_id':result.get('target_tax_id'),'state':result['state'],
                    'available':bool(entry.get('file_id') or provider=='nfe_distribution' and result.get('file_id'))}
    def archive(self,conn,cid,provider,environment,target):
        return project(cid,provider,environment,self.occurrences(conn,cid,provider,environment,target))
    def versions(self,cid,uid,provider,environment,year,rid,offset=0):
        self.validate_filters(provider,environment,year,'',offset,'','')
        if not re.fullmatch('[a-f0-9]{64}',rid):raise DomainError('Documento local inválido.')
        with self.db.read(snapshot=True) as conn:
            company=self.reception._access(conn,uid,cid)
            for group in self.archive(conn,cid,provider,environment,company['tax_id']):
                if group['record_id']==rid and select(group,year):return detail(group,offset)|{'provider':provider,'environment':environment}
        raise DomainError('Documento não localizado neste acervo.',404,'not_found')
    def overview(self,cid,uid,provider,environment,year,query='',offset=0,direction='',competence=''):
        with self.db.read(snapshot=True) as conn:
            company=self.reception._access(conn,uid,cid)
            prefs=self.preferences(conn,cid)
            selected=configuration(conn,cid,provider,self.reception.credentials)
            environment=selected['environment'] if environment is None else environment
            self.validate_filters(provider,environment,year,query,offset,direction,competence)
            state=self.reception._state(conn,cid,provider+':'+environment+':'+company['tax_id'])
            groups=self.archive(conn,cid,provider,environment,company['tax_id'])
            documents=[item for group in groups if (item:=select(group,year,query,direction,competence)) is not None]
            receipts=[]
            for row,result in self.rows(conn,cid,provider,environment,year):
                receipts.append({k:result[k] for k in ('state','period','cursor_before','cursor_after','error_codes','code') if k in result}|{'receipt_key':row['key'],'created_at':row['created_at'],'count':len(result.get('entries',[])),'has_original':bool(result.get('file_id'))})
                if len(receipts)==20:break
            return {'preferences':prefs,'configuration':selected,'provider':provider,'environment':environment,
                'state':{'cursor':state['cursor'],'next_allowed_at':state['next_allowed_at'],'busy':state['lease_until']>self.reception.clock()},
                'documents':documents[offset:offset+20],'offset':offset,'has_more':len(documents)>offset+20,'receipts':receipts,
                'capabilities':CAPABILITIES[provider]|{'automation_available':True,'a1_cnpj_only':True}}
    def receipt_history(self,cid,uid,provider,environment,year,offset=0):
        """Page the audit history without opening or decompressing original XMLs."""
        self.validate_filters(provider,environment,year,'',offset,'','')
        with self.db.read(snapshot=True) as conn:
            self.reception._access(conn,uid,cid)
            items=[]
            for index,(row,result) in enumerate(self.rows(conn,cid,provider,environment,year)):
                if index < offset:continue
                items.append({k:result[k] for k in ('state','period','cursor_before','cursor_after','error_codes','code') if k in result}|{'receipt_key':row['key'],'created_at':row['created_at'],'count':len(result.get('entries',[])),'has_original':bool(result.get('file_id'))})
                if len(items)>20:break
            return {'provider':provider,'environment':environment,'receipts':items[:20],
                    'offset':offset,'has_more':len(items)>20}

    def local_entries(self,conn,cid,result,target,cache=None):
        cache={} if cache is None else cache
        files=cache.setdefault('files',{});metadata_cache=cache.setdefault('metadata',{})
        entries=result.get('entries',[])
        packets={}
        if result.get('provider')=='nfe_distribution' and entries and result.get('file_id'):
            original=read_file(conn,cid,result['file_id'])
            if original['sha256']!=result['sha256']:raise DomainError('Original divergente. Confira a integridade do acervo.',409,'file_integrity')
            packets={p['nsu']:p for p in read_nfe_distribution(original['content'])['entries']}
        for entry in entries:
            raw=None
            if packets:
                packet=packets.get(entry['nsu'])
                if not packet or packet['sha256']!=entry['sha256']:raise DomainError('XML divergente.',409,'file_integrity')
                raw=packet['xml']
            elif result.get('provider')=='nfse_adn' and entry.get('file_id'):
                fid=entry['file_id']
                if fid not in files:
                    original=read_file(conn,cid,fid)
                    files[fid]=(original['sha256'],len(original['content']))
                    metadata_cache[original['sha256']]=classify(original['content'],result['provider'],target)
                sha,size=files[fid]
                if sha!=entry['sha256'] or size!=entry['bytes']:raise DomainError('XML divergente.',409,'file_integrity')
                yield entry|metadata_cache[sha]|{'content_verified':True}
                continue
            if raw:
                if entry['sha256'] not in metadata_cache:metadata_cache[entry['sha256']]=classify(raw,result['provider'],target)
                metadata=metadata_cache[entry['sha256']]
            else:metadata={'direction':'unknown','company_roles':[]}
            yield entry|metadata|{'content_verified':raw is not None}

    def report(self,cid,uid,provider,environment,year,query='',direction='',competence='',view='documents'):
        if view not in {'documents','occurrences'}:raise DomainError('Tipo de relatório local inválido.')
        self.validate_filters(provider,environment,year,query,0,direction,competence)
        output=io.StringIO(newline='')
        writer=csv.writer(output,delimiter=';')
        fields=['environment','reference_period','declared_competence','direction','nsu','access_key','xml_access_key','number','issuer_tax_id','issuer_name','issue_date','received_at','receipt_key','sha256','record_id','version_count','occurrence_count','versions_pending_review','first_sha256']
        writer.writerow(fields)
        # One read snapshot: concurrent arrivals cannot shift pages or duplicate rows.
        with self.db.read(snapshot=True) as conn:
            require(conn,uid,cid,'fiscal.imports','export')
            company=self.reception._access(conn,uid,cid)
            count=0
            for group in self.archive(conn,cid,provider,environment,company['tax_id']):
                selected=select(group,year,query,direction,competence)
                if selected is None:continue
                items=[selected] if view=='documents' else (decorate(group,i) for i in group['occurrences'] if matches(i,year,query,direction,competence))
                for item in items:
                    count+=1
                    if count>100000:raise DomainError('Relatório local excede a proteção técnica. Reduza os filtros.',413,'report_size')
                    values=[]
                    for field in fields:
                        value=str(environment if field=='environment' else item.get(field,''))
                        values.append("'"+value if (value.lstrip().startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n'))) else value)
                    writer.writerow(values)
        return ('\ufeff'+output.getvalue()).encode('utf-8')

    def check(self,cid,uid,provider,payload):
        with self.db.read() as conn:
            company=self.reception._access(conn,uid,cid,'import')
            if not isinstance(payload,dict) or set(payload) not in ({'configuration_revision'},{'environment'}):
                raise DomainError('Informe somente a revisão da configuração da empresa.')
            # Compatibility for old local-check clients; they cannot override the saved environment.
            expected=payload.get('configuration_revision') if 'configuration_revision' in payload else configuration(conn,cid,provider,self.reception.credentials)['revision']
            selected=require_configuration(conn,cid,provider,self.reception.credentials,expected,payload.get('environment'))
        try:self.reception.local_identity(cid,company,provider,selected['environment'])
        except DomainError as error:return {'ready':False,'remote_checked':False,'message':error.detail,'code':error.code}
        with self.db.read() as conn:
            self.reception._access(conn,uid,cid,'import')
            require_configuration(conn,cid,provider,self.reception.credentials,expected)
        return {'ready':True,'remote_checked':False,'environment':selected['environment'],'message':'A1, identidade e validade conferidos localmente. A autorização e a aceitação externas ainda não foram verificadas.'}
    def capture(self,cid,uid,actor,provider,payload):
        if provider not in ENVS:raise DomainError('Serviço inválido.')
        if not CAPABILITIES[provider]['remote_available']:
            raise DomainError(CAPABILITIES[provider]['coverage'],409,'reception_contract_pending')
        if not isinstance(payload,dict) or set(payload)!={'environment','period','idempotency_key','configuration_revision'}:
            raise DomainError('Parâmetros de consulta inválidos. Atualize a tela.')
        if not isinstance(payload['configuration_revision'],str) or not re.fullmatch('[a-f0-9]{64}',payload['configuration_revision']):
            raise DomainError('Revisão da configuração inválida. Atualize a tela.')
        body={key:value for key,value in payload.items() if key!='configuration_revision'}
        return self.reception.query(cid,body|{'provider':provider},actor,uid,
                                    expected_configuration=payload['configuration_revision'])
