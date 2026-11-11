"""Opt-in operational restrictions; authentication and integrity stay mandatory."""
import base64
import json
from fastapi import Body, Request
from .core import DomainError, audit, company_row, now, pack, text

MAX_UPLOAD_BYTES = 128 * 1024 * 1024
DEFAULTS = dict(require_extra_confirmations=False, require_separate_document_review=False,
    enforce_period_locks=False, enforce_package_retention=False,
    protect_fiscal_source=False, block_imports=False, block_movement_deletion=False,
    block_package_cleanup=False, limit_import_size=False, limit_batch_selection=False,
    import_size_mb=20, batch_selection_limit=5000)
LABELS = {
    'require_extra_confirmations': ('Pedir confirmações adicionais', 'Abrir uma confirmação extra na importação e limpeza. Desativado: o botão final executa a ação apresentada na prévia.'),
    'require_separate_document_review': ('Exigir conferência em etapa separada', 'Exigir marcar o documento como conferido antes de escriturar. Desativado: permite conferir e escriturar em uma única ação.'),
    'enforce_period_locks': ('Respeitar bloqueios mensais', 'Impedir alterações em competências fechadas. Desativar não altera a marcação do mês.'),
    'enforce_package_retention': ('Exigir prazo para limpar originais', 'Aplicar o prazo da limpeza de arquivos também às limpezas manuais.'),
    'protect_fiscal_source': ('Proteger originais de documentos importados', 'Impedir a remoção do original quando há documentos vinculados.'),
    'block_imports': ('Bloquear importações', 'Impedir análise, confirmação e reprocessamento fiscal, contábil e financeiro.'),
    'block_movement_deletion': ('Bloquear exclusão de movimentos', 'Impedir exclusão e limpeza de documentos fiscais e lançamentos contábeis.'),
    'block_package_cleanup': ('Bloquear limpeza de lotes', 'Impedir limpeza manual e programada de arquivos e histórico.'),
    'limit_import_size': ('Limitar tamanho do arquivo', 'Aplicar o tamanho abaixo. A proteção técnica de 128 MiB permanece.'),
    'limit_batch_selection': ('Limitar quantidade selecionada', 'Aplicar a quantidade abaixo às operações em lote e à limpeza de arquivos.'),
    'import_size_mb': ('Tamanho máximo (MiB)', 'Usado somente quando o limite de arquivo estiver ativado.'),
    'batch_selection_limit': ('Quantidade máxima por seleção', 'Usada somente quando o limite de seleção estiver ativado.'),
}
FIELDS = [dict(key=k, label=LABELS[k][0], description=LABELS[k][1], type='boolean' if type(v) is bool else 'integer', **({} if type(v) is bool else {'min': 1, 'max': 128 if k == 'import_size_mb' else 1000000})) for k,v in DEFAULTS.items()]


def migrate(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS company_operational_settings (
        company_id INTEGER PRIMARY KEY REFERENCES companies(id), settings_json TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS operational_setting_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT NOT NULL,
        settings_json TEXT NOT NULL, source_company_id INTEGER NOT NULL REFERENCES companies(id),
        created_at TEXT NOT NULL, created_by TEXT NOT NULL)''')


def get_settings(conn,cid):
    company_row(conn,cid)
    row=conn.execute('SELECT settings_json FROM company_operational_settings WHERE company_id=?',(cid,)).fetchone()
    return DEFAULTS | (json.loads(row['settings_json']) if row else {})


def ensure_action_allowed(conn,cid,key):
    if get_settings(conn,cid)[key]:
        raise DomainError(LABELS[key][0]+': restrição ativada nos parâmetros operacionais da empresa.',409,'operational_restriction')


def ensure_import_allowed(conn,cid,size=0):
    cfg=get_settings(conn,cid)
    if cfg['block_imports']:
        raise DomainError('Importações bloqueadas nos parâmetros operacionais da empresa.',409,'operational_restriction')
    maximum=cfg['import_size_mb']*1024*1024 if cfg['limit_import_size'] else MAX_UPLOAD_BYTES
    if size>maximum:
        message=f"Arquivo excede o limite configurado de {cfg['import_size_mb']} MiB. Ajuste os parâmetros da empresa." if cfg['limit_import_size'] else 'Arquivo excede a proteção técnica de 128 MiB. Divida o arquivo.'
        raise DomainError(message,413,'file_too_large')


def decode_import_content(conn,cid,encoded):
    ensure_import_allowed(conn,cid)
    if not isinstance(encoded,str): raise DomainError('Selecione um arquivo para importar.')
    if len(encoded)>((MAX_UPLOAD_BYTES+2)//3)*4:
        raise DomainError('Arquivo excede a proteção técnica de 128 MiB.',413,'file_too_large')
    try: raw=base64.b64decode(encoded,validate=True)
    except (ValueError,base64.binascii.Error): raise DomainError('Conteúdo base64 inválido.') from None
    if not raw: raise DomainError('O arquivo selecionado está vazio.')
    ensure_import_allowed(conn,cid,len(raw))
    return raw


def ensure_selection_allowed(conn,cid,count):
    cfg=get_settings(conn,cid)
    if cfg['limit_batch_selection'] and count>cfg['batch_selection_limit']:
        raise DomainError(f"Seleção excede {cfg['batch_selection_limit']} registros, conforme os parâmetros da empresa.",409,'selection_limit')


def normalize(values):
    if not isinstance(values,dict) or set(values)-set(DEFAULTS): raise DomainError('Parâmetros operacionais inválidos ou desconhecidos.')
    result=DEFAULTS|values
    for field in FIELDS:
        value=result[field['key']]
        if field['type']=='boolean':
            if type(value) is not bool: raise DomainError(field['label']+': informe sim ou não.')
        elif type(value) is not int or not field['min']<=value<=field['max']:
            raise DomainError(field['label']+': valor fora do intervalo permitido.')
    return result


def save_settings(conn,cid,payload,actor):
    company_row(conn,cid)
    row=conn.execute('SELECT version FROM company_operational_settings WHERE company_id=?',(cid,)).fetchone()
    version=row['version'] if row else 0
    if type(payload.get('version')) is not int or payload['version']!=version:
        raise DomainError('Os parâmetros mudaram. Atualize a configuração antes de salvar.',409,'stale_version')
    cfg=normalize(payload.get('settings'))
    conn.execute('''INSERT INTO company_operational_settings VALUES(?,?,?,?,?)
        ON CONFLICT(company_id) DO UPDATE SET settings_json=excluded.settings_json,
        version=excluded.version,updated_at=excluded.updated_at,updated_by=excluded.updated_by''',
        (cid,pack(cfg),version+1,now(),actor))
    audit(conn,cid,actor,'configure','operational-settings',cid,{'settings':cfg,'version':version+1})
    return cfg


def describe(conn,cid,uid):
    from .permissions import company_access
    company_row(conn,cid)
    row=conn.execute('SELECT version FROM company_operational_settings WHERE company_id=?',(cid,)).fetchone()
    templates=[{'id':'unrestricted','name':'Sem restrições operacionais','description':'Modelo padrão: todas as restrições opcionais desativadas.','settings':dict(DEFAULTS)}]
    for item in conn.execute('SELECT * FROM operational_setting_templates ORDER BY name,id'):
        if company_access(conn,uid,item['source_company_id'])[0]:
            templates.append({'id':item['id'],'name':item['name'],'description':item['description'],'settings':json.loads(item['settings_json'])})
    return {'settings':get_settings(conn,cid),'defaults':dict(DEFAULTS),'fields':FIELDS,'version':row['version'] if row else 0,'templates':templates,'technical_upload_limit_mb':128}


def register(app,core,actor):
    @app.get('/api/companies/{cid}/operational-settings')
    def read(cid:int,request:Request):
        with core.db.read() as conn: return describe(conn,cid,request.state.session['user']['id'])

    @app.put('/api/companies/{cid}/operational-settings')
    def save(cid:int,request:Request,payload:dict=Body(...)):
        with core.db.transaction() as conn:
            save_settings(conn,cid,payload,actor(request))
            return describe(conn,cid,request.state.session['user']['id'])

    @app.post('/api/companies/{cid}/operational-settings/templates')
    def create_template(cid:int,request:Request,payload:dict=Body(...)):
        with core.db.transaction() as conn:
            name=text(payload.get('name'),'Nome do modelo',True,120)
            description=text(payload.get('description'),'Descrição',False,1000)
            cfg=get_settings(conn,cid)
            iid=conn.execute('INSERT INTO operational_setting_templates(name,description,settings_json,source_company_id,created_at,created_by) VALUES(?,?,?,?,?,?)',(name,description,pack(cfg),cid,now(),actor(request))).lastrowid
            audit(conn,cid,actor(request),'create','operational-template',iid,{'name':name,'settings':cfg})
            return describe(conn,cid,request.state.session['user']['id'])|{'created_template_id':iid}

    @app.post('/api/companies/{cid}/operational-settings/apply-template')
    def apply_template(cid:int,request:Request,payload:dict=Body(...)):
        with core.db.transaction() as conn:
            uid=request.state.session['user']['id']
            template=next((r for r in describe(conn,cid,uid)['templates'] if r['id']==payload.get('template_id')),None)
            if template is None: raise DomainError('Modelo não encontrado ou indisponível para este usuário.',404,'not_found')
            save_settings(conn,cid,{'settings':template['settings'],'version':payload.get('version')},actor(request))
            return describe(conn,cid,uid)
