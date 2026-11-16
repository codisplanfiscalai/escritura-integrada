"""Stored-document evidence for EFD-Contribuições preparation, never a serializer.

No CST/regime allocation, credit or contribution calculation. Read the same
stored document representation and sources as Core.documents in one snapshot.
"""
from copy import deepcopy
import json

from fastapi import Request
from fastapi.responses import Response
from ..core import DomainError, company_row, digest, pack, period as validate_period
from ..fiscal_series import settings as series_settings
from ..permissions import effect

BASE_URL = 'https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-contribuicoes/'
REFERENCE = {
    'checked_on': '2026-11-15', 'diagnostic_period_reviewed': '2026-11',
    'guide_version': '1.35', 'guide_revision': '2021-06-18',
    'layout_code_in_guide': '006', 'layout_version_in_guide': '3.2.0',
    'layout_initial_period_in_guide': '2020-01',
    'complete_current_layout_review': False, 'official_program_validated': False,
    'sources': [
        {'id': 'guide-1.35', 'url': BASE_URL + 'manuais/guia_pratico_efd_contribuicoes_versao_1_35-18_06_2021.pdf/@@display-file/file',
         'bytes': 4105830, 'sha256': '60eace459169238808e3e745e952fcbbbd2af6b7f933b043e8c9692b68f4d08b',
         'pages_reviewed': [1, 57, 66, 67, 71, 72, 105, 106, 117, 118, 122, 123]},
        {'id': 'nt12-2026', 'url': BASE_URL + 'documentos-tecnicos/nota-tecnica-12-2026-reducao-linear-de-incentivos-e-beneficios-lc-224/@@display-file/file',
         'bytes': 224526, 'sha256': '9ff91fc533ae9a7c5865dde4939dbcda717287fec2f7bf5b24af0a931b35b91b',
         'pages_reviewed': [1]},
        {'id': 'nt13-2026', 'url': BASE_URL + 'documentos-tecnicos/nota-tecnica-013_2026-alteracoes-efd-contribuicoes-para-rtc-2027.pdf/@@display-file/file',
         'bytes': 346724, 'sha256': '5b588eb7a49581a4073eaaad1e1ad2c73f18781fa90fb5e46439eaaab6c1c5b1',
         'pages_reviewed': [1]},
    ],
}


def observed_fields(document):
    """Locate known storage spellings, without mapping or validating fiscal values.

    Paths are arrays: the last segment may itself contain an XML slash.
    Blank, null and non-text values remain distinguishable from absent keys.
    """
    fields, issues = [], []
    def scan(value, path):
        if not isinstance(value, dict):
            issues.append({'path': path, 'code': 'UNREADABLE_FIELD_CONTAINER'})
            return
        for key in sorted(value):
            for tax in ('PIS', 'COFINS'):
                names = {f'CST_{tax}', f'VL_BC_{tax}', f'ALIQ_{tax}_PERCENT',
                         f'ALIQ_{tax}_REAIS', f'QUANT_BC_{tax}', f'VL_{tax}', f'VL_{tax}_ST'}
                if key in names or key.startswith(tax + '/') or key.rsplit('/', 1)[-1] == 'v' + tax:
                    raw = value[key]
                    state = ('null' if raw is None else 'blank' if raw == '' else
                             'stored_text_unvalidated' if isinstance(raw, str) else 'unsupported_value_type')
                    fields.append({'tax': tax, 'path': path + [key],
                                   'stored_value': deepcopy(raw), 'state': state})
    scan(document.get('taxes', {}), ['taxes'])
    scan(document.get('raw_fields', {}), ['raw_fields'])
    items = document.get('items', [])
    if not isinstance(items, list):
        issues.append({'path': ['items'], 'code': 'UNREADABLE_ITEM_CONTAINER'})
    else:
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                issues.append({'path': ['items', index], 'code': 'UNREADABLE_ITEM'})
                continue
            scan(item.get('taxes', {}), ['items', index, 'taxes'])
            scan(item.get('raw_fields', {}), ['items', index, 'raw_fields'])
    return {'fields': fields, 'issues': issues, 'semantic_validation_performed': False}


def contributions_snapshot(core, cid, competence):
    competence = validate_period(competence)
    with core.db.read(snapshot=True) as conn:
        effect(conn, cid, 'fiscal.documents', 'read')
        effect(conn, cid, 'fiscal.documents', 'export')
        company = company_row(conn, cid)
        digits = series_settings(conn, cid)['digits']
        documents = []
        for row in conn.execute('SELECT * FROM documents WHERE company_id=? AND period=? ORDER BY posting_date,id', (cid, competence)):
            stored = core._document_values(row, digits)
            names = ('id', 'company_id', 'version', 'period', 'direction', 'model', 'number',
                     'series', 'declared_series', 'key', 'issue_date', 'posting_date', 'movement_date',
                     'status', 'document_state', 'book_cancellation', 'source', 'source_hash',
                     'cfop_perspective', 'document_type', 'taxes', 'raw_fields', 'items', 'import_posting')
            document = {key: deepcopy(stored[key]) for key in names if key in stored}
            document['stored_total_cents'] = str(row['total_cents'])
            document['stored_payload_sha256'] = row['payload_hash']
            document['sources'] = []
            document['tax_evidence'] = observed_fields(stored)
            document['efd_fiscal_inclusion'] = None
            documents.append(document)
        by_id = {document['id']: document for document in documents}
        for source in conn.execute('''SELECT s.* FROM document_sources s JOIN documents d
            ON d.company_id=s.company_id AND d.id=s.document_id
            WHERE d.company_id=? AND d.period=? ORDER BY s.id''', (cid, competence)):
            by_id[source['document_id']]['sources'].append({'id': source['id'],
                'source_hash': source['source_hash'], 'source': json.loads(source['source_json'])})
        warnings = []
        def warn(code, message):
            warnings.append({'code': code, 'message': message, 'blocking_export': False})
        warn('PREPARATION_ONLY', 'Evidências armazenadas, sem arquivo EFD-Contribuições, apuração, assinatura ou validação oficial.')
        warn('SOURCE_CST_NOT_COMPANY_CLASSIFICATION', 'CST/valores de origem são preservados; não representam classificação da empresa, direito a crédito ou decisão de inclusão fiscal.')
        warn('REFERENCE_REVIEW_PARTIAL', 'Guia 1.35, NT11/12/13 e tabelas CST conferidos para o contrato declarado; benefícios, demais tabelas, regras completas e programa oficial não foram validados integralmente.')
        warn('REQUIRED_DATA_UNATTESTED', 'Regime 0110, critérios de receita, ajustes, retenções e cadeia 1100/1500 não foram atestados; permanecem nulos, sem usar zero.')
        if competence != REFERENCE['diagnostic_period_reviewed']:
            warn('PERIOD_OUTSIDE_REVIEWED_SLICE', 'Dados exportados; a matriz deste diagnóstico foi confrontada para novembro/2026. Não se aplica o leiaute automaticamente a outro período.')
        if competence >= '2027-01':
            warn('TRANSITION_2027_NOT_IMPLEMENTED', 'NT13 prevê finalidades específicas após 2026; este diagnóstico não implementa transição CBS nem presume extinção de todos os fluxos.')
        if not documents:
            warn('NO_STORED_DOCUMENTS', 'Nenhum documento armazenado nessa competência; isto não atesta ausência de movimento ou dispensa da obrigação.')
        if any(not d['tax_evidence']['fields'] for d in documents):
            warn('NO_RECOGNIZED_TAX_FIELDS', 'Há documento sem campos PIS/Cofins reconhecidos no armazenamento consultado; valores não foram preenchidos.')
        if any(d['tax_evidence']['issues'] or any(f['state'] != 'stored_text_unvalidated' for f in d['tax_evidence']['fields']) for d in documents):
            warn('INCOMPLETE_OR_UNTYPED_SOURCE_VALUES', 'Há estruturas, valores vazios/nulos ou tipos não textuais; dados preservados sem conversão decimal ou classificação.')
        from .contributions_contracts import declaration_review
        preparation = declaration_review(conn, cid, competence)
        snapshot = {
            'schema_version': 2, 'mode': 'stored_document_evidence_only',
            'company': {'id': cid, 'code': company['code'], 'tax_id': company['tax_id'],
                        'stored_regime_label': company['regime']},
            'period': competence, 'scope_basis': 'stored_posting_period',
            'reference': deepcopy(REFERENCE), 'documents': documents,
            'preparation_review': preparation,
            'summary': {'stored_documents': len(documents),
                        'recognized_field_observations': sum(len(d['tax_evidence']['fields']) for d in documents)},
            'unattested': {'regime_0110': None, 'revenue_recognition': None,
                'taxable_bases': None, 'tax_due': None, 'credit_1100_1500_history': None,
                'withholdings': None, 'adjustments': None, 'complete_efd_layout': None},
            'source_semantic_validation_performed': False, 'generates_efd': False,
            'official_program_validated': False, 'warnings': warnings,
        }
        return {'snapshot': snapshot, 'snapshot_sha256': digest(snapshot)}


def register_contributions_routes(app, core, check_period):
    @app.get('/api/companies/{cid}/sped-generator/contributions-snapshot')
    def contributions(cid: int, request: Request, period: str):
        competence = check_period(request, period)
        session = request.state.session
        if session['active_company_id'] != cid or session.get('module', 'fiscal') != 'fiscal':
            raise DomainError('Ative a empresa e o módulo Fiscal do diagnóstico.', 409, 'stale_context')
        for header, expected in [('x-company-id', str(cid)), ('x-year', competence[:4]), ('x-module', 'fiscal')]:
            if request.headers.get(header) and request.headers[header] != expected:
                raise DomainError('O contexto mudou. Reabra o diagnóstico na empresa, exercício e módulo selecionados.', 409, 'stale_context')
        result = contributions_snapshot(core, cid, competence)
        return Response(pack(result) + '\n', media_type='application/json', headers={
            'Content-Disposition': f'attachment; filename="contribuicoes-preparacao-{cid}-{competence}.json"',
            'Cache-Control': 'no-store', 'X-Snapshot-SHA256': result['snapshot_sha256']})
