"""Optional minimal TRC legal-entity profile, CTBLCTOS PDF sheets 3–4.

Only mandatory, unambiguous PJ fields are emitted. CPF/free identities and the
ambiguous personal fields remain outside this profile. No destination lookup.
"""
import re
from .core import DomainError, digest, normalize_cnpj

PROFILE = 'TRC-PJ-646-minimal-v1'


def validate_registration(mapping):
    from .prosoft import ascii_field
    data = mapping.get('create_third')
    allowed = {'destination_missing', 'person_type', 'name', 'alias', 'state'}
    if not isinstance(data, dict) or set(data) - allowed:
        raise DomainError('Dados TRC PJ inválidos ou não suportados.')
    if data.get('destination_missing') is not True or data.get('person_type') != 'legal':
        raise DomainError('TRC deste perfil exige pessoa jurídica declarada ausente no destino.')
    code = mapping.get('code')
    if mapping.get('confirmed') is not True or mapping.get('third_type', 'normal') != 'normal':
        raise DomainError('Confirme o CNPJ do terceiro normal antes de gerar TRC PJ.')
    if not isinstance(code, str) or not re.fullmatch('[0-9]{14}', code):
        raise DomainError('TRC PJ exige CNPJ numérico de 14 posições, sem pontuação.')
    normalize_cnpj(code)
    for key, width in [('name', 60), ('alias', 20)]:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or not ascii_field(value, 'TRC '+key, width, []).strip():
            raise DomainError('Informe razão social e apelido TRC PJ representáveis em ASCII.')
    state = data.get('state')
    if not isinstance(state, str) or not re.fullmatch('[A-Z]{2}', state):
        raise DomainError('Informe a UF TRC PJ em duas letras maiúsculas.')
    return data


def encode_registrations(journals, accounts, participants, changes):
    from .prosoft import ascii_field, numeric, put
    used = {}
    for journal in journals:
        for line in journal['lines']:
            pid = line.get('participant_id')
            if pid and accounts.get(str(line['account_id']), {}).get('third_mode', 'none') in {'optional', 'required'}:
                used.setdefault(str(pid), set()).add(journal['id'])
    definitions, requests = {}, []
    for pid in sorted(used, key=int):
        mapping = participants.get(pid, {})
        if mapping.get('create_third') is None:
            continue
        data = validate_registration(mapping)
        code = mapping['code']
        out = list(' ' * 646)
        for start, width, value in [(1, 3, 'TRC'), (11, 1, '0'), (12, 14, code),
                (26, 60, ascii_field(data['name'], 'Razão social TRC '+pid, 60, changes)),
                (86, 20, ascii_field(data['alias'], 'Apelido TRC '+pid, 20, changes)),
                (275, 2, data['state'])]:
            put(out, start, width, value)
        definition = ''.join(out)
        if code in definitions and definitions[code] != definition:
            raise DomainError('Terceiros mapeiam cadastros TRC divergentes para o mesmo CNPJ.', 409, 'third_registration_conflict')
        definitions[code] = definition
        requests.append({'participant_id': int(pid), 'destination_code': code, 'journal_ids': sorted(used[pid])})
    records, orders, hashes = [], {}, {}
    for code in sorted(definitions):
        out = list(definitions[code])
        order = len(records) + 1
        put(out, 4, 5, numeric(order, 5, 'Ordem TRC'))
        record = ''.join(out)
        records.append(record)
        orders[code] = order
        hashes[code] = digest(record.encode('ascii'))
    trace = [item | {'order': orders[item['destination_code']], 'record_sha256': hashes[item['destination_code']]} for item in requests]
    return records, trace
