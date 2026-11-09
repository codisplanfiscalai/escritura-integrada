"""Cadastros por empresa e modelos revisáveis, sem enquadramento fiscal presumido."""
import json
import re
from .core import (DomainError, audit, boolean, check_version, company_row, integer,
                   iso_date, json_value, money, normalize_cnpj, now, pack, select_one, text)

KINDS = {'participant', 'establishment', 'product', 'service', 'history', 'accounting_model'}
UFS = set('AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO EX'.split())


def profile_values(payload, previous=None):
    if payload is not None and not isinstance(payload,dict):
        raise DomainError("Perfil cadastral inválido.")
    p = dict(previous or {})
    p.update(payload or {})
    result = {k: text(p.get(k), k, False, 500) for k in
              ('legal_nature', 'registration_status', 'complement', 'lookup_source', 'lookup_date', 'notes')}
    state = p.get('ie_status', 'unknown')
    if state not in {'unknown', 'not_found', 'registered', 'exempt', 'not_applicable'}:
        raise DomainError('Situação da inscrição estadual inválida.')
    result['ie_status'] = state
    result['state_registrations'] = []
    regs = p.get('state_registrations', [])
    if not isinstance(regs, list) or len(regs) > 100:
        raise DomainError('Informe até 100 inscrições estaduais.')
    for r in regs:
        if not isinstance(r, dict):
            raise DomainError('Inscrição estadual inválida.')
        uf = text(r.get('state'), 'UF da IE', True, 2).upper()
        if uf not in UFS:
            raise DomainError('UF da inscrição estadual inválida.')
        result['state_registrations'].append({
            'state': uf, 'number': text(r.get('number'), 'Inscrição estadual', True, 30),
            'active': r.get('active') if isinstance(r.get('active'), bool) else None,
            'source': text(r.get('source'), 'Fonte da IE', False, 100),
            'updated_at': text(r.get('updated_at'), 'Atualização da IE', False, 100)})
    cnaes = p.get('secondary_cnaes', [])
    if not isinstance(cnaes, list) or len(cnaes) > 200:
        raise DomainError('CNAEs secundários inválidos.')
    result['secondary_cnaes'] = []
    for c in cnaes:
        code = re.sub(r'[.\-/ ]', '', str(c))
        if not re.fullmatch(r'\d{7}', code):
            raise DomainError('CNAE secundário deve conter sete dígitos.')
        result['secondary_cnaes'].append(code)
    return result


def tax_identity(value):
    value = re.sub(r'[.\-/\s]', '', text(value, 'CPF/CNPJ', False, 30)).upper()
    if not value:
        return ''
    if len(value) == 14:
        return normalize_cnpj(value)
    if not re.fullmatch(r'\d{11}', value) or len(set(value)) == 1:
        raise DomainError('CPF/CNPJ inválido.')
    for n in (9, 10):
        d = (sum(int(v)*w for v, w in zip(value[:n], range(n+1, 1, -1))) * 10) % 11
        if str(0 if d == 10 else d) != value[n]:
            raise DomainError('Dígitos verificadores do CPF inválidos.')
    return value


class CadastrosMixin:
    def _master(self, conn, cid, item_id, kind=None, active=False):
        r = select_one(conn, 'masters', cid, item_id)
        if kind and r['kind'] != kind:
            raise DomainError('Tipo de cadastro incompatível.')
        if active and not r['active']:
            raise DomainError('Cadastro inativo; selecione um registro ativo.')
        r['data'] = json.loads(r.pop('data_json'))
        r['active'] = bool(r['active'])
        return r

    def masters(self, cid, kind):
        if kind not in KINDS:
            raise DomainError('Cadastro não encontrado.', 404)
        with self.db.read() as conn:
            company_row(conn, cid)
            return [self._master(conn, cid, r['id']) for r in conn.execute(
                'SELECT id FROM masters WHERE company_id=? AND kind=? ORDER BY code', (cid, kind))]

    def save_master(self, cid, kind, payload, actor, item_id=None):
        if kind not in KINDS:
            raise DomainError('Cadastro não encontrado.', 404)
        with self.db.transaction() as conn:
            company = company_row(conn, cid)
            old = self._master(conn, cid, item_id, kind) if item_id else None
            if old:
                check_version(old, payload)
            code = text(payload.get('code'), 'Código', True, 50)
            name = text(payload.get('name'), 'Nome', True, 250)
            active = boolean(payload.get('active'), True)
            data = payload.get('data', {})
            json_value(data, dict, 'Dados cadastrais')
            data = dict(data)
            tax_id = tax_identity(payload.get('tax_id')) if kind in {'participant', 'establishment'} else ''
            if kind in {'participant', 'establishment'}:
                data['profile'] = profile_values(data.get('profile'))
                for k in ('trade_name', 'address', 'number', 'district', 'city', 'state', 'postal_code',
                          'ibge', 'ie', 'im', 'cnae', 'email', 'phone', 'prosoft_code'):
                    data[k] = text(data.get(k), k, False, 500)
                if data['state'] and data['state'] not in UFS:
                    raise DomainError('UF inválida.')
                for k, n in [('postal_code', 8), ('ibge', 7), ('cnae', 7)]:
                    data[k] = re.sub(r'[.\-/ ]', '', data[k])
                    if data[k] and not re.fullmatch(rf'\d{{{n}}}', data[k]):
                        raise DomainError(f'{k}: informe {n} dígitos.')
                roles = data.get('roles', ['customer', 'supplier'])
                if not isinstance(roles, list) or any(not isinstance(x,str) for x in roles) or not set(roles) <= {'customer','supplier','carrier','other'}:
                    raise DomainError('Papel do participante inválido.')
                data['roles'] = roles
                if kind == 'establishment' and (len(tax_id) != 14 or tax_id[:8] != company['tax_id'][:8]):
                    raise DomainError('Estabelecimento deve ter a mesma raiz do CNPJ da empresa.')
                if old and old['tax_id'] != tax_id:
                    raise DomainError('A identidade de um participante/estabelecimento é preservada. Crie outro cadastro para outro CPF/CNPJ.')
            if kind in {'product','service'}:
                for k in ('unit','ncm','cfop','service_code','cst','cclass_trib','barcode'):
                    data[k] = text(data.get(k), k, False, 100)
                for k,n in [('ncm',8),('cfop',4)]:
                    if data[k] and not re.fullmatch(rf'\d{{{n}}}',data[k]):
                        raise DomainError(f'{k.upper()}: informe {n} dígitos.')
                data['price'] = str(data.get('price') or '0.00')
                money(data['price'], 'Preço')
            if kind == 'history':
                data = {'text': text(data.get('text'), 'Histórico', True, 2000)}
            if kind == 'accounting_model':
                data = {k: data.get(k) for k in ('debit_account_id','credit_account_id','cost_center_id',
                         'valid_from','valid_to','history','direction','status','source','responsible')}
                for k in ('debit_account_id','credit_account_id'):
                    account = select_one(conn,'accounts',cid,integer(data[k],'Conta'))
                    if not account['active'] or not account['analytical']:
                        raise DomainError('Modelo exige contas analíticas ativas.')
                if data['debit_account_id'] == data['credit_account_id']:
                    raise DomainError('Selecione contas diferentes para débito e crédito.')
                if data['cost_center_id']:
                    select_one(conn,'cost_centers',cid,integer(data['cost_center_id'],'Centro'))
                else:
                    data['cost_center_id'] = None
                data['valid_from'] = iso_date(data.get('valid_from'),'Início da vigência')
                data['valid_to'] = iso_date(data['valid_to']) if data.get('valid_to') else ''
                if data['valid_to'] and data['valid_to'] < data['valid_from']:
                    raise DomainError('Fim da vigência anterior ao início.')
                data['status'] = data.get('status') or 'draft'
                data['direction'] = data.get('direction') or 'both'
                if data['status'] not in {'draft','validated'} or data['direction'] not in {'both','incoming','outgoing'}:
                    raise DomainError('Status ou direção do modelo inválido.')
                for k in ('history','source','responsible'):
                    data[k] = text(data.get(k),k,data['status']=='validated',1000)
            values = (code,name,tax_id,pack(data),active,now())
            if old:
                conn.execute('UPDATE masters SET code=?,name=?,tax_id=?,data_json=?,active=?,updated_at=?,version=version+1 WHERE id=? AND company_id=?',(*values,item_id,cid))
            else:
                item_id = conn.execute('INSERT INTO masters(code,name,tax_id,data_json,active,updated_at,company_id,kind,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(*values,cid,kind,now())).lastrowid
            audit(conn,cid,actor,'update' if old else 'create',kind,item_id,{'before':old,'after':payload})
            return self._master(conn,cid,item_id)

    def _model_lines(self,conn,cid,item_id,doc):
        model = self._master(conn,cid,integer(item_id,'Modelo'),'accounting_model',True)
        m = model['data']
        if m['status'] != 'validated' or not m['valid_from'] <= doc['posting_date'] or (m['valid_to'] and doc['posting_date'] > m['valid_to']):
            raise DomainError('Modelo não revisado ou fora da vigência.')
        if m['direction'] not in {'both',doc['direction']}:
            raise DomainError('Sentido do modelo incompatível com o documento.')
        from .core import decimal_text
        value = decimal_text(doc['total_cents'])
        return [{'account_id':m['debit_account_id'],'debit':value,'credit':'0.00','cost_center_id':m['cost_center_id']},
                {'account_id':m['credit_account_id'],'debit':'0.00','credit':value,'cost_center_id':m['cost_center_id']}]
