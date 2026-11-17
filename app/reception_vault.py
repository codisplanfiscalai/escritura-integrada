"""Company A1 vault. Ciphertext in DB; master key outside data/backups.

No secret read-back. POSIX uses private files; Windows uses CurrentUser DPAPI.
Certificate validation and TLS remain those of reception_credentials.load_a1.
"""
import base64
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import uuid
from . import backup_platform
from .core import DomainError,audit,company_row,digest,now,pack
from .permissions import require
from .reception_credentials import LocalA1Credentials,_private_file,load_a1,query_cnpj

SCOPE='reception-company-a1-v1'
ENVS={'nfe_distribution':{'homologation','production'},'nfse_adn':{'restricted_production','production'}}

def unavailable():
    raise DomainError('Cofre A1 indisponível ou integridade inválida. Confira a chave separada desta instalação.',503,'reception_vault_unavailable')

def dpapi(raw,protect):
    try:return backup_platform.dpapi(raw,protect)
    except (OSError,ValueError):unavailable()

class CompanyA1Vault:
    def __init__(self,db,directory=None,fallback=None):
        self.db,self.directory=db,directory
        self.fallback=fallback or LocalA1Credentials()
    def row(self,conn,cid):
        return conn.execute('SELECT * FROM operations WHERE company_id=? AND scope=? AND key=?',(cid,SCOPE,'a1')).fetchone()
    def revision(self,conn,cid):
        row=self.row(conn,cid)
        return row['request_hash'] if row else None
    def access(self,conn,cid,uid,write=False):
        company=company_row(conn,cid)
        require(conn,uid,cid,'system.companies','edit' if write else 'read')
        return company
    def public(self,row):
        if not row:return {'version':0,'configured':False,'environments':{},'allow_adn_procuration':False}
        data=json.loads(row['result_json'])
        return {k:data[k] for k in ('version','configured','environments','allow_adn_procuration','holder_cnpj','updated_at')}
    def status(self,cid,uid):
        with self.db.read() as conn:
            self.access(conn,cid,uid)
            return self.public(self.row(conn,cid))
    def key_root(self):
        configured=self.directory or os.environ.get('ESCRITURA_RECEPTION_VAULT_DIR')
        if configured:root=Path(configured).expanduser()
        elif os.name=='nt':root=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'Codisplan/EscrituraSecrets'
        elif sys.platform=='darwin':root=Path.home()/'Library/Application Support/Codisplan/EscrituraSecrets'
        else:root=Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))/'escritura-integrada/reception-secrets'
        if not root.is_absolute() or root.resolve().is_relative_to(self.db.data_dir.resolve()):unavailable()
        return root
    def key(self,installation,create=False):
        if not isinstance(installation,str) or len(installation)!=32 or any(c not in '0123456789abcdef' for c in installation):unavailable()
        try:
            root=self.key_root()
            if create:root.mkdir(mode=0o700,parents=True,exist_ok=True)
            info=root.lstat()
            if backup_platform.reparse(root) or not stat.S_ISDIR(info.st_mode) or (os.name!='nt' and (info.st_uid!=os.getuid() or info.st_mode&0o077)):unavailable()
            path=root/(installation+'.key')
            if create and not path.exists():
                raw=secrets.token_bytes(32)
                stored=dpapi(raw,True) if os.name=='nt' else raw
                try:
                    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
                    with os.fdopen(descriptor,'wb') as output:
                        output.write(stored);output.flush();os.fsync(output.fileno())
                except FileExistsError:pass
            if backup_platform.reparse(path):unavailable()
            raw=_private_file(path,16384)
            result=dpapi(raw,False) if os.name=='nt' else raw
            if len(result)!=32:unavailable()
            return result
        except (OSError,ValueError,DomainError):unavailable()
    def cipher(self,key,nonce,installation,cid,tax_id,version):
        try:from Cryptodome.Cipher import AES
        except ImportError:raise DomainError('Runtime do cofre A1 incompleto. Confira a instalação.',503,'reception_dependency_missing') from None
        cipher=AES.new(key,AES.MODE_GCM,nonce=nonce,mac_len=16)
        cipher.update(pack({'scope':SCOPE,'installation':installation,'company':cid,'tax_id':tax_id,'version':version}).encode())
        return cipher
    def decrypt(self,company,row,meta):
        try:
            data=json.loads(row['result_json']);installation=meta['value']
            cipher=self.cipher(self.key(installation),base64.b64decode(data['nonce'],validate=True),installation,company['id'],company['tax_id'],data['version'])
            secret=json.loads(cipher.decrypt_and_verify(base64.b64decode(data['ciphertext'],validate=True),base64.b64decode(data['tag'],validate=True)))
            if secret['tax_id']!=company['tax_id']:unavailable()
            return secret
        except DomainError:raise
        except (KeyError,TypeError,ValueError):unavailable()
    def save(self,cid,uid,actor,raw,password,options):
        if not isinstance(raw,bytes) or not 0<len(raw)<=5000000:raise DomainError('Selecione PFX/P12 de até 5 MB.',413,'reception_certificate_size')
        if not isinstance(password,str) or len(password)>4096 or '\0' in password:raise DomainError('Senha de proteção do A1 inválida.')
        if not isinstance(options,dict) or set(options)!={'version','environments','allow_adn_procuration'} or type(options['version']) is not int or type(options['allow_adn_procuration']) is not bool:raise DomainError('Parâmetros A1 inválidos.')
        envs=options['environments']
        if not isinstance(envs,dict) or not envs or set(envs)-set(ENVS):raise DomainError('Selecione serviço e ambiente para este A1.')
        for provider,values in envs.items():
            if not isinstance(values,list) or not values or any(not isinstance(e,str) or e not in ENVS[provider] for e in values) or len(values)!=len(set(values)):raise DomainError('Ambiente A1 inválido.')
        with self.db.read() as conn:
            company=self.access(conn,cid,uid,True)
            old=self.public(self.row(conn,cid))
        if old['version']!=options['version']:raise DomainError('O A1 mudou. Recarregue o cadastro.',409,'stale_version')
        holder=None
        for provider,values in envs.items():
            for environment in values:
                identity=load_a1(raw,password,company['tax_id'],provider,environment,options['allow_adn_procuration'])
                if holder and identity.tax_id!=holder:unavailable()
                holder=identity.tax_id
        with self.db.transaction() as conn:
            current=self.access(conn,cid,uid,True)
            if current['tax_id']!=company['tax_id']:raise DomainError('CNPJ alterado. Reabra a configuração.',409,'stale_company')
            if self.public(self.row(conn,cid))['version']!=options['version']:raise DomainError('O A1 mudou. Recarregue o cadastro.',409,'stale_version')
            meta=conn.execute("SELECT value FROM meta WHERE key='reception_vault_id'").fetchone()
            installation=meta['value'] if meta else uuid.uuid4().hex
            key=self.key(installation,create=not bool(meta))
            if not meta:conn.execute('INSERT INTO meta(key,value) VALUES(?,?)',('reception_vault_id',installation))
            version=options['version']+1;nonce=secrets.token_bytes(12)
            cipher=self.cipher(key,nonce,installation,cid,current['tax_id'],version)
            ciphertext,tag=cipher.encrypt_and_digest(pack({'pfx':base64.b64encode(raw).decode(),'password':password,'tax_id':current['tax_id'],'environments':envs,'allow_adn_procuration':options['allow_adn_procuration']}).encode())
            result=dict(version=version,configured=True,holder_cnpj=holder,updated_at=now(),environments=envs,allow_adn_procuration=options['allow_adn_procuration'],nonce=base64.b64encode(nonce).decode(),tag=base64.b64encode(tag).decode(),ciphertext=base64.b64encode(ciphertext).decode())
            conn.execute('''INSERT INTO operations(company_id,scope,key,request_hash,result_json,created_at) VALUES(?,?,?,?,?,?)
                ON CONFLICT(company_id,scope,key) DO UPDATE SET request_hash=excluded.request_hash,result_json=excluded.result_json''',(cid,SCOPE,'a1',digest({'version':version,'nonce':result['nonce']}),pack(result),now()))
            public=self.public({'result_json':pack(result)})
            audit(conn,cid,actor,'configure','reception-a1',cid,public)
            return public
    def update(self,cid,uid,actor,options):
        with self.db.read() as conn:
            company=self.access(conn,cid,uid,True);row=self.row(conn,cid)
            meta=conn.execute("SELECT value FROM meta WHERE key='reception_vault_id'").fetchone()
        if not row:raise DomainError('Cadastre o A1 primeiro.',409,'reception_not_configured')
        secret=self.decrypt(company,row,meta)
        return self.save(cid,uid,actor,base64.b64decode(secret['pfx'],validate=True),secret['password'],options)
    def load(self,cid,target,provider,environment):
        target=query_cnpj(target,provider)
        with self.db.read() as conn:
            company=company_row(conn,cid);row=self.row(conn,cid)
            meta=conn.execute("SELECT value FROM meta WHERE key='reception_vault_id'").fetchone()
        if not row:return self.fallback.load(cid,target,provider,environment)
        secret=self.decrypt(company,row,meta)
        if target!=company['tax_id']:unavailable()
        if environment not in secret['environments'].get(provider,[]):raise DomainError('Ambiente não habilitado no A1 desta empresa.',409,'reception_environment_disabled')
        return load_a1(base64.b64decode(secret['pfx'],validate=True),secret['password'],target,provider,environment,secret['allow_adn_procuration'])
