"""Cadastros por empresa e modelos revisáveis, sem enquadramento fiscal presumido."""
import json
import re
from .core import (DomainError, audit, boolean, check_version, company_row, integer,
                   iso_date, json_value, money, normalize_cnpj, now, pack, select_one, text, digest)

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
    from .third_parties import registration_values
    result['state_registrations'] = registration_values(p.get('state_registrations', []))
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
                if payload.get('active') is not False and conn.execute('SELECT 1 FROM third_party_replacements WHERE company_id=? AND master_id=?', (cid, item_id)).fetchone():
                    raise DomainError('Cadastro substituído; utilize o cadastro correto indicado no histórico.', 409, 'already_replaced')
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
                    from .account_refs import resolve_account
                    account = resolve_account(conn,cid,data[k],materialize=True,actor=actor)
                    data[k]=account['id']
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
            from .third_parties import sync_third_party
            sync_third_party(conn, cid, item_id, actor, 'Cadastro local revisado explicitamente.')
            audit(conn,cid,actor,'update' if old else 'create',kind,item_id,{'before':old,'after':payload})
            return self._master(conn,cid,item_id)

    def _import_document_masters(self, conn, cid, payload, actor):
        """Link XML identities in the document transaction, never by display name.

        Supplier item codes are scoped to their issuer, not to the buyer's SKU.
        Existing reviewed descriptions/tax settings are never overwritten.
        """
        if not payload.get('source_hash') or not isinstance(payload.get('issuer'), dict):
            return payload
        payload = dict(payload)
        company = company_row(conn, cid)
        warnings = []

        def allowed(action):
            from .permissions import effect
            try:
                effect(conn, cid, 'fiscal.masters', action)
            except DomainError as exc:
                if exc.status != 403:
                    raise
                warnings.append('Sem permissão para ' + ('criar cadastros' if action == 'create' else 'atualizar papéis de participantes') + '; dados de origem preservados no documento.')
                return False
            return True

        def insert(kind, code, name, tax_id, data):
            if not allowed('create'):
                return None
            # Generated technical codes must not collide with user-entered codes.
            initial, suffix = code, 0
            while conn.execute('SELECT 1 FROM masters WHERE company_id=? AND kind=? AND code=?',
                               (cid, kind, code)).fetchone():
                suffix += 1
                code = initial[:40] + '-' + str(suffix)
            stamp = now()
            mid = conn.execute(
                'INSERT INTO masters(company_id,kind,code,name,tax_id,data_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                (cid, kind, code, name, tax_id, pack(data), stamp, stamp)).lastrowid
            from .third_parties import sync_third_party
            sync_third_party(conn, cid, mid, actor, 'Identidade vinculada pela importação; origem local preservada.')
            audit(conn, cid, actor, 'create', kind, mid,
                  {'source': payload.get('source'), 'source_hash': payload['source_hash'], 'imported': True})
            return mid

        def participant(party, role):
            if not isinstance(party, dict) or not party.get('tax_id'):
                return None  # Anonymous consumers do not become fictitious masters.
            try:
                identity = tax_identity(party['tax_id'])
            except DomainError:
                warnings.append('CPF/CNPJ inválido na origem; participante não cadastrado automaticamente.')
                return None
            if identity == company['tax_id']:
                return None
            row = conn.execute("SELECT * FROM masters WHERE company_id=? AND kind='participant' AND tax_id=?",
                               (cid, identity)).fetchone()
            if row:
                if not row['active']:
                    warnings.append('Participante existente inativo; vínculo automático não realizado.')
                    return None
                data = json.loads(row['data_json'])
                roles = data.get('roles', [])
                if role not in roles and allowed('edit'):
                    data['roles'] = sorted(set(roles + [role]))
                    conn.execute('UPDATE masters SET data_json=?,updated_at=?,version=version+1 WHERE company_id=? AND id=?',
                                 (pack(data), now(), cid, row['id']))
                    from .third_parties import sync_third_party
                    sync_third_party(conn, cid, row['id'], actor, 'Função local acrescentada pela importação autorizada.')
                    audit(conn, cid, actor, 'update', 'participant', row['id'], {'added_role': role, 'source_hash': payload['source_hash']})
                return row['id']
            name = str(party.get('name') or '').strip()
            if not name:
                warnings.append('Participante identificado sem nome na origem; cadastro automático não realizado.')
                return None
            data = {k: party[k] for k in ('trade_name', 'address', 'number', 'district', 'city', 'state',
                    'postal_code', 'ibge', 'ie', 'im', 'email', 'phone') if party.get(k)}
            data.update(roles=[role], profile=profile_values(None), import_source=payload.get('source'))
            return insert('participant', 'XML-' + identity, name, identity, data)

        partner_tax_id = payload.get('partner_tax_id')
        parties = [payload.get('issuer', {}), payload.get('recipient', {})]
        transport = payload.get('transport') or {}
        if isinstance(transport, dict):
            parties.append(transport.get('taker') or {})
        party = next((p for p in parties if p.get('tax_id') == partner_tax_id and partner_tax_id),
                     {'tax_id': partner_tax_id, 'name': payload.get('partner_name')})
        role = 'supplier' if payload.get('direction') in {'incoming', 'entrada'} else 'customer'
        participant_id = participant(party, role)
        if participant_id and not payload.get('participant_id'):
            payload['participant_id'] = participant_id
        carrier = transport.get('carrier') if isinstance(transport, dict) else None
        if payload.get('document_type') == 'transport':
            carrier = payload.get('issuer')
        carrier_id = participant(carrier, 'carrier')
        if carrier_id:
            payload['carrier_id'] = carrier_id

        issuer = payload['issuer'].get('tax_id') or payload['issuer'].get('foreign_id')
        linked_items = []
        catalog_index = {}
        for item in payload.get('items', []):
            item = dict(item)
            tax_fields = item.get('taxes') if isinstance(item.get('taxes'), dict) else {}
            # Mixed NF-e can declare services per item. Use the actual ISSQN
            # source group, never CFOP or description as a tax/type guess.
            issqn = any(str(key).startswith('ISSQN/') for key in tax_fields)
            icms = any(str(key).startswith('ICMS/') for key in tax_fields)
            explicit_service = payload.get('document_type') in {'service', 'transport'}
            if not item.get('master_id') and issqn and icms and not explicit_service:
                warnings.append(f"Item {item.get('number', '?')}: grupos ICMS e ISSQN simultâneos; cadastro automático pendente de revisão.")
                linked_items.append(item)
                continue
            kind = 'service' if explicit_service or issqn else 'product'
            code = str(item.get('code') or '').strip()
            name = str(item.get('description') or '').strip()
            if not item.get('master_id') and issuer and code and name:
                identity = {'issuer': issuer, 'code': code}
                if kind not in catalog_index:
                    catalog_index[kind] = {}
                    for row in conn.execute('SELECT * FROM masters WHERE company_id=? AND kind=?', (cid, kind)):
                        origin = json.loads(row['data_json']).get('import_identity')
                        if isinstance(origin, dict):
                            catalog_index[kind][pack(origin)] = row
                found = catalog_index[kind].get(pack(identity))
                if found and found['active']:
                    item['master_id'] = found['id']
                elif found:
                    warnings.append('Produto/serviço existente inativo; vínculo automático não realizado.')
                else:
                    data = {k: item[k] for k in ('unit', 'ncm', 'cest', 'service_code', 'barcode') if item.get(k)}
                    if kind == 'service' and not data.get('service_code') and tax_fields.get('ISSQN/cListServ'):
                        data['service_code'] = str(tax_fields['ISSQN/cListServ']).strip()
                    data.update(import_identity=identity, import_source=payload.get('source'))
                    # Source CFOP/CST and invoice prices are not master defaults.
                    master_id = insert(kind, 'XML-' + digest(identity)[:40], name, '', data)
                    if master_id:
                        item['master_id'] = master_id
                        catalog_index[kind][pack(identity)] = {'id': master_id, 'active': True}
            linked_items.append(item)
        payload['items'] = linked_items
        if warnings:
            payload['master_import_warnings'] = list(dict.fromkeys(warnings))
        return payload

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
