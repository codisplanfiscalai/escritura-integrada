"""Grupos, concessões pessoais e explicação das permissões efetivas."""
from .core import DomainError, audit, boolean, check_version, company_row, integer, now, text
from .permissions import ACTIONS, MODULES, ROUTINES, catalog, company_access, decision, require


def ids_list(value,label):
    if not isinstance(value,list) or len(value)>1000:
        raise DomainError(label+' deve ser uma lista de até 1000 identificadores.')
    values=[integer(i,label) for i in value]
    if len(values)!=len(set(values)):raise DomainError(label+' contém duplicidade.')
    return values


def normalize_permissions(value):
    if not isinstance(value,list) or len(value)>5000:raise DomainError('Informe até 5000 permissões.')
    result=[];seen=set()
    for row in value:
        if not isinstance(row,dict):raise DomainError('Permissão inválida.')
        cid=integer(row.get('company_id'),'Empresa');routine=row.get('routine');action=row.get('action');effect=row.get('effect')
        valid=routine in ROUTINES or routine=='*' or routine in {m+'.*' for m in MODULES}
        if not valid or action not in {*ACTIONS,'*'} or effect not in {'allow','deny'}:
            raise DomainError('Rotina, ação ou efeito de permissão inválido.')
        if routine in ROUTINES and action!='*' and action not in ROUTINES[routine][1].split():
            raise DomainError('Ação indisponível nessa rotina.')
        key=(cid,routine,action)
        if key in seen:raise DomainError('Permissão repetida. Use uma única decisão por empresa, rotina e ação.')
        seen.add(key);result.append({'company_id':cid,'routine':routine,'action':action,'effect':effect})
    return result


class AccessMixin:
    def _user(self,conn,uid):
        r=conn.execute('SELECT id,username,role,active,version FROM users WHERE id=?',(uid,)).fetchone()
        if not r:raise DomainError('Usuário não encontrado.',404)
        return dict(r)|{'active':bool(r['active']),
            'company_ids':[x[0] for x in conn.execute('SELECT company_id FROM user_companies WHERE user_id=?',(uid,))],
            'group_ids':[x[0] for x in conn.execute('SELECT group_id FROM group_users WHERE user_id=?',(uid,))],
            'company_access':[dict(x) for x in conn.execute('SELECT company_id,effect FROM user_company_access WHERE user_id=?',(uid,))],
            'permissions':[dict(x) for x in conn.execute('SELECT company_id,routine,action,effect FROM user_permissions WHERE user_id=?',(uid,))]}

    def users(self):
        with self.db.read() as conn:return [self._user(conn,r[0]) for r in conn.execute('SELECT id FROM users ORDER BY username')]

    def save_user(self,payload,actor,item_id=None):
        username=text(payload.get('username'),'Usuário',True,100)
        role=payload.get('role','custom');active=boolean(payload.get('active'),True)
        if role not in {'admin','operator','viewer','custom'}:raise DomainError('Perfil inválido.')
        ids=ids_list(payload.get('company_ids',[]),'Empresas');groups=ids_list(payload.get('group_ids',[]),'Grupos')
        password=text(payload.get('password'),'Senha',not bool(item_id),256)
        if password and len(password)<12:raise DomainError('Use senha com pelo menos 12 caracteres.')
        hashed=self._password_hash(password) if password else None
        permissions=normalize_permissions(payload.get('permissions',[]))
        overrides=payload.get('company_access',[])
        if not isinstance(overrides,list) or len(overrides)>1000:raise DomainError('Exceções de empresa inválidas.')
        company_rules={}
        for row in overrides:
            cid=integer(row.get('company_id'),'Empresa')
            if cid in company_rules or row.get('effect') not in {'allow','deny'}:raise DomainError('Exceção de empresa inválida ou repetida.')
            company_rules[cid]=row['effect']
        with self.db.transaction() as conn:
            old=self._user(conn,item_id) if item_id else None
            if old:
                check_version(old,payload)
                if old['username']==actor and (not active or role!='admin'):
                    raise DomainError('Não remova seu próprio acesso administrativo.')
            for cid in {*ids,*company_rules,*(p['company_id'] for p in permissions)}:company_row(conn,cid)
            for gid in groups:
                if not conn.execute('SELECT 1 FROM access_groups WHERE id=?',(gid,)).fetchone():raise DomainError('Grupo não encontrado.')
            # Contrato antigo: o perfil escolhido é convertido em concessões explícitas.
            if 'permissions' not in payload and role in {'operator','viewer'}:
                permissions=[{'company_id':cid,'routine':r,'action':a,'effect':'allow'} for cid in ids
                    for r,(_,actions) in ROUTINES.items() for a in actions.split() if role=='operator' or a in {'read','export','print'}]
            if old:
                conn.execute('UPDATE users SET username=?,role=?,active=?,version=version+1 WHERE id=?',(username,role,active,item_id))
                if hashed:conn.execute('UPDATE users SET password_hash=? WHERE id=?',(hashed,item_id))
                conn.execute('DELETE FROM sessions WHERE user_id=?',(item_id,))
                for table in ('user_companies','group_users','user_company_access','user_permissions'):
                    conn.execute('DELETE FROM '+table+' WHERE user_id=?',(item_id,))
            else:
                item_id=conn.execute('INSERT INTO users(username,password_hash,created_at,role,active) VALUES(?,?,?,?,?)',(username,hashed,now(),role,active)).lastrowid
            for cid in ids:conn.execute('INSERT INTO user_companies VALUES(?,?)',(item_id,cid))
            for gid in groups:conn.execute('INSERT INTO group_users VALUES(?,?)',(gid,item_id))
            for cid,effect in company_rules.items():conn.execute('INSERT INTO user_company_access VALUES(?,?,?)',(item_id,cid,effect))
            for p in permissions:conn.execute('INSERT INTO user_permissions VALUES(?,?,?,?,?)',(item_id,p['company_id'],p['routine'],p['action'],p['effect']))
            result=self._user(conn,item_id)
            audit(conn,None,actor,'update' if old else 'create','user',item_id,{'before':old,'after':result,'password_changed':bool(hashed)})
            return result

    def _group(self,conn,gid):
        row=conn.execute('SELECT * FROM access_groups WHERE id=?',(gid,)).fetchone()
        if not row:raise DomainError('Grupo não encontrado.',404)
        return dict(row)|{'active':bool(row['active']),'company_ids':[r[0] for r in conn.execute('SELECT company_id FROM group_companies WHERE group_id=?',(gid,))],
            'user_ids':[r[0] for r in conn.execute('SELECT user_id FROM group_users WHERE group_id=?',(gid,))],
            'permissions':[dict(r) for r in conn.execute('SELECT company_id,routine,action,effect FROM group_permissions WHERE group_id=?',(gid,))]}

    def groups(self):
        with self.db.read() as conn:return [self._group(conn,r[0]) for r in conn.execute('SELECT id FROM access_groups ORDER BY name')]

    def save_group(self,payload,actor,item_id=None):
        name=text(payload.get('name'),'Nome do grupo',True,100);description=text(payload.get('description'),'Descrição',False,500)
        active=boolean(payload.get('active'),True);companies=ids_list(payload.get('company_ids',[]),'Empresas');users=ids_list(payload.get('user_ids',[]),'Usuários')
        permissions=normalize_permissions(payload.get('permissions',[]))
        if any(p['company_id'] not in companies for p in permissions):raise DomainError('A permissão deve pertencer a uma empresa concedida ao grupo.')
        with self.db.transaction() as conn:
            old=self._group(conn,item_id) if item_id else None
            if old:check_version(old,payload)
            for cid in companies:company_row(conn,cid)
            for uid in users:self._user(conn,uid)
            if old:
                conn.execute('UPDATE access_groups SET name=?,description=?,active=?,version=version+1,updated_at=? WHERE id=?',(name,description,active,now(),item_id))
                for table in ('group_companies','group_users','group_permissions'):conn.execute('DELETE FROM '+table+' WHERE group_id=?',(item_id,))
            else:item_id=conn.execute('INSERT INTO access_groups(name,description,active,created_at,updated_at) VALUES(?,?,?,?,?)',(name,description,active,now(),now())).lastrowid
            for cid in companies:conn.execute('INSERT INTO group_companies VALUES(?,?)',(item_id,cid))
            for uid in users:conn.execute('INSERT INTO group_users VALUES(?,?)',(item_id,uid))
            for p in permissions:conn.execute('INSERT INTO group_permissions VALUES(?,?,?,?,?)',(item_id,p['company_id'],p['routine'],p['action'],p['effect']))
            affected=set(users)|set(old['user_ids'] if old else [])
            for uid in affected:
                conn.execute('UPDATE users SET version=version+1 WHERE id=?',(uid,))
                conn.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
            result=self._group(conn,item_id)
            audit(conn,None,actor,'update' if old else 'create','group',item_id,{'before':old,'after':result})
            return result

    def allowed_companies(self,uid):
        with self.db.read() as conn:return [r[0] for r in conn.execute('SELECT id FROM companies') if company_access(conn,uid,r[0])[0]]

    def effective_access(self,uid):
        with self.db.read(snapshot=True) as conn:
            user=self._user(conn,uid);companies=[]
            for c in conn.execute('SELECT id,code,name FROM companies ORDER BY code'):
                allowed,origins=company_access(conn,uid,c['id'])
                routines=[]
                for routine,(name,actions) in ROUTINES.items():
                    routines.append({'id':routine,'name':name,'module':routine.split('.')[0],
                        'actions':{a:decision(conn,uid,c['id'],routine,a) for a in actions.split()}})
                companies.append(dict(c)|{'allowed':allowed,'origins':origins,'routines':routines})
            return {'user':user,'companies':companies,'policy':catalog()['precedence']}

    def authorize(self,user,cid=None,write=False,admin=False,routine=None,action='read'):
        with self.db.read() as conn:
            # Compatibilidade da assinatura; rotas novas sempre informam rotina/ação.
            require(conn,user['id'],cid,routine,action,admin)
            if write and routine is None and user['role']=='viewer':raise DomainError('Seu perfil permite somente consulta.',403,'forbidden')
