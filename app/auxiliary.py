"""DANFE em Python; geração visual não valida assinatura nem incidência fiscal."""
from .core import DomainError

RENDERER='BrazilFiscalReport 1.3.1'


def render_danfe(raw):
    from lxml import etree
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise DomainError('DTD não permitido.')
    root=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True))
    ns={'n':'http://www.portalfiscal.inf.br/nfe'}
    if root.findtext('.//n:ide/n:mod',namespaces=ns)!='55':raise DomainError('Geração validada nesta versão somente para DANFE modelo 55. Preserve o PDF original dos demais modelos.',422,'renderer_not_validated')
    if root.findtext('.//n:transp/n:modFrete',namespaces=ns) not in {'0','1','2','3','4','9'}:
        raise DomainError('XML sem modalidade de frete válida: a representação visual exige campos completos.',422,'renderer_input')
    try:
        from brazilfiscalreport.danfe import Danfe
        doc=Danfe(xml=etree.tostring(root,encoding='unicode'))
        return bytes(doc.output()),RENDERER+'/'+type(doc).__name__
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning('Falha no renderizador DANFE: %s',type(exc).__name__)
        raise DomainError('O renderizador não produziu DANFE para este XML. Original preservado; confira sua integridade e os campos obrigatórios.',422,'renderer_input') from None
