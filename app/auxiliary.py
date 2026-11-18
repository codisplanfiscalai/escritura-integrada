"""Representações fiscais em Python; geração visual não valida assinatura ou incidência."""
from .core import DomainError

RENDERER='BrazilFiscalReport 1.3.1'


def render_danfe(raw, *, document_preview=False):
    from lxml import etree
    from .importers import _xml_tree
    try: checked = _xml_tree(raw)
    except ValueError: raise DomainError('XML inválido para visualização.',422,'renderer_input') from None
    if checked.tag == '{http://www.sped.fazenda.gov.br/nfse}NFSe':
        try: return render_service_xml(checked), 'Escritura/DANFSe-conferencia-v1'
        except ValueError: raise DomainError('NFS-e sem estrutura única para visualização; confira o XML.',422,'renderer_input') from None
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise DomainError('DTD não permitido.')
    root=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True))
    ns={'n':'http://www.portalfiscal.inf.br/nfe'}
    model=root.xpath('string(.//*[local-name()="ide"]/*[local-name()="mod"])')
    if model not in {'55','65','57','58','67'}:
        if document_preview: return render_xml_mirror(checked), 'Escritura/Espelho-XML-v1'
        raise DomainError('Modelo sem representação implementada.',422,'renderer_not_validated')
    if model=='67':return render_cte_os(root), 'Escritura/CTeOS-conferencia-v1'
    if model=='55' and root.findtext('.//n:transp/n:modFrete',namespaces=ns) not in {'0','1','2','3','4','9'}:
        raise DomainError('XML sem modalidade de frete válida: a representação visual exige campos completos.',422,'renderer_input')
    try:
        from brazilfiscalreport.danfe import Danfe
        from brazilfiscalreport.danfce import Danfce
        from brazilfiscalreport.dacte import Dacte
        if document_preview and model == '57':
            from .dacte_preview import PreviewDacte
            Dacte = PreviewDacte
        from brazilfiscalreport.damdfe import Damdfe
        renderer={'55':Danfe,'65':Danfce,'57':Dacte,'58':Damdfe}[model]
        doc=renderer(xml=etree.tostring(root,encoding='unicode'))
        return bytes(doc.output()),RENDERER+'/'+type(doc).__name__
    except DomainError:
        raise
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning('Falha no renderizador DANFE: %s',type(exc).__name__)
        raise DomainError('O renderizador não produziu o documento auxiliar para este XML. Original preservado; confira sua integridade e os campos obrigatórios.',422,'renderer_input') from None


def render_service_xml(root):
    """Offline service representation, never an assertion of fiscal validation."""
    from io import BytesIO
    from xml.sax.saxutils import escape
    from reportlab.platypus import SimpleDocTemplate, Paragraph, LongTable, TableStyle, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from .nfse_import import node, value
    info=node(root,'infNFSe',True);dps=node(info,'DPS/infDPS',True)
    styles=getSampleStyleSheet();output=BytesIO()
    def p(text): return Paragraph(escape(str(text or 'Não informado')),styles['BodyText'])
    rows=[['NFS-e',value(info,'nNFSe')],['Chave',info.get('Id','')[3:]],
          ['Emissão',value(dps,'dhEmi')],['Competência declarada',value(dps,'dCompet')],
          ['Prestador',value(info,'emit/xNome') or value(dps,'prest/xNome')],
          ['CPF/CNPJ prestador',value(dps,'prest/CNPJ') or value(dps,'prest/CPF')],
          ['Tomador',value(dps,'toma/xNome')],['CPF/CNPJ tomador',value(dps,'toma/CNPJ') or value(dps,'toma/CPF')],
          ['Serviço',value(dps,'serv/cServ/xDescServ')],['Valor dos serviços',value(dps,'valores/vServPrest/vServ')],
          ['Base de cálculo ISSQN',value(info,'valores/vBC')],['ISSQN',value(info,'valores/vISSQN')],
          ['Tipo de retenção ISSQN',value(dps,'valores/trib/tribMun/tpRetISSQN')],['Valor líquido',value(info,'valores/vLiq')]]
    table=LongTable([[p(a),p(b)] for a,b in rows],colWidths=[155,368],splitInRow=1)
    table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.3,colors.grey),('VALIGN',(0,0),(-1,-1),'TOP')]))
    story=[Paragraph('DANFSe · representação para conferência',styles['Title']),
           p('Gerado a partir do XML arquivado. Não substitui o DANFSe do serviço nacional nem comprova assinatura, autorização ou situação atual.'),Spacer(1,12),table]
    SimpleDocTemplate(output,pagesize=A4,leftMargin=36,rightMargin=36).build(story)
    return output.getvalue()


def render_xml_mirror(root):
    """Generic read-only representation for events, summaries and other XMLs."""
    from io import BytesIO
    from xml.sax.saxutils import escape
    from reportlab.platypus import SimpleDocTemplate,Paragraph,LongTable,TableStyle,Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    styles=getSampleStyleSheet();out=BytesIO();rows=[];truncated=False
    def leaves(element,path=''):
        nonlocal truncated
        name=element.tag.rsplit('}',1)[-1]
        if name in {'Signature','X509Certificate','X509Data'}: return
        if len(name)>100: name=name[:100]+' […]';truncated=True
        path=path+'/'+name
        if len(path)>500: path=path[:350]+' […] '+path[-140:];truncated=True
        if len(element):
            for child in element: yield from leaves(child,path)
        else: yield path,(element.text or '').strip()
    for path,value in leaves(root):
        if len(rows)>=2000: truncated=True;break
        if len(value)>1000: value=value[:1000]+' […]';truncated=True
        rows.append([Paragraph(escape(path),styles['BodyText']),Paragraph(escape(value),styles['BodyText'])])
    story=[Paragraph('Espelho XML para conferência',styles['Title']),Paragraph('Leitura do original arquivado. Resumo ou evento não é DANFE, nota completa, manifestação ou prova de autorização.',styles['BodyText']),Spacer(1,12)]
    if truncated: story.append(Paragraph('Visualização resumida por limite de tamanho. Baixe o XML para consultar o conteúdo integral.',styles['BodyText']))
    table=LongTable(rows or [['XML','Sem campos textuais']],colWidths=[250,273],splitInRow=1)
    table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.3,colors.grey),('VALIGN',(0,0),(-1,-1),'TOP')]))
    story.append(table);SimpleDocTemplate(out,pagesize=A4,leftMargin=36,rightMargin=36).build(story)
    return out.getvalue()


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
