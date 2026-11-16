"""Narrow integration with existing authentication, context and fiscal permissions."""
import base64
import hashlib
import json
from fastapi import Body, Request

from ..core import DomainError, company_row, integer, select_one, period as validate_period
from ..import_package_cleanup import require_original
from .native_export import consolidate_native_sped
from .ecd_snapshot import register_ecd_snapshot_routes
from ..permissions import effect
from .consolidation import preview_nfce_groups


def consolidation_preview(core, cid, competence):
    competence = validate_period(competence)
    with core.db.read(snapshot=True) as conn:
        effect(conn, cid, 'fiscal.documents', 'read')
        company = company_row(conn, cid)
        rows = conn.execute(
            'SELECT * FROM documents WHERE company_id=? AND period=? ORDER BY id',
            (cid, competence))
        documents = (core._document_values(row) for row in rows)
        return preview_nfce_groups(documents, company_id=cid,
                                   company_tax_id=company['tax_id'], competence=competence)


def register_sped_generator_routes(app, core, check_period):
    from .obligations import register_obligation_routes
    register_obligation_routes(app)

    @app.get('/api/companies/{cid}/sped-generator/nfce-consolidation')
    def nfce_consolidation(cid: int, request: Request, period: str):
        competence = check_period(request, period)
        session = request.state.session
        if session['active_company_id'] != cid or session.get('module', 'fiscal') != 'fiscal':
            raise DomainError('Ative a empresa e o módulo Fiscal da consulta.', 409, 'stale_context')
        return consolidation_preview(core, cid, competence)

    @app.post('/api/companies/{cid}/sped-generator/consolidation-export')
    def consolidation_export(cid: int, request: Request, payload: dict = Body(...)):
        if set(payload) - {'period', 'import_id', 'consolidate_nfce', 'segment_on_gap'}:
            raise DomainError('Opção não suportada por este incremento do exportador.')
        competence = check_period(request, payload.get('period'))
        session = request.state.session
        if session['active_company_id'] != cid or session.get('module', 'fiscal') != 'fiscal':
            raise DomainError('Ative a empresa e o módulo Fiscal da consulta.', 409, 'stale_context')
        enabled = payload.get('consolidate_nfce', False)
        segment_on_gap = payload.get('segment_on_gap', True)
        if type(enabled) is not bool or type(segment_on_gap) is not bool:
            raise DomainError('Opções de consolidação devem ser booleanas.')
        with core.db.read(snapshot=True) as conn:
            effect(conn, cid, 'fiscal.documents', 'read')
            effect(conn, cid, 'fiscal.documents', 'export')
            effect(conn, cid, 'fiscal.imports', 'export')
            company = company_row(conn, cid)
            batch = select_one(conn, 'imports', cid, integer(payload.get('import_id'), 'Importação'))
            require_original(conn, cid, batch['id'])
            if batch['period'] != competence:
                raise DomainError('Competência da importação difere da consulta.', 409, 'period_mismatch')
            if json.loads(batch['parsed_json']).get('format') != 'sped_efd_icms_ipi_020':
                raise DomainError('Este incremento usa um EFD 020 original importado; XML/ZIP para EFD permanece pendente.')
            original = bytes(batch['original'])
            result = consolidate_native_sped(original, company_tax_id=company['tax_id'],
                competence=competence, enabled=enabled, segment_on_gap=segment_on_gap)
            content = result.pop('payload')
            return {**result, 'import_id': batch['id'], 'period': competence,
                    'filename': f"gerador-sped-import-{batch['id']}.txt",
                    'source_sha256': hashlib.sha256(original).hexdigest(),
                    'result_sha256': hashlib.sha256(content).hexdigest(),
                    'content_base64': base64.b64encode(content).decode()}

    @app.post('/api/companies/{cid}/sped-generator/bookkeeping-block-c')
    def bookkeeping_block_c(cid: int, request: Request, payload: dict = Body(...)):
        from .bookkeeping import generate_nfce_block_c
        allowed = {'period', 'header_0000', 'profile', 'activity', 'purpose'}
        if set(payload) - allowed:
            raise DomainError('Opção não suportada neste incremento do Bloco C.')
        if any(not isinstance(value, str) for key, value in payload.items() if key != 'period'):
            raise DomainError('Opções do cabeçalho devem ser textos.')
        competence = check_period(request, payload.get('period'))
        session = request.state.session
        if session['active_company_id'] != cid or session.get('module', 'fiscal') != 'fiscal':
            raise DomainError('Ative a empresa e o módulo Fiscal da consulta.', 409, 'stale_context')
        with core.db.read(snapshot=True) as conn:
            effect(conn, cid, 'fiscal.documents', 'read')
            effect(conn, cid, 'fiscal.documents', 'export')
            company = company_row(conn, cid)
            rows = conn.execute('SELECT * FROM documents WHERE company_id=? AND period=? ORDER BY id',
                                (cid, competence))
            result = generate_nfce_block_c((core._document_values(row) for row in rows),
                company=company, competence=competence, options={key: value for key, value in payload.items() if key != 'period'})
            content = result.pop('payload')
            return {**result, 'filename': f'efd-bloco-c-parcial-{competence}-empresa-{cid}.txt',
                    'content_base64': base64.b64encode(content).decode()}

    register_ecd_snapshot_routes(app, core, check_period)
    from .contributions_snapshot import register_contributions_routes
    register_contributions_routes(app, core, check_period)
