"""Permissões por empresa, com revogação aplicada também dentro da transação."""
from .core import DomainError, audit, boolean, company_row, integer, now, text

class AccessMixin:
    def users(self):
        with self.db.read() as conn:
            return [dict(r)|{'company_ids':[x[0] for x in conn.execute('SELECT company_id FROM user_companies WHERE user_id=?',(r['id'],))]} for r in conn.execute('SELECT id,username,role,active FROM users ORDER BY username')]

    def save_user(self,payload,actor,item_id=None):
        username=text(payload.get('username'),'Usuário',True,100)
        role=payload.get('role','viewer');active=boolean(payload.get('active'),True)
        ids=payload.get('company_ids',[])
        if role not in {'admin','operator','viewer'} or not isinstance(ids,list) or len(ids)!=len(set(ids)):
            raise DomainError('Perfil ou empresas inválidos.')
        password=text(payload.get('password'),'Senha',not bool(item_id),256)
        if password and len(password)<12:raise DomainError('Use senha com pelo menos 12 caracteres.')
        hashed=self._password_hash(password) if password else None
        with self.db.transaction() as conn:
            for cid in ids:company_row(conn,integer(cid,'Empresa'))
            old=conn.execute('SELECT * FROM users WHERE id=?',(item_id,)).fetchone() if item_id else None
            if item_id and not old:raise DomainError('Usuário não encontrado.',404)
            if old and old['username']==actor and (not active or role!='admin'):
                raise DomainError('Não remova seu próprio acesso administrativo.')
            if old:
                conn.execute('UPDATE users SET username=?,role=?,active=? WHERE id=?',(username,role,active,item_id))
                if hashed:conn.execute('UPDATE users SET password_hash=? WHERE id=?',(hashed,item_id))
                conn.execute('DELETE FROM sessions WHERE user_id=?',(item_id,))
                conn.execute('DELETE FROM user_companies WHERE user_id=?',(item_id,))
            else:item_id=conn.execute('INSERT INTO users(username,password_hash,created_at,role,active) VALUES(?,?,?,?,?)',(username,hashed,now(),role,active)).lastrowid
            for cid in ids:conn.execute('INSERT INTO user_companies VALUES(?,?)',(item_id,cid))
            audit(conn,None,actor,'update' if old else 'create','user',item_id,{'username':username,'role':role,'company_ids':ids,'active':active})
            return {'id':item_id,'username':username,'role':role,'active':active,'company_ids':ids}

    def authorize(self,user,cid=None,write=False,admin=False):
        with self.db.read() as conn:
            current=conn.execute('SELECT role,active FROM users WHERE id=?',(user['id'],)).fetchone()
            if not current or not current['active']:raise DomainError('Acesso desativado.',403,'forbidden')
            if admin and current['role']!='admin':raise DomainError('Ação reservada ao administrador.',403,'forbidden')
            if write and current['role']=='viewer':raise DomainError('Seu perfil permite somente consulta.',403,'forbidden')
            if cid is not None and current['role']!='admin' and not conn.execute('SELECT 1 FROM user_companies WHERE user_id=? AND company_id=?',(user['id'],cid)).fetchone():
                raise DomainError('Sem permissão para esta empresa.',403,'forbidden')
