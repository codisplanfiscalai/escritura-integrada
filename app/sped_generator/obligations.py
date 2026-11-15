"""Read-only capability metadata, separate from authorization and file generation.

A reference layout is a research baseline, never a claim of implemented coverage.
Export availability means that the exact adapter route is registered in this app;
its own company/context/permission checks still apply.
"""
from copy import deepcopy

VERIFIED_ON = '2026-11-15'
CATALOG_PATH = '/api/sped/obligations'

_EFD_ROUTES = (
    ('native_consolidation', '/api/companies/{cid}/sped-generator/consolidation-export',
     'EFD importado, original ou consolidação nativa opcional de NFC-e próprias de saída'),
    ('bookkeeping_block_c', '/api/companies/{cid}/sped-generator/bookkeeping-block-c',
     'Bloco C parcial de NFC-e próprias de saída já escrituradas'),
)

# Manual revision, file layout and period scope are intentionally distinct.
_OBLIGATIONS = (
    {
        'id': 'efd_icms_ipi', 'name': 'EFD ICMS/IPI', 'domain': 'fiscal',
        'implementation': 'partial',
        'import_coverage': 'Leitor parcial EFD 020; não representa cobertura integral dos blocos.',
        'reference': {
            'layout': '020', 'manual_revision': 'Guia Prático 3.2.4',
            'period_scope': 'Leiaute 020: fatos de 2026; seleção de outros períodos pendente.',
            'sources': [
                'https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-icms-ipi/manuais-e-documentos-tecnicos/guia-pratico-efd-versao-3-2-4.pdf/@@download/file',
                'https://sped.rfb.gov.br/item/show/7819',
            ],
        },
        'existing_services': ['app/importers.py:_sped', 'app/fiscal_analytics.py:fiscal_posting_lines',
                              'app/sped_generator/native_export.py:consolidate_native_sped'],
        'pending': ['EFD integral a partir da escrituração e cobertura dos demais modelos/blocos',
                    'Cadastros, ajustes, apuração, inventário e seleção versionada por período',
                    'Escolha persistida por empresa e consolidação opcional na importação',
                    'Conferência de arquivo completo no PVA'],
    },
    {
        'id': 'ecd', 'name': 'ECD — SPED Contábil', 'domain': 'accounting',
        'implementation': 'not_implemented', 'import_coverage': 'Sem leitor ECD; CSV contábil não é ECD.',
        'reference': {
            'layout': '9', 'manual_revision': 'Maio/2026; ADE Cofis 1/2026',
            'period_scope': 'A partir do ano-calendário 2020, conforme manual; não é seleção automática.',
            'sources': ['https://sped.rfb.gov.br/item/show/7990'],
        },
        'existing_services': ['app/core.py:Core._journal', 'app/core.py:Core.journals',
                              'app/business.py:BusinessCore.create_opening',
                              'app/account_refs.py:resolve_account', 'app/reports.py:ReportsMixin.business_report'],
        'pending': ['Contrato anual/especial do livro e identificação de responsáveis/signatários',
                    'Mapeamento de contas/centros, saldos e demonstrações para registros ECD',
                    'Serializador, contadores, rastreabilidade de lançamentos e estornos',
                    'Reconciliação e ensaio sintético no programa oficial'],
    },
    {
        'id': 'ecf', 'name': 'ECF', 'domain': 'accounting',
        'implementation': 'not_implemented', 'import_coverage': 'Sem leitor ECF ou recuperação de ECD/ECF.',
        'reference': {
            'layout': '12', 'manual_revision': 'Julho/2026 no conteúdo; ADE Cofis 2/2026',
            'period_scope': 'Ano-calendário 2025 e situações especiais de 2026; não cobre por inferência o ano normal de 2026.',
            'sources': ['https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/ecf/manuais-e-documentos-tecnicos/manual_ecf_leiaute_12_20_05_2026_ac_2025_sit_esp_2026.docx/@@download/file'],
        },
        'existing_services': ['app/account_refs.py:resolve_account',
                              'app/reports.py:ReportsMixin.business_report'],
        'pending': ['Recuperação da ECD ativa e ECF anterior no programa oficial, quando aplicável',
                    'Plano referencial e regime/período de apuração explícitos',
                    'IRPJ/CSLL, e-Lalur/e-Lacs, ajustes e saldos transportados',
                    'Serializador por leiaute/regime e validação no programa oficial'],
    },
    {
        'id': 'efd_contribuicoes', 'name': 'EFD-Contribuições — PIS/Cofins', 'domain': 'fiscal',
        'implementation': 'not_implemented',
        'import_coverage': 'Sem leitor EFD-Contribuições; C100 de ICMS/IPI não é intercambiável.',
        'reference': {
            'layout': None, 'manual_revision': 'Guia Prático 1.35 + notas e tabelas vigentes, incluindo NT 11/12/13 de 2026',
            'period_scope': 'Matriz por competência pendente; transição 2026/2027 requer regras próprias. Versão do guia/PGE não é COD_VER.',
            'sources': [
                'https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-contribuicoes',
                'https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-contribuicoes/manuais/guia_pratico_efd_contribuicoes_versao_1_35-18_06_2021.pdf',
                'https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-contribuicoes/documentos-tecnicos/nota-tecnica-013_2026-alteracoes-efd-contribuicoes-para-rtc-2027.pdf/@@display-file/file',
            ],
        },
        'existing_services': ['app/core.py:Core._document_values',
                              'app/tax_assessment.py:TaxAssessmentMixin._assessment_snapshot',
                              'app/tax_ledger.py:TaxLedgerMixin.previous_credit'],
        'pending': ['Regime cumulativo/não cumulativo e caixa/competência com decisão rastreável',
                    'CST, natureza da receita/crédito, bases e alíquotas por contribuição',
                    'Registros de operações, apuração, retenções e histórico de créditos',
                    'Notas/tabelas por vigência e transição CBS, serializador e validação no PGE'],
    },
)


def obligation_catalog(registered_routes=()):
    """Build a fresh response; callers cannot mutate shared capability metadata."""
    registered = set(registered_routes)
    obligations = deepcopy(list(_OBLIGATIONS))
    for obligation in obligations:
        obligation.update(complete_file_generator=False, validated_in_official_program=False, exports=[])
    obligations[0]['exports'] = [
        {'id': name, 'method': 'POST', 'path': path, 'description': description,
         'registered': ('POST', path) in registered, 'format': 'txt',
         'complete_file': False, 'validated_in_official_program': False}
        for name, path, description in _EFD_ROUTES
    ]
    return {
        'schema_version': 1, 'module': 'internal_sped', 'verified_on': VERIFIED_ON,
        'availability_scope': 'Rotas registradas; não concede acesso nem certifica cobertura/conformidade.',
        'interoperability': {'destination': 'qualquer aplicação compatível com a obrigação/leiaute',
                             'vendor_required': False, 'transmission_implemented': False},
        'requirements': {
            'fiscal_warnings_block_export': False,
            'closed_period_mutations_require_reopening': True,
            'preserve_originals_and_trace': True,
            'note': 'Requisitos do módulo; catálogo não altera políticas nem travas de serviços existentes.',
        },
        'obligations': obligations,
    }


def register_obligation_routes(app):
    @app.get(CATALOG_PATH)
    def sped_obligations():
        # Inspect the running app, not the presence of source files or another PR.
        registered = ((method, route.path) for route in app.routes
                      for method in getattr(route, 'methods', ()))
        return obligation_catalog(registered)
