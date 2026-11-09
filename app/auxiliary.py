"""Representações fiscais em Python; geração visual não valida assinatura ou incidência."""
from .core import DomainError

RENDERER='BrazilFiscalReport 1.3.1'


def render_danfe(raw):
    from lxml import etree
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise DomainError('DTD não permitido.')
    root=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True))
    ns={'n':'http://www.portalfiscal.inf.br/nfe'}
    model=root.xpath('string(.//*[local-name()="ide"]/*[local-name()="mod"])')
    if model not in {'55','65','57','58','67'}:raise DomainError('Modelo sem representação implementada.',422,'renderer_not_validated')
    if model=='67':return render_cte_os(root), 'Escritura/CTeOS-conferencia-v1'
    if model=='55' and root.findtext('.//n:transp/n:modFrete',namespaces=ns) not in {'0','1','2','3','4','9'}:
        raise DomainError('XML sem modalidade de frete válida: a representação visual exige campos completos.',422,'renderer_input')
    try:
        from brazilfiscalreport.danfe import Danfe
        from brazilfiscalreport.danfce import Danfce
        from brazilfiscalreport.dacte import Dacte
        from brazilfiscalreport.damdfe import Damdfe
        renderer={'55':Danfe,'65':Danfce,'57':Dacte,'58':Damdfe}[model]
        doc=renderer(xml=etree.tostring(root,encoding='unicode'))
        return bytes(doc.output()),RENDERER+'/'+type(doc).__name__
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning('Falha no renderizador DANFE: %s',type(exc).__name__)
        raise DomainError('O renderizador não produziu o documento auxiliar para este XML. Original preservado; confira sua integridade e os campos obrigatórios.',422,'renderer_input') from None


def render_cte_os(root):
    """Espelho completo de leitura. Não substitui DACTE OS homologado do emissor."""
    from io import BytesIO
    from lxml import etree
    from xml.sax.saxutils import escape
    from reportlab.platypus import SimpleDocTemplate,Paragraph,LongTable,TableStyle,Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    styles=getSampleStyleSheet();output=BytesIO()
    story=[Paragraph('CT-e OS · espelho para conferência',styles['Title']),Paragraph('Modelo 67. Representação dos dados do XML original. Este espelho não substitui o DACTE OS emitido pelo prestador e não comprova autorização ou assinatura.',styles['BodyText']),Spacer(1,14)]
    def p(v):return Paragraph(escape(str(v)),styles['BodyText'])
    def leaves(element,path=''):
        name=etree.QName(element).localname
        if name in {'Signature','X509Certificate'}:return
        path=path+'/'+name
        if len(element):
            for child in element:yield from leaves(child,path)
        elif element.text and element.text.strip():yield [p(path),p(element.text.strip())]
    rows=[[p('Campo / grupo'),p('Conteúdo')]]+list(leaves(root))
    table=LongTable(rows,colWidths=[255,268],repeatRows=1,splitInRow=1)
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dcebe7')),('GRID',(0,0),(-1,-1),.3,colors.grey),('VALIGN',(0,0),(-1,-1),'TOP')]))
    story.append(table)
    def footer(canvas,doc):canvas.drawString(36,20,f'Escritura Integrada · conferência CT-e OS · página {doc.page}')
    SimpleDocTemplate(output,pagesize=A4,leftMargin=36,rightMargin=36).build(story,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()
