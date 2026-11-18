"""Read-only auxiliary PDF from the exact retained XML of a fiscal document."""
import hashlib
import json
import re
from zipfile import BadZipFile

from .core import DomainError
from .permissions import effect

SUPPORTED = {'55': 'DANFE', '65': 'DANFC-e', '57': 'DACTE', 'NFSE':'DANFSe'}


def document_auxiliary(core, cid, item_id):
    from .auditor_sources import original_xmls
    from .auxiliary import render_danfe
    from .importers import _xml_tree

    with core.db.read(snapshot=True) as conn:
        effect(conn, cid, 'fiscal.documents', 'read')
        effect(conn, cid, 'fiscal.documents', 'export')
        document = core._document(conn, cid, item_id)
        if document['model'] not in SUPPORTED:
            raise DomainError('Modelo sem prévia de layout suportada na escrituração. CT-e OS, MDF-e e outros modelos exigem integração específica; nenhum espelho será apresentado como documento oficial.', 422, 'renderer_not_validated')
        source_hash = document.get('source_hash')
        if not isinstance(source_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', source_hash):
            raise DomainError('Documento sem XML original preservado. Não é possível gerar a prévia a partir dos campos da escrituração.', 422, 'source_unavailable')
        # Candidate lookup only; verify actual bytes and identity, never filename.
        # Do not fall back to a different source version with the same key.
        for batch in conn.execute('SELECT filename,original,parsed_json FROM imports WHERE company_id=? AND original IS NOT NULL AND parsed_json LIKE ? ORDER BY id DESC', (cid, '%' + source_hash + '%')):
            candidates = [d for d in json.loads(batch['parsed_json']).get('documents', [])
                          if d.get('source_hash') == source_hash and d.get('key') == document.get('key')
                          and d.get('model') == document['model']]
            if len(candidates) != 1:
                continue
            try:
                originals = original_xmls(batch['filename'], batch['original'])
                for _, raw in originals:
                    if hashlib.sha256(raw).hexdigest() != source_hash:
                        continue
                    root = _xml_tree(raw)
                    if document['model']=='NFSE':
                        from .nfse_import import NS,node
                        if root.tag!='{'+NS+'}NFSe': continue
                        info=node(root,'infNFSe',True)
                        if info.get('Id')!='NFS'+document['key']: continue
                        pdf,renderer=render_danfe(raw,document_preview=True)
                        return pdf,renderer,source_hash
                    ns = 'http://www.portalfiscal.inf.br/' + ('cte' if document['model'] == '57' else 'nfe')
                    tag = 'infCte' if document['model'] == '57' else 'infNFe'
                    infos = list(root.iter('{'+ns+'}'+tag))
                    if len(infos) != 1:
                        continue
                    info = infos[0]
                    key = re.sub(r'^(NFe|CTe)', '', info.attrib.get('Id', ''))
                    if key != document.get('key') or info.findtext('{'+ns+'}ide/{'+ns+'}mod') != document['model']:
                        continue
                    if info.attrib.get('versao') != '4.00':
                        raise DomainError('Versão XML sem layout de prévia validado neste fluxo (NF-e/NFC-e/CT-e 4.00).', 422, 'renderer_not_validated')
                    pdf, renderer = render_danfe(raw, document_preview=True)
                    return pdf, renderer, source_hash
            except (ValueError, OSError, BadZipFile):
                continue
        raise DomainError('XML original íntegro correspondente indisponível. Nenhum documento foi alterado; a prévia requer a origem preservada.', 422, 'source_unavailable')


def register(app, core):
    from fastapi.responses import Response

    @app.get('/api/companies/{cid}/documents/{item_id}/auxiliary')
    def preview(cid: int, item_id: int):
        pdf, renderer, source_hash = document_auxiliary(core, cid, item_id)
        return Response(pdf, media_type='application/pdf', headers={
            'Content-Disposition': f'inline; filename="documento-{item_id}.pdf"',
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'X-Document-Renderer': renderer, 'X-Source-SHA256': source_hash,
        })
