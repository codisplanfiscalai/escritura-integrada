"""Pure, loss-aware Escritura and Prosoft chart-of-accounts interchange.

``decode_plan(bytes, format, options)`` returns a JSON-compatible plan.
``encode_plan(plan, format, options)`` returns ``(bytes, manifest)``. The
manifest's ``changes`` must be explicitly accepted by the application before
release of an ASCII file. No persistence or user approval occurs here.

Prosoft export records lack properties. Supply options['properties'] with
mask and groups. Zero-padded classifiers are inherently ambiguous: supply
classification_depths (keyed by access code), or explicitly select
trailing_zero_policy='trim_groups'. The latter removes complete trailing
zero groups, never individual digits, and is recorded in warnings.
"""
from copy import deepcopy
import json
import re
import unicodedata

SCHEMA = 'escritura-account-plan/v1'
GROUPS = ('asset', 'liability', 'compensation', 'cost', 'expense', 'revenue')
FLAGS = {'entries': '0123', 'monetary_correction': '012', 'reducer': '01',
         'cost_center': '0123', 'currency_conversion': '0123456', 'reconciliation': '01'}


class PlanCodecError(ValueError):
    """Invalid input or a decision required before unambiguous conversion."""


def _fail(message):
    raise PlanCodecError(message)


def _mapping(value, label):
    if not isinstance(value, dict):
        _fail(f'{label} deve ser um objeto JSON.')
    return value


def _property_shapes(properties):
    _mapping(properties, 'properties')
    for key in ('groups', 'group_natures'):
        if key in properties:
            _mapping(properties[key], f'properties.{key}')
    return properties


def _options(options):
    options = {} if options is None else _mapping(options, 'options')
    for key in ('properties', 'groups', 'classification_depths', 'nature_overrides'):
        if key in options:
            _mapping(options[key], f'options.{key}')
    if 'properties' in options:
        _property_shapes(options['properties'])
    if 'encoding' in options and not isinstance(options['encoding'], str):
        _fail('options.encoding deve ser texto.')
    return options


def _properties(options):
    p = deepcopy(_property_shapes(options.get('properties', {})))
    for key in ('mask', 'groups'):
        if key in options:
            p[key] = deepcopy(options[key])
    mask = p.get('mask', '')
    if not isinstance(mask, str) or not re.fullmatch(r'#(?:\.#+)+', mask) or mask.count('#') > 15 or len(mask) > 29:
        _fail('Informe máscara explícita válida, começando por #., com até 15 dígitos.')
    groups = p.get('groups', {})
    if not isinstance(groups, dict) or any(str(groups.get(k, '')) not in '123456789' or len(str(groups.get(k, ''))) != 1 for k in GROUPS):
        _fail('Informe os seis grupos Prosoft explicitamente (asset, liability, compensation, cost, expense, revenue).')
    p['groups'] = {k: str(groups[k]) for k in GROUPS}
    p.setdefault('generated_access', '0')
    p.setdefault('plan_type', '0')
    p.setdefault('special_mask', '')
    p.setdefault('filler', ' ' * 36)
    return p


def _decode_bytes(raw, options, warnings):
    if isinstance(raw, str):
        return raw, 'unicode'
    if not isinstance(raw, (bytes, bytearray)):
        _fail('Conteúdo deve ser bytes ou texto.')
    encoding = options.get('encoding')
    if encoding:
        try:
            return bytes(raw).decode(encoding), encoding
        except (UnicodeError, LookupError) as exc:
            _fail(f'Codificação inválida: {exc}')
    try:
        return bytes(raw).decode('ascii'), 'ascii'
    except UnicodeDecodeError:
        try:
            result = bytes(raw).decode('utf-8-sig')
            warnings.append('Arquivo fora do ASCII do leiaute; UTF-8 detectado. Revise a codificação.')
            return result, 'utf-8-sig'
        except UnicodeDecodeError:
            try:
                result = bytes(raw).decode('cp1252')
            except UnicodeDecodeError:
                _fail('Codificação não reconhecida; informe encoding explicitamente.')
            warnings.append('Arquivo fora do ASCII do leiaute; cp1252 presumido. Confirme a codificação.')
            return result, 'cp1252'


def _classifier(raw, mask, code, options, warnings):
    if not re.fullmatch(r'[0-9]{15}', raw):
        _fail(f'Conta {code}: classificador deve conter 15 dígitos.')
    sizes = [len(s) for s in mask.split('.')]
    if any(c != '0' for c in raw[sum(sizes):]):
        _fail(f'Conta {code}: classificador excede a máscara.')
    parts, pos = [], 0
    for size in sizes:
        parts.append(raw[pos:pos + size])
        pos += size
    depth = (options.get('classification_depths') or {}).get(code)
    if depth is not None:
        if isinstance(depth, bool) or not isinstance(depth, int) or not 1 <= depth <= len(parts):
            _fail(f'Conta {code}: profundidade inválida.')
        if any(set(s) != {'0'} for s in parts[depth:]):
            _fail(f'Conta {code}: profundidade descartaria dígitos significativos.')
        parts = parts[:depth]
    elif len(parts) > 1 and set(parts[-1]) == {'0'}:
        if options.get('trailing_zero_policy') != 'trim_groups':
            _fail(f'Conta {code}: zeros finais ambíguos; informe classification_depths ou confirme trailing_zero_policy=trim_groups.')
        while len(parts) > 1 and set(parts[-1]) == {'0'}:
            parts.pop()
    return '.'.join(parts)


def _nature(classifier, reducer, properties):
    matches = [k for k, v in properties['groups'].items() if v == classifier[0]]
    natures = {'asset': 'debit', 'liability': 'credit', 'cost': 'debit', 'expense': 'debit', 'revenue': 'credit'}
    explicit = properties.get('group_natures', {}).get(classifier[0])
    values = {natures[k] for k in matches if k in natures}
    if explicit in ('debit', 'credit'):
        nature = explicit
    elif len(values) == 1 and 'compensation' not in matches:
        nature = values.pop()
    else:
        _fail(f'Grupo {classifier[0]} sem natureza inequívoca; informe properties.group_natures (debit/credit).')
    if reducer not in '01' or len(reducer) != 1:
        _fail('Flag redutora inválida: não é possível determinar a natureza.')
    if reducer == '1':
        nature = 'credit' if nature == 'debit' else 'debit'
    report = next((k for k in matches if k in ('asset', 'liability', 'expense', 'revenue')), '')
    if report == '' and 'cost' in matches:
        report = 'expense'
    return nature, report


def _validate_native(plan):
    if not isinstance(plan, dict) or plan.get('schema') != SCHEMA:
        _fail(f'Schema nativo esperado: {SCHEMA}.')
    if not isinstance(plan.get('properties'), dict) or not isinstance(plan.get('accounts'), list):
        _fail('Plano deve conter properties e accounts.')
    if 'warnings' in plan and not isinstance(plan['warnings'], list):
        _fail('warnings deve ser uma lista JSON.')
    _property_shapes(plan['properties'])
    for a in plan['accounts']:
        if not isinstance(a, dict) or not isinstance(a.get('classifier'), str) or not a['classifier'] or not isinstance(a.get('name'), str) or not a['name']:
            _fail('Conta nativa exige classifier e name textuais não vazios.')
        if 'prosoft' in a:
            _mapping(a['prosoft'], 'account.prosoft')
            for key in ('export_filler', 'import_filler'):
                if key in a['prosoft'] and not isinstance(a['prosoft'][key], str):
                    _fail(f'account.prosoft.{key} deve ser texto.')
        if a.get('nature') not in ('debit', 'credit') or not isinstance(a.get('analytical'), bool):
            _fail('Conta nativa exige nature debit/credit e analytical booleano.')
    return plan


def decode_plan(raw, format='native', options=None):
    """Decode without changing external state; unknown native metadata survives."""
    options = _options(options)
    warnings = []
    if format == 'native':
        try:
            text = raw.decode('utf-8-sig') if isinstance(raw, (bytes, bytearray)) else raw
            plan = _validate_native(json.loads(text))
        except (UnicodeError, json.JSONDecodeError, TypeError) as exc:
            _fail(f'JSON nativo inválido: {exc}')
        plan['format'], plan['encoding'] = format, 'utf-8'
        plan.setdefault('warnings', [])
        return plan
    if format not in ('prosoft-export', 'prosoft-import', 'prosoft', 'auto'):
        _fail('Formato desconhecido.')
    text, encoding = _decode_bytes(raw, options, warnings)
    lines = text.splitlines()
    if not lines:
        _fail('Arquivo vazio.')
    is_import = lines[0].startswith('P')
    actual_format = 'prosoft-import' if is_import else 'prosoft-export'
    if format in ('prosoft-import', 'prosoft-export') and actual_format != format:
        _fail('Formato selecionado difere dos registros do arquivo.')
    if is_import:
        p = lines.pop(0)
        if len(p) != 103:
            _fail('Registro P deve conter 103 posições.')
        properties = _properties({'properties': {'mask': p[1:30].rstrip(), 'generated_access': p[30],
            'groups': dict(zip(GROUPS, p[31:37])), 'plan_type': p[37], 'special_mask': p[38:67].rstrip(), 'filler': p[67:103],
            'group_natures': (options.get('properties') or {}).get('group_natures', {})}})
    else:
        properties = _properties(options)
    if any(c != ' ' for c in properties.get('filler', '')):
        warnings.append('Registro P: filler não branco preservado; bloqueia exportação Prosoft.')
    if options.get('trailing_zero_policy') == 'trim_groups':
        warnings.append('Política explícita trim_groups aplicada: grupos finais inteiramente zero são preenchimento; revise a hierarquia.')
    accounts = []
    for i, line in enumerate(lines, 2 if is_import else 1):
        if len(line) != 204:
            _fail(f'Linha {i}: esperado registro de 204 posições, recebido {len(line)}.')
        if is_import and line[0] != 'C':
            _fail(f'Linha {i}: esperado registro C.')
        record = line[1:] if is_import else line
        code, classifier, name = record[:5], record[5:20], record[20:50].rstrip()
        if not re.fullmatch(r'[0-9]{5}', code):
            _fail(f'Linha {i}: código de acesso inválido.')
        if not name:
            _fail(f'Linha {i}: nome vazio.')
        flags = dict(zip(FLAGS, record[50:56]))
        for key, allowed in FLAGS.items():
            if flags[key] not in allowed:
                warnings.append(f'Linha {i}: flag {key}={flags[key]!r} fora do leiaute; preservada, bloqueia exportação Prosoft.')
        if flags['entries'] not in FLAGS['entries']:
            _fail(f'Linha {i}: flag de lançamentos inválida.')
        dotted = _classifier(classifier, properties['mask'], code, options, warnings)
        nature_override = (options.get('nature_overrides') or {}).get(code)
        if nature_override is not None:
            if nature_override not in ('debit', 'credit'):
                _fail(f'Conta {code}: nature_overrides exige debit/credit.')
            nature = nature_override
            report = next((k for k in ('asset', 'liability', 'expense', 'revenue') if properties['groups'][k] == dotted[0]), '')
            warnings.append(f'Conta {code}: natureza explicitamente substituída por {nature_override}; flags originais preservadas.')
        else:
            nature, report = _nature(dotted, flags['reducer'], properties)
        metadata = dict(flags, classifier_original=classifier, source_format=actual_format)
        if is_import:
            metadata.update(special_classifier=record[56:76].rstrip(), special_name=record[76:156].rstrip(), import_filler=record[156:203])
        else:
            metadata['export_filler'] = record[56:204]
        for filler_key in ('import_filler', 'export_filler'):
            if any(c != ' ' for c in metadata.get(filler_key, '')):
                warnings.append(f'Linha {i}: {filler_key} não branco preservado; bloqueia exportação Prosoft.')
        accounts.append({'access_code': code, 'prosoft_code': code, 'classifier': dotted, 'name': name, 'analytical': flags['entries'] != '0',
            'nature': nature, 'requires_cost_center': flags['cost_center'] == '3', 'active': True, 'report_group': report, 'prosoft': metadata})
    if not accounts:
        _fail('Plano sem contas.')
    return {'schema': SCHEMA, 'properties': properties, 'accounts': accounts, 'warnings': warnings, 'format': actual_format, 'encoding': encoding}


def encode_plan(plan, format='native', options=None):
    """Return (content bytes, manifest); ASCII changes require caller approval.

    prosoft-import is the normal output to import into Prosoft. prosoft-export
    is also available for archival interchange, but cannot carry properties or
    special classifiers; their loss is reported in the manifest.
    """
    options = _options(options)
    plan = _validate_native(deepcopy(plan))
    manifest = {'format': format, 'encoding': 'utf-8' if format == 'native' else 'ascii', 'changes': [], 'warnings': []}
    manifest['text_changes'] = manifest['changes']
    if format == 'native':
        return (json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8'), manifest
    if format not in ('prosoft-import', 'prosoft-export'):
        _fail('Formato de exportação desconhecido.')
    properties = _properties({'properties': {**plan['properties'], **options.get('properties', {})}})

    def field(value, width, label, numeric=False):
        value = str(value)
        normalized = ''.join(c for c in unicodedata.normalize('NFKD', value) if not unicodedata.combining(c))
        normalized = ''.join(c if 32 <= ord(c) <= 126 else '?' for c in normalized)
        if value != normalized:
            manifest['changes'].append({'field': label, 'original': value, 'replacement': normalized})
        if len(normalized) > width:
            _fail(f'{label}: {len(normalized)} posições excedem limite {width}; truncamento não permitido.')
        if numeric and not re.fullmatch(r'[0-9]+', normalized):
            _fail(f'{label}: esperado somente dígitos.')
        return normalized.zfill(width) if numeric else normalized.ljust(width)

    for key, allowed in [('generated_access', '01'), ('plan_type', '012')]:
        if str(properties[key]) not in allowed or len(str(properties[key])) != 1:
            _fail(f'Propriedade {key} inválida.')
    if not isinstance(properties.get('filler', ''), str) or any(c != ' ' for c in properties.get('filler', '')):
        _fail('property_filler deve conter somente brancos para exportação Prosoft.')
    records = []
    if format == 'prosoft-import':
        records.append('P' + field(properties['mask'], 29, 'mask') + str(properties['generated_access']) +
            ''.join(properties['groups'][k] for k in GROUPS) + str(properties['plan_type']) +
            field(properties['special_mask'], 29, 'special_mask') + field(properties.get('filler', ''), 36, 'property_filler'))
    else:
        manifest['warnings'].append('Formato Prosoft export não inclui propriedades nem campos especiais; preserve também o arquivo nativo.')
    sizes = [len(s) for s in properties['mask'].split('.')]
    seen_codes = set()
    for a in plan['accounts']:
        code = field(a.get('prosoft_code') or a.get('access_code', ''), 5, 'prosoft_code', True)
        if code in seen_codes:
            _fail(f'Código de acesso Prosoft duplicado após normalização: {code}.')
        seen_codes.add(code)
        label = f'Conta {code}'
        parts = a['classifier'].split('.')
        if len(parts) > len(sizes) or any(not re.fullmatch(r'[0-9]+', s) or len(s) != sizes[i] for i, s in enumerate(parts)):
            _fail(f'{label}: classificador não corresponde à máscara.')
        classifier = ''.join(parts).ljust(15, '0')
        meta = a.get('prosoft', {})
        for filler_key in ('import_filler', 'export_filler'):
            if any(c != ' ' for c in meta.get(filler_key, '')):
                _fail(f'{label}: {filler_key} deve conter somente brancos para exportação Prosoft.')
        flags = {key: str(meta.get(key, '0')) for key in FLAGS}
        flags['entries'] = str(meta.get('entries', '1' if a['analytical'] else '0'))
        flags['cost_center'] = str(meta.get('cost_center', '3' if a.get('requires_cost_center') else '0'))
        for key, allowed in FLAGS.items():
            if len(flags[key]) != 1 or flags[key] not in allowed:
                _fail(f'{label}: flag {key} inválida para Prosoft.')
        if (flags['entries'] != '0') != a['analytical'] or (flags['cost_center'] == '3') != bool(a.get('requires_cost_center')):
            _fail(f'{label}: flags Prosoft conflitam com campos editados.')
        if 'reducer' not in meta:
            base_nature, _ = _nature(a['classifier'], '0', properties)
            flags['reducer'] = '0' if base_nature == a['nature'] else '1'
        expected, _ = _nature(a['classifier'], flags['reducer'], properties)
        if expected != a['nature']:
            _fail(f'{label}: natureza conflita com grupo/redutora Prosoft.')
        common = code + classifier + field(a['name'], 30, label + '.name') + ''.join(flags.values())
        if format == 'prosoft-import':
            line = 'C' + common + field(meta.get('special_classifier', ''), 20, label + '.special_classifier') + field(meta.get('special_name', ''), 80, label + '.special_name') + field(meta.get('import_filler', ''), 47, label + '.import_filler')
            if meta.get('export_filler', '').strip():
                _fail(f'{label}: filler export contém dados sem destino no registro C; use formato nativo.')
        else:
            line = common + field(meta.get('export_filler', ''), 148, label + '.export_filler')
            if meta.get('special_classifier') or meta.get('special_name') or meta.get('import_filler', '').strip():
                manifest['changes'].append({'field': label + '.special_fields', 'original': {k: meta.get(k) for k in ('special_classifier', 'special_name', 'import_filler')}, 'replacement': None})
        if len(line) != 204:
            _fail(f'{label}: tamanho de registro inconsistente.')
        records.append(line)
    return ('\r\n'.join(records) + '\r\n').encode('ascii'), manifest
