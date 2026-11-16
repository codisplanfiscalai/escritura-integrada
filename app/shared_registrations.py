"""Installation-wide common registry with company-local usage and immutable FKs.

The database is the installation/organization boundary. Never federate identities
across databases or infer a grant from a matching tax identifier.
"""
import json

from .cadastros import tax_identity
from .core import DomainError, audit, boolean, check_version, company_row, integer, now, pack, text
from .permissions import effect, readable, require
from .db import request_context
from .third_parties import UFS, sync_third_party

FIELDS = ('trade_name', 'address', 'number', 'district', 'city', 'state', 'postal_code', 'ibge', 'im', 'cnae')


def migrate(conn):
    conn.execute('BEGIN IMMEDIATE')
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS shared_registrations (
            id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('third-party','accountant')),
            name TEXT NOT NULL, tax_id TEXT NOT NULL DEFAULT '', data_json TEXT NOT NULL DEFAULT '{}',
            active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS shared_registration_links (
            registration_id INTEGER NOT NULL REFERENCES shared_registrations(id),
            company_id INTEGER NOT NULL REFERENCES companies(id), master_id INTEGER,
            PRIMARY KEY(registration_id,company_id), UNIQUE(company_id,master_id),
            FOREIGN KEY(company_id,master_id) REFERENCES masters(company_id,id))''')
        # Exactly one global entry per legacy master, even for equal/invalid tax IDs.
        # No FK, master, document, title or identity history is rewritten.
        for row in conn.execute("SELECT * FROM masters WHERE kind='participant' ORDER BY id").fetchall():
            register_local(conn,row)
        conn.execute("INSERT INTO meta(key,value) VALUES('shared_registrations_schema_version','1') ON CONFLICT(key) DO NOTHING")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def register_local(conn,row):
    """Called by legacy imports/CRUD in their transaction, after schema creation."""
    if row['kind']!='participant' or not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='shared_registration_links'").fetchone():
        return
    if conn.execute('SELECT 1 FROM shared_registration_links WHERE company_id=? AND master_id=?',(row['company_id'],row['id'])).fetchone():
        return
    data=json.loads(row['data_json'])
    rid=conn.execute("""INSERT INTO shared_registrations(name,tax_id,kind,data_json,active,created_at,updated_at)
        VALUES(?,?,'third-party',?,?,?,?)""",(row['name'],row['tax_id'],pack({k:data[k] for k in FIELDS if k in data}),row['active'],now(),now())).lastrowid
    conn.execute('INSERT INTO shared_registration_links VALUES(?,?,?)',(rid,row['company_id'],row['id']))


def routine(kind):
    if kind not in {'third-party', 'accountant'}:
        raise DomainError('Cadastro não encontrado.', 404)
    return 'fiscal.shared_parties' if kind == 'third-party' else 'accounting.accountants'


class SharedRegistrationsMixin:
    def _registration(self, conn, cid, kind, rid):
        effect(conn, cid, routine(kind), 'read')
        company_row(conn,cid)
        row = conn.execute('SELECT * FROM shared_registrations WHERE id=? AND kind=?',(rid,kind)).fetchone()
        if not row:
            raise DomainError('Cadastro global não encontrado.',404,'not_found')
        result = dict(row)
        result['data'] = json.loads(result.pop('data_json'))
        result['active'] = bool(result['active'])
        # Neither hidden company IDs nor counts are exposed.
        result['links'] = [dict(l) for l in conn.execute('SELECT company_id,master_id FROM shared_registration_links WHERE registration_id=? ORDER BY company_id', (rid,)) if readable(conn,l['company_id'],'fiscal.masters' if kind=='third-party' else routine(kind))]
        return result

    def registrations(self, cid, kind):
        with self.db.read(snapshot=True) as conn:
            company_row(conn,cid)
            effect(conn,cid,routine(kind),'read')
            return [self._registration(conn,cid,kind,r['id']) for r in conn.execute(
                'SELECT id FROM shared_registrations WHERE kind=? ORDER BY name,id',(kind,))]

    def registration(self, cid, kind, rid):
        with self.db.read(snapshot=True) as conn:
            return self._registration(conn,cid,kind,rid)

    def _registration_admin(self,conn):
        # Common profile writes affect the entire installation, like other global
        # catalogs. Local routine grants alone never become global write authority.
        ctx=request_context.get()
        if ctx and ctx.get('user_id'):
            require(conn,ctx['user_id'],None,admin=True)

    def save_registration(self,cid,kind,payload,actor,rid=None):
        with self.db.transaction() as conn:
            company_row(conn,cid)
            self._registration_admin(conn)
            effect(conn,cid,routine(kind),'edit' if rid else 'create')
            old = self._registration(conn,cid,kind,rid) if rid else None
            if old:
                check_version(old,payload)
            name = text(payload.get('name'),'Nome',True,250)
            tax_id = tax_identity(payload.get('tax_id'))
            if old and tax_id != old['tax_id']:
                raise DomainError('Identidade preservada. Cadastre outra pessoa para outro CPF/CNPJ.')
            active = boolean(payload.get('active'),True)
            if old and old['active'] != active:
                effect(conn,cid,routine(kind),'delete' if not active else 'edit')
            raw = payload.get('data',{})
            if not isinstance(raw,dict):
                raise DomainError('Dados cadastrais inválidos.')
            fields = (*FIELDS,'email','phone') if kind=='third-party' else ('crc','crc_state','category','email','phone')
            data = {k:text(raw.get(k),k,k in {'crc','crc_state','category'},500) for k in fields}
            if kind=='accountant':
                if len(tax_id)!=11:
                    raise DomainError('Informe o CPF do contador.')
                data['crc_state']=data['crc_state'].upper()
                if data['crc_state'] not in UFS or data['category'] not in {'accountant','technician'}:
                    raise DomainError('Confira UF do CRC e categoria profissional.')
            if kind=='third-party' and data['state'] and data['state'] not in UFS:
                raise DomainError('UF inválida.')
            if not old and tax_id and conn.execute('SELECT 1 FROM shared_registrations WHERE kind=? AND tax_id=?',(kind,tax_id)).fetchone():
                raise DomainError('Identidade já presente no catálogo global. Utilize o cadastro existente; registros ambíguos exigem revisão.',409)
            if old:
                conn.execute('UPDATE shared_registrations SET name=?,data_json=?,active=?,version=version+1,updated_at=? WHERE id=?',(name,pack(data),active,now(),rid))
            else:
                rid=conn.execute('INSERT INTO shared_registrations(kind,name,tax_id,data_json,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(kind,name,tax_id,pack(data),active,now(),now())).lastrowid
            for company_id in {cid} | {link['company_id'] for link in conn.execute('SELECT company_id FROM shared_registration_links WHERE registration_id=?',(rid,))}:
                audit(conn,company_id,actor,'update' if old else 'create','shared_registration',rid,{'kind':kind,'name':name,'active':active})
            return self._registration(conn,cid,kind,rid)

    def _registration_master(self,conn,cid,rid,name,tax_id,data,actor,payload):
        """Explicit local usage snapshot; never merge matches or move existing FKs."""
        if payload.get('master_id'):
            master=self._master(conn,cid,integer(payload['master_id'],'Cadastro local'),'participant')
            check_version(master,{'version':payload.get('master_version')})
            if master['tax_id']!=tax_id or not master['active']:
                raise DomainError('Cadastro local deve estar ativo e ter a mesma identidade.')
            if conn.execute('SELECT 1 FROM shared_registration_links WHERE company_id=? AND master_id=?',(cid,master['id'])).fetchone():
                raise DomainError('Cadastro local já vinculado. Nenhuma união automática é permitida.',409)
            return master['id']
        code=text(payload.get('code'),'Código local',False,50)
        if not code:
            code=f'GLOBAL-{rid}'
            suffix=0
            while conn.execute("SELECT 1 FROM masters WHERE company_id=? AND kind='participant' AND code=?",(cid,code)).fetchone():
                suffix+=1
                code=f'GLOBAL-{rid}-{suffix}'
        if conn.execute("SELECT 1 FROM masters WHERE company_id=? AND kind='participant' AND (code=? OR (tax_id<>'' AND tax_id=?))",(cid,code,tax_id)).fetchone():
            raise DomainError('Já existe código ou identidade nesta empresa. Revise o cadastro local; não foi criada duplicidade.',409)
        mid=conn.execute("""INSERT INTO masters(company_id,kind,code,name,tax_id,data_json,created_at,updated_at)
            VALUES(?,'participant',?,?,?,?,?,?)""",(cid,code,name,tax_id,pack(data | {'roles':['customer','supplier']}),now(),now())).lastrowid
        conn.execute('INSERT INTO shared_registration_links VALUES(?,?,?)',(rid,cid,mid))
        sync_third_party(conn,cid,mid,actor,'Vínculo explícito ao cadastro compartilhado.')
        return mid

    def link_registration(self,cid,kind,rid,payload,actor):
        target=integer(payload.get('company_id'),'Empresa de destino')
        with self.db.transaction() as conn:
            row=self._registration(conn,cid,kind,rid)
            check_version(row,payload)
            # Consultation is already global. This operation only enables local
            # use; it grants no access to a different company's masters/documents.
            effect(conn,target,routine(kind),'read')
            effect(conn,target,'fiscal.masters' if kind=='third-party' else routine(kind),'create' if kind=='third-party' else 'edit')
            company_row(conn,target)
            if not row['active']:
                raise DomainError('Cadastro inativo não pode receber novos vínculos.')
            if conn.execute('SELECT 1 FROM shared_registration_links WHERE registration_id=? AND company_id=?',(rid,target)).fetchone():
                return self._registration(conn,cid,kind,rid)
            if kind=='accountant' and conn.execute("SELECT 1 FROM shared_registrations r JOIN shared_registration_links l ON l.registration_id=r.id WHERE l.company_id=? AND r.kind='accountant' AND r.tax_id=?",(target,row['tax_id'])).fetchone():
                raise DomainError('Já existe contador com esta identidade no destino. Revise os cadastros; nenhuma união foi realizada.',409)
            mid=self._registration_master(conn,target,rid,row['name'],row['tax_id'],row['data'],actor,payload) if kind=='third-party' else None
            conn.execute('INSERT OR IGNORE INTO shared_registration_links VALUES(?,?,?)',(rid,target,mid))
            audit(conn,target,actor,'link','shared_registration',rid,{'kind':kind})
            return self._registration(conn,cid,kind,rid)

    def deactivate_registration(self,cid,kind,rid,payload,actor):
        with self.db.transaction() as conn:
            row=self._registration(conn,cid,kind,rid)
            check_version(row,payload)
            self._registration_admin(conn)
            effect(conn,cid,routine(kind),'delete')
            conn.execute('UPDATE shared_registrations SET active=0,version=version+1,updated_at=? WHERE id=?',(now(),rid))
            for company_id in {cid} | {link['company_id'] for link in conn.execute('SELECT company_id FROM shared_registration_links WHERE registration_id=?',(rid,))}:
                audit(conn,company_id,actor,'deactivate','shared_registration',rid,{'preserved_local_links':True})
            return self._registration(conn,cid,kind,rid)
