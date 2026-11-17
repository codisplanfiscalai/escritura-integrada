"""Versioned, company-scoped destination mappings; never writes accounting data."""
import json
import re
from .core import DomainError, audit, company_row, now, pack
from .account_refs import resolve_account
from .prosoft import numeric
from .prosoft_profiles import selected_types, valid_fiscal_species

KIND = 'prosoft_export_settings'


def settings_row(conn, cid, mode):
    if mode not in {'accounting', 'fiscal'}: raise DomainError('Perfil Prosoft inválido.')
    return conn.execute('SELECT * FROM masters WHERE company_id=? AND kind=? AND code=?', (cid, KIND, mode)).fetchone()


def defaults(company, mode):
    result = {'company_code': company['prosoft_code'] or '', 'plan_code': '0050', 'record_types': ['LC1','LC2'] if mode == 'accounting' else ['incoming_notes','outgoing_notes']}
    return result | ({'batch': '1', 'accounts': {}, 'centers': {}, 'participants': {}} if mode == 'accounting' else
                     {'species': {'55': {'code': '', 'confirmed': False}, '65': {'code': '', 'confirmed': False}}, 'cfop_accounts': {}})


def assert_settings_version(conn, cid, mode, payload):
    if 'settings_version' not in payload: return  # Legacy explicit API payloads remain valid.
    row = settings_row(conn, cid, mode)
    version = row['version'] if row else 0
    if type(payload['settings_version']) is not int or payload['settings_version'] != version:
        raise DomainError('Os mapeamentos Prosoft salvos mudaram. Recarregue e gere nova prévia.', 409, 'stale_settings')


def mapping_values(value, kind):
    if not isinstance(value, dict): raise DomainError('Mapeamento Prosoft inválido.')
    allowed = {'code', 'confirmed'} | ({'third_mode', 'third', 'third_type', 'create_account'} if kind == 'account' else
                                      {'third_type', 'create_third'} if kind == 'participant' else set())
    if set(value) - allowed: raise DomainError('Propriedade de mapeamento Prosoft desconhecida.')
    result = dict(value)
    code = result.get('code', '')
    confirmed = result.get('confirmed', False)
    if type(confirmed) is not bool or not isinstance(code, str): raise DomainError('Código e conferência do mapeamento inválidos.')
    pattern = '[A-Z0-9]{0,14}' if kind == 'participant' else '[0-9]{0,5}'
    valid_code = (code == '' or valid_fiscal_species(code)) if kind == 'species' else re.fullmatch(pattern, code)
    if not valid_code or (confirmed and not code): raise DomainError('Código do mapeamento fora do formato permitido.')
    if kind in {'account', 'center', 'cfop'} and code and int(code) == 0: raise DomainError('Acesso de destino deve ser maior que zero.')
    result.update(code=code, confirmed=confirmed)
    if kind == 'account':
        mode = result.get('third_mode', 'none')
        if not isinstance(mode, str) or mode not in {'none', 'optional', 'required'}: raise DomainError('Política de terceiros inválida.')
        third = result.get('third', '')
        if not isinstance(third, str) or not re.fullmatch('[A-Z0-9]{0,14}', third): raise DomainError('Terceiro fixo inválido.')
        result.update(third_mode=mode, third=third)
        registration = result.get('create_account')
        if registration is not None:
            allowed_cta = {'destination_missing','classifier','name','cost_center_mode','reconciliation','special_classifier','special_name'}
            if not isinstance(registration, dict) or set(registration) - allowed_cta: raise DomainError('Dados CTA inválidos.')
            if registration.get('destination_missing') is not True: raise DomainError('CTA exige conta ausente no destino.')
            for field, width in [('classifier',15), ('special_classifier',20)]:
                text = registration.get(field, '')
                if not isinstance(text, str) or (text and (not re.fullmatch('[0-9]+(?:\\.[0-9]+)*', text) or len(text.replace('.', '')) > width)):
                    raise DomainError('Classificador CTA inválido.')
            for field, width in [('name',30), ('special_name',80)]:
                text = registration.get(field, '')
                if not isinstance(text, str) or len(text) > width or any(ord(c) < 32 for c in text): raise DomainError('Texto CTA inválido.')
            if not isinstance(registration.get('cost_center_mode'), str) or not isinstance(registration.get('reconciliation'), str) or registration['cost_center_mode'] not in {'0','1','2','3'} or registration['reconciliation'] not in {'0','1'}:
                raise DomainError('Políticas CTA inválidas.')
    if kind in {'account', 'participant'}:
        third_type = result.get('third_type', 'normal')
        if not isinstance(third_type, str) or third_type not in {'normal', 'free'}: raise DomainError('Tipo de terceiro inválido.')
        result['third_type'] = third_type
    if kind == 'participant' and result.get('create_third') is not None:
        from .prosoft_trc import validate_registration
        validate_registration(result)
    return result


def reference_key(conn, cid, value):
    if not isinstance(value, str) or not re.fullmatch('-?[1-9][0-9]*', value): raise DomainError('Referência de conta inválida.')
    account = resolve_account(conn, cid, int(value))
    return str(-account['shared_entry_id'] if account['shared_entry_id'] else account['id']), str(account['id'])


def describe(conn, cid, mode):
    company = company_row(conn, cid)
    row = settings_row(conn, cid, mode)
    config = defaults(company, mode) | json.loads(row['data_json']) if row else defaults(company, mode)
    unavailable = {}
    if mode == 'accounting':
        resolved = {}
        for key, mapping in config['accounts'].items():
            try: _, current = reference_key(conn, cid, key)
            except DomainError as e:
                if e.code != 'account_reference_unavailable': raise
                unavailable[key] = mapping
                continue
            if current in resolved and resolved[current] != mapping:
                raise DomainError('Aliases de conta possuem mapeamentos salvos divergentes.', 409, 'account_mapping_conflict')
            resolved[current] = mapping
        config['accounts'] = resolved
    return {'company_id': cid, 'mode': mode, 'version': row['version'] if row else 0,
            'settings': config, 'unavailable_accounts': unavailable}


class ProsoftSettingsMixin:
    def prosoft_settings(self, cid, mode):
        with self.db.read(snapshot=True) as conn: return describe(conn, cid, mode)

    def save_prosoft_settings(self, cid, mode, payload, actor):
        from .permissions import effect
        with self.db.transaction() as conn:
            effect(conn, cid, mode + '.prosoft', 'edit')
            company = company_row(conn, cid)
            row = settings_row(conn, cid, mode)
            version = row['version'] if row else 0
            if type(payload.get('version')) is not int or payload['version'] != version:
                raise DomainError('Os mapeamentos mudaram. Recarregue antes de salvar.', 409, 'stale_version')
            config = payload.get('settings')
            allowed = defaults(company, mode)
            if not isinstance(config, dict) or set(config) - set(allowed): raise DomainError('Configuração Prosoft inválida.')
            config = allowed | config
            code = config['company_code']
            if not isinstance(code, str) or not re.fullmatch('[0-9]{0,4}', code) or (code and int(code) == 0): raise DomainError('Código de empresa Prosoft inválido.')
            config['record_types'] = selected_types(mode, config['record_types'])
            config['plan_code'] = numeric(config['plan_code'], 4, 'Plano no destino')
            if mode == 'accounting': config['batch'] = numeric(config['batch'], 5, 'Lote', True)
            for key, kind in ([('accounts','account'),('centers','center'),('participants','participant')] if mode == 'accounting' else [('species','species'),('cfop_accounts','cfop')]):
                values = config[key]
                if not isinstance(values, dict): raise DomainError('Mapeamentos devem ser objetos.')
                normalized = {}
                for reference, value in values.items():
                    canonical = reference
                    if kind == 'account': canonical, _ = reference_key(conn, cid, reference)
                    elif kind in {'center', 'participant'}:
                        if not re.fullmatch('[1-9][0-9]*', str(reference)): raise DomainError('Referência cadastral inválida.')
                        table = 'cost_centers' if kind == 'center' else 'masters'
                        existing = conn.execute('SELECT * FROM '+table+' WHERE company_id=? AND id=?', (cid, int(reference))).fetchone()
                        if not existing or kind == 'participant' and existing['kind'] != 'participant': raise DomainError('Cadastro não pertence à empresa.')
                    elif kind == 'species' and reference not in {'55', '65'}: raise DomainError('Modelo fiscal não coberto por este perfil.')
                    elif kind == 'cfop' and not re.fullmatch('[0-9]{4}', reference): raise DomainError('CFOP inválido.')
                    value = mapping_values(value, kind)
                    if canonical in normalized and normalized[canonical] != value: raise DomainError('Aliases com mapeamentos divergentes.',409,'account_mapping_conflict')
                    normalized[canonical] = value
                if kind == 'species': normalized = defaults(company, mode)['species'] | normalized
                config[key] = normalized
            # Keep unavailable historical mappings; never transfer by an access code match.
            if row and mode == 'accounting':
                for key, value in describe(conn, cid, mode)['unavailable_accounts'].items(): config['accounts'].setdefault(key, value)
            stamp = now()
            if row:
                conn.execute('UPDATE masters SET data_json=?,version=version+1,updated_at=? WHERE id=?', (pack(config), stamp, row['id']))
                item_id = row['id']
            else:
                item_id = conn.execute('INSERT INTO masters(company_id,kind,code,name,data_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                                       (cid,KIND,mode,'Mapeamentos Prosoft '+mode,pack(config),stamp,stamp)).lastrowid
            audit(conn,cid,actor,'configure','prosoft-settings',item_id,{'mode':mode,'version':version+1})
            return describe(conn,cid,mode)
