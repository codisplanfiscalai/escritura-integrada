"""National NFSe XML reader. Declared amounts remain distinct from book policy."""
import re
from .importers import ImportProblem, _decimal, _date, _xml_date, _source, _issue, _flatten_repeated

NS = 'http://www.sped.fazenda.gov.br/nfse'


def node(root, path, required=False):
    found = root.findall('/'.join('{'+NS+'}'+part for part in path.split('/')))
    if len(found) > 1 or required and len(found) != 1:
        raise ImportProblem('NFSE_FIELD_AMBIGUOUS', 'NFS-e sem campo único: '+path)
    return found[0] if found else None


def value(root, path, required=False):
    element = node(root, path, required)
    if element is None: return None
    if len(element) or required and not (element.text or '').strip():
        raise ImportProblem('NFSE_FIELD_INVALID', 'Campo NFS-e inválido: '+path)
    return (element.text or '').strip()


def read_document(root, filename, company, result, sha256):
    info = node(root, 'infNFSe', True)
    dps = node(info, 'DPS/infDPS', True)
    def party(path):
        p = node(dps, path)
        if p is None: return {'tax_id':'', 'name':''}
        identifiers = [value(p, tag) for tag in ('CNPJ','CPF','NIF') if value(p, tag)]
        if len(identifiers) > 1: raise ImportProblem('NFSE_PARTY', 'Inscrição da parte ambígua.')
        return {'tax_id':identifiers[0] if identifiers else '', 'name':value(p,'xNome') or '',
                'declared_fields':_flatten_repeated(p)}
    issuer, recipient = party('prest'), party('toma')
    # National NFSe may place the legal name only in the authorized emit group.
    emit = node(info, 'emit')
    if not issuer['name'] and emit is not None:
        emit_id = value(emit,'CNPJ') or value(emit,'CPF')
        if emit_id == issuer['tax_id']: issuer['name'] = value(emit,'xNome') or ''
    target = company['tax_id']
    roles = (target == issuer['tax_id'], target == recipient['tax_id'])
    if roles == (True, True): raise ImportProblem('COMPANY_ROLE_AMBIGUOUS', 'Empresa é prestadora e tomadora; revise a operação individualmente.')
    if not any(roles): raise ImportProblem('COMPANY_MISMATCH', 'Empresa não é prestadora nem tomadora desta NFS-e.')
    direction = 'outgoing' if roles[0] else 'incoming'
    partner = recipient if roles[0] else issuer
    if not partner['name']: partner['name'] = partner['tax_id'] or 'Tomador não identificado no XML'
    key = info.get('Id', '')
    if not re.fullmatch(r'NFS[0-9A-Z]{50}', key): raise ImportProblem('NFSE_KEY', 'Identificador nacional NFS-e inválido.')
    environment = value(dps,'tpAmb',True)
    if environment not in {'1','2'}: raise ImportProblem('NFSE_ENVIRONMENT','Ambiente NFS-e inválido.')
    receipt_environment=company.get('import_options',{}).get('reception_environment')
    if receipt_environment is not None and environment != {'production':'1','restricted_production':'2'}.get(receipt_environment):
        raise ImportProblem('NFSE_ENVIRONMENT_MISMATCH','Ambiente do XML difere do recibo nacional; mantenha em conferência.')
    emitted = _xml_date(value(dps,'dhEmi',True))
    competence = _date(value(dps,'dCompet',True))
    total = _decimal(value(dps,'valores/vServPrest/vServ',True),money=True,allow_negative=False)
    taxes = {}
    for tag in ('vBC','vISSQN','vLiq','vTotalRet'):
        amount = value(info,'valores/'+tag)
        if amount is not None: taxes['ISS.'+tag] = _decimal(amount,money=True,allow_negative=False)
    retained = value(dps,'valores/trib/tribMun/tpRetISSQN')
    if retained is not None:
        if retained not in {'1','2','3'}: raise ImportProblem('NFSE_WITHHOLDING','Tipo de retenção ISSQN inválido.')
        taxes['ISS.tpRetISSQN'] = retained
        if retained in {'2','3'} and 'ISS.vISSQN' in taxes: taxes['ISS.vISSRetido'] = taxes['ISS.vISSQN']
        if retained == '1': taxes['ISS.vISSRetido'] = '0.00'
    federal='valores/trib/tribFed/piscofins/'
    shared_base=value(dps,federal+'vBCPisCofins')
    if shared_base is not None:
        for tax in ('PIS','COFINS'): taxes[tax+'.vBC']=_decimal(shared_base,money=True,allow_negative=False)
    for tag,tax_key in [('vPis','PIS.vPIS'),('vCofins','COFINS.vCOFINS'),('pAliqPis','PIS.pPIS'),('pAliqCofins','COFINS.pCOFINS')]:
        amount=value(dps,federal+tag)
        if amount is not None: taxes[tax_key]=_decimal(amount,money=tag.startswith('v'),allow_negative=False)
    options = company.get('import_options', {})
    posting_date = options.get('posting_date') or emitted
    doc = {'model':'NFSE','document_type':'NFSE','number':value(info,'nNFSe',True),
           'series':value(dps,'serie') or '', 'key':key[3:], 'direction':direction,
           'issue_date':emitted,'posting_date':_date(posting_date),'declared_competence':competence,
           'posting_date_proposed':direction=='incoming' and not options.get('posting_date'),
           'partner_name':partner['name'],'partner_tax_id':partner['tax_id'],
           'issuer':issuer,'recipient':recipient,'total':total,'taxes':taxes,'items':[],
           'cfop':'','source_cfops':[],'source':_source(filename,record='NFSe'),
           'source_hash':sha256,'declared_xml':_flatten_repeated(root),
           'signature_verified':False,'schema_validated':False,'environment':environment,
           'authorization':{'source':'national_nfse_xml','signature_verified':False},
           'service_bookkeeping':{'declared_competence':competence,'description':value(dps,'serv/cServ/xDescServ') or ''}}
    result['documents'].append(doc)
    _issue(result,'DOCUMENT_REVIEW_REQUIRED','Confira as partes, competência, retenção e perfil de serviços antes de escriturar.',doc['source'],'warning')
    if environment=='2': _issue(result,'HOMOLOGATION_DOCUMENT','NFS-e de produção restrita; sem escrituração direta.',doc['source'],'warning')
    return 'nfse_nacional'
