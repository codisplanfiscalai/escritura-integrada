"""Lossless company-scoped series formatting and stable document identity."""
import json
DEFAULT_DIGITS = 3
SETTINGS_KIND = 'fiscal_series_settings'
IDENTITY_FIELDS = ('direction','model','series','number','partner_tax_id','partner_name','issue_date')
VALUE_FIELDS = ('direction','number','series','model','partner_name','partner_tax_id','key','cfop','issue_date','posting_date','total_cents')

def numeric_series(value):
    return isinstance(value,str) and bool(value) and value.isascii() and value.isdigit()

def normalize_series(value,digits=DEFAULT_DIGITS):
    return value.zfill(digits) if numeric_series(value) else value

def canonical_series(value):
    return (value.lstrip('0') or '0') if numeric_series(value) else value

def settings(conn,cid):
    from .core import DomainError
    row=conn.execute('SELECT m.data_json,m.version FROM companies c LEFT JOIN masters m ON m.company_id=c.id AND m.kind=? AND m.code=? WHERE c.id=?',(SETTINGS_KIND,'default',cid)).fetchone()
    if row is None: raise DomainError('Empresa não encontrada.',404,'not_found')
    return {'digits':json.loads(row['data_json'])['digits'] if row['data_json'] is not None else DEFAULT_DIGITS,'version':row['version'] if row['version'] is not None else 0}

def presentation(document,digits):
    result=dict(document)
    result.setdefault('declared_series',result.get('series',''))
    result['series']=normalize_series(result.get('series',''),digits)
    return result

def business_key(document):
    from .core import digest
    if document.get('key'):return 'key:'+document['key']
    identity={k:document.get(k,'') for k in IDENTITY_FIELDS}
    identity['series']=canonical_series(identity['series'])
    return digest(identity)

def find_document(conn,cid,document,exclude_id=None):
    from .core import DomainError
    if document.get('key'):
        found=conn.execute('SELECT * FROM documents WHERE company_id=? AND business_key=? AND id<>?',(cid,'key:'+document['key'],exclude_id or 0)).fetchall()
    else:
        fields=[k for k in IDENTITY_FIELDS if k!='series']
        candidates=conn.execute("SELECT * FROM documents WHERE company_id=? AND key='' AND id<>? AND "+' AND '.join(k+'=?' for k in fields),(cid,exclude_id or 0,*(document.get(k,'') for k in fields)))
        found=[r for r in candidates if canonical_series(r['series'])==canonical_series(document.get('series',''))]
    if len(found)>1:raise DomainError('Há documentos com identidade equivalente após padronizar a série. Confira as duplicidades; nenhum registro foi mesclado.',409,'series_identity_conflict')
    return found[0] if found else None

def payload_hash(values,taxes,items,extras=None,imported=False):
    from .core import digest,document_item_semantics
    fields={k:values[k] for k in VALUE_FIELDS};fields['series']=canonical_series(fields['series'])
    if (extras or {}).get('book_cancellation'):fields['book_cancellation']=extras['book_cancellation']
    return digest(fields|{'taxes':taxes,'items':document_item_semantics(items,imported)})

def stored_payload_hash(row):
    extras=json.loads(row['extra_json'])
    return payload_hash(row,json.loads(row['taxes_json']),json.loads(row['items_json']),extras,bool(row['source_hash'] and isinstance(extras.get('issuer'),dict)))
