from __future__ import annotations
from datetime import datetime
from decimal import Decimal,ROUND_HALF_UP
from hashlib import sha256
import re
from lxml import etree
from .catalog import CatalogSnapshot
from .input_validation import CompanyDocumentMismatch,DuplicateItemNumber,InvalidItemNumber
from .product_reconciliation import item_identity
NS={'n':'http://www.portalfiscal.inf.br/nfe'}
ZERO=Decimal('0');CENT=Decimal('0.01')

def _text(node,path,default=''):
    result=node.xpath(path,namespaces=NS)
    if isinstance(result,(str,float,bool)):return str(result) if result not in ('',None) else default
    if not result:return default
    value=result[0]
    if isinstance(value,etree._Element):return (value.text or default).strip()
    return str(value).strip()

def _dec(node,path):
    v=_text(node,path,'0').replace(',','.')
    if not re.fullmatch(r'-?\d{1,15}(?:\.\d{1,10})?',v):raise ValueError('Número decimal inválido no XML: '+path)
    return Decimal(v)

def _sum(node,path):return sum((_dec(x,'.') for x in node.xpath(path,namespaces=NS)),ZERO)
def _money(v:Decimal):return v.quantize(CENT,rounding=ROUND_HALF_UP)
def _iso(value:str):
    if not value:return None
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).isoformat()
    except:return value

def _tax_id(node,prefix):return _text(node,f'{prefix}/n:CNPJ') or _text(node,f'{prefix}/n:CPF') or None
def _digits(value):return re.sub(r'[.\s/\-]','',value or '').upper()

def _address(node,prefix):
    return {key:value for key,value in {
        'street':_text(node,f'{prefix}/n:xLgr'),'number':_text(node,f'{prefix}/n:nro'),
        'complement':_text(node,f'{prefix}/n:xCpl'),'district':_text(node,f'{prefix}/n:xBairro'),
        'city_code':_text(node,f'{prefix}/n:cMun'),'city':_text(node,f'{prefix}/n:xMun'),
        'state':_text(node,f'{prefix}/n:UF'),'postal_code':_text(node,f'{prefix}/n:CEP'),
        'country':_text(node,f'{prefix}/n:xPais'),'phone':_text(node,f'{prefix}/n:fone'),
    }.items() if value}

def _party(node,prefix,address_tag):
    return {key:value for key,value in {
        'tax_id':_tax_id(node,prefix),'name':_text(node,f'{prefix}/n:xNome'),
        'trade_name':_text(node,f'{prefix}/n:xFant'),'state_registration':_text(node,f'{prefix}/n:IE'),
        'municipal_registration':_text(node,f'{prefix}/n:IM'),'email':_text(node,f'{prefix}/n:email'),
        'address':_address(node,f'{prefix}/n:{address_tag}'),
    }.items() if value not in ('',None,{})}

def _additional_identifiers(additional:str):
    patterns={
        'chassis':r'\bCHASSI\s*[:\-]?\s*([A-Z0-9]{17})\b',
        'imei':r'\bIMEI(?:\s*[12])?\s*[:\-]?\s*(\d{15})\b',
        'serial':r'\b(?:SERIAL|N[ÚU]MERO\s+DE\s+S[ÉE]RIE|S/N)\s*[:\-]?\s*([A-Z0-9][A-Z0-9._/\-]{3,39})',
        'plate':r'\bPLACA\s*[:\-]?\s*([A-Z0-9-]{7,10})\b',
    }
    identifiers=[]
    for kind,pattern in patterns.items():
        for match in re.finditer(pattern,additional or '',re.I):
            value=match.group(1).upper()
            if not any(item['type']==kind and item['value']==value for item in identifiers):
                identifiers.append({'type':kind,'value':value,'source':'det/infAdProd','confidence':'exact' if kind in {'chassis','imei','serial'} else 'high'})
    return identifiers

def _money_map(node,prefix,names):
    return {name:str(_money(_dec(node,f'{prefix}/n:{name}'))) for name in names if _text(node,f'{prefix}/n:{name}')!=''}

def _present(values):
    return {key:value for key,value in values.items() if value not in ('',None,{},[])}

def finding(rule,severity,category,title,description,document_ref,item_number=None,evidence=None,impact=None,action=None,confidence=None):
    return {'document_ref':document_ref,'item_number':item_number,'rule_code':rule,'rule_version':'1.0.0','severity':severity,'category':category,'title':title,'description':description,'impact':impact,'recommended_action':action,'status':'open','confidence':confidence,'evidence':evidence or {}}

def parse_event(data:bytes):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():raise ValueError('DTD e entidades não são permitidas.')
    parser=etree.XMLParser(resolve_entities=False,no_network=True,remove_blank_text=True,huge_tree=False)
    root=etree.fromstring(data,parser)
    if etree.QName(root).localname not in {'procEventoNFe','evento'}:return None
    return {'access_key':_text(root,'.//n:chNFe'),'event_type':_text(root,'.//n:tpEvento'),'status_code':_text(root,'.//n:cStat'),'description':_text(root,'.//n:xEvento'),'registered_at':_iso(_text(root,'.//n:dhRegEvento'))}

def _local_text(node,name,default=''):
    if node is None:return default
    values=node.xpath(f'./*[local-name()="{name}"]')
    return ((values[0].text or '').strip() if values else default)

def _local_descendant_text(node,name,default=''):
    if node is None:return default
    values=node.xpath(f'.//*[local-name()="{name}"]')
    return ((values[0].text or '').strip() if values else default)

def _local_party(node):
    if node is None:return {}
    address=next(iter(node.xpath('./*[local-name()="enderEmit" or local-name()="enderReme" or local-name()="enderDest" or local-name()="enderExped" or local-name()="enderReceb" or local-name()="enderToma"]')),None)
    result={'tax_id':_local_text(node,'CNPJ') or _local_text(node,'CPF') or None,'name':_local_text(node,'xNome') or None,'trade_name':_local_text(node,'xFant') or None,'state_registration':_local_text(node,'IE') or None}
    if address is not None:
        result['address']={key:value for key,value in {'street':_local_text(address,'xLgr'),'number':_local_text(address,'nro'),'district':_local_text(address,'xBairro'),'city_code':_local_text(address,'cMun'),'city':_local_text(address,'xMun'),'state':_local_text(address,'UF'),'postal_code':_local_text(address,'CEP')}.items() if value}
    return {key:value for key,value in result.items() if value not in ('',None,{})}

def _generic_access_key(root,inf,prefixes):
    raw=inf.get('Id') or ''
    for prefix in prefixes:raw=raw.removeprefix(prefix)
    access_key=_digits(raw)
    if len(access_key)==44:return access_key
    for tag in ('chCTe','chMDFe'):
        candidate=_digits(_local_descendant_text(root,tag))
        if len(candidate)==44:return candidate
    return None

def parse_transport_document(root,data:bytes,source_file_id:str,xml_storage_path:str,company_tax_id:str):
    inf=(root.xpath('.//*[local-name()="infCte" or local-name()="infMDFe"]') or [None])[0]
    if inf is None:raise ValueError('XML não contém um documento fiscal eletrônico suportado.')
    ide=next(iter(inf.xpath('./*[local-name()="ide"]')),None)
    model=_local_text(ide,'mod')
    if model not in {'57','67','58'}:raise ValueError(f'Modelo fiscal {model or "não identificado"} não é suportado para auditoria.')
    document_type={'57':'CT-e','67':'CT-e OS','58':'MDF-e'}[model]
    issuer_node=next(iter(inf.xpath('./*[local-name()="emit"]')),None)
    recipient_node=next(iter(inf.xpath('./*[local-name()="dest"]')),None)
    issuer=_local_party(issuer_node);recipient=_local_party(recipient_node)
    participants=[issuer.get('tax_id'),recipient.get('tax_id')]
    for name in ('rem','exped','receb','toma4'):
        participants.append(_local_text(next(iter(inf.xpath(f'./*[local-name()="{name}"]')),None),'CNPJ'))
    company_digits=_digits(company_tax_id)
    participant_digits={_digits(value) for value in participants if value}
    if company_digits and company_digits not in participant_digits:raise CompanyDocumentMismatch()
    access_key=_generic_access_key(root,inf,('CTe','MDFe'))
    document_ref=access_key or sha256(data).hexdigest()
    issued_at=_iso(_local_text(ide,'dhEmi') or _local_text(ide,'dEmi'))
    total_node=next(iter(inf.xpath('.//*[local-name()="vPrest" or local-name()="tot"]')),None)
    total_value=_local_text(total_node,'vTPrest') or _local_text(total_node,'vCarga') or '0'
    protocol=next(iter(root.xpath('.//*[local-name()="infProt"]')),None)
    status_code=_local_text(protocol,'cStat')
    normalized={
        'document_type':document_type,
        'issuer_name':issuer.get('name'),'recipient_name':recipient.get('name'),
        'identification':{'model':model,'nature':_local_text(ide,'natOp'),'environment':_local_text(ide,'tpAmb'),'operation_type':_local_text(ide,'tpCTe'),'service_type':_local_text(ide,'tpServ')},
        'issuer':issuer,'recipient':recipient,
        'totals':{'vTPrest':total_value},
        'protocol':{'number':_local_text(protocol,'nProt'),'status_code':status_code,'status_reason':_local_text(protocol,'xMotivo'),'received_at':_iso(_local_text(protocol,'dhRecbto'))},
        'xml_sha256':sha256(data).hexdigest(),
    }
    return {
        'document_ref':document_ref,'source_file_id':source_file_id,'access_key':access_key,'model':model,
        'series':_local_text(ide,'serie') or None,'number':_local_text(ide,'nCT') or _local_text(ide,'nMDF') or None,
        'issued_at':issued_at,'direction':'saida' if _digits(issuer.get('tax_id'))==company_digits else 'entrada',
        'status':'authorized' if status_code in {'100','150'} else 'parsed',
        'issuer_tax_id':issuer.get('tax_id'),'recipient_tax_id':recipient.get('tax_id'),'total_value':str(_money(Decimal(total_value.replace(',','.')) if total_value else ZERO)),
        'ibs_cbs_base':'0.00','ibs_value':'0.00','cbs_value':'0.00','item_count':0,'normalized':normalized,
        'xml_storage_path':xml_storage_path,'danfe_storage_path':None,'items':[],
    },[]

def parse_invoice(data:bytes,source_file_id:str,xml_storage_path:str,catalog:CatalogSnapshot,company_tax_id:str):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():raise ValueError('DTD e entidades não são permitidas.')
    parser=etree.XMLParser(resolve_entities=False,no_network=True,remove_blank_text=True,huge_tree=False)
    root=etree.fromstring(data,parser)
    inf=(root.xpath('.//n:infNFe',namespaces=NS) or [None])[0]
    if inf is None:return parse_transport_document(root,data,source_file_id,xml_storage_path,company_tax_id)
    if _text(inf,'./n:ide/n:mod') not in {'55','65'}:raise ValueError('Modelo NF-e não suportado.')
    access_key=(inf.get('Id') or '').removeprefix('NFe') or _text(root,'.//n:protNFe/n:infProt/n:chNFe')
    document_ref=access_key or sha256(data).hexdigest()
    issuer=_tax_id(inf,'./n:emit');recipient=_tax_id(inf,'./n:dest')
    company_tax_id=_digits(company_tax_id);issuer_tax_id=_digits(issuer);recipient_tax_id=_digits(recipient)
    if company_tax_id and company_tax_id not in {issuer_tax_id,recipient_tax_id}:raise CompanyDocumentMismatch()
    tp_nf=_text(inf,'./n:ide/n:tpNF')
    direction=('saida' if tp_nf=='1' else 'entrada') if issuer==company_tax_id else ('entrada' if recipient==company_tax_id else ('saida' if tp_nf=='1' else 'entrada'))
    issued_at=_iso(_text(inf,'./n:ide/n:dhEmi') or _text(inf,'./n:ide/n:dEmi'))
    issued_on=datetime.fromisoformat(issued_at).date() if issued_at else None
    items=[];findings=[];item_numbers=set()
    for det in inf.xpath('./n:det',namespaces=NS):
        raw_item_number=det.get('nItem','')
        if not raw_item_number.isdigit() or int(raw_item_number)<1:raise InvalidItemNumber()
        nitem=int(raw_item_number)
        if nitem in item_numbers:raise DuplicateItemNumber()
        item_numbers.add(nitem);prod=(det.xpath('./n:prod',namespaces=NS) or [det])[0];tax=(det.xpath('./n:imposto',namespaces=NS) or [det])[0]
        components={
          'vProd':_dec(prod,'./n:vProd'),'vServ':_dec(tax,'./n:ISSQN/n:vServ'),'vFrete':_dec(prod,'./n:vFrete'),'vSeg':_dec(prod,'./n:vSeg'),'vOutro':_dec(prod,'./n:vOutro'),'vII':_sum(tax,'.//n:II/n:vII'),'vDesc':_dec(prod,'./n:vDesc'),'vPIS':_sum(tax,'.//n:PIS/*/n:vPIS'),'vCOFINS':_sum(tax,'.//n:COFINS/*/n:vCOFINS'),'vICMS':_sum(tax,'.//n:ICMS/*/n:vICMS'),'vICMSUFDest':_sum(tax,'.//n:ICMSUFDest/n:vICMSUFDest'),'vFCP':_sum(tax,'.//n:ICMS/*/n:vFCP'),'vFCPUFDest':_sum(tax,'.//n:ICMSUFDest/n:vFCPUFDest'),'vICMSMono':_sum(tax,'.//n:ICMS/*/n:vICMSMono'),'vISSQN':_sum(tax,'.//n:ISSQN/n:vISSQN'),'vIS':_sum(tax,'.//n:IS//n:vIS')}
        has_base_group=bool(tax.xpath('./n:IBSCBS/n:gIBSCBS',namespaces=NS))
        base_calc=_money(components['vProd']+components['vServ']+components['vFrete']+components['vSeg']+components['vOutro']+components['vII']-components['vDesc']-components['vPIS']-components['vCOFINS']-components['vICMS']-components['vICMSUFDest']-components['vFCP']-components['vFCPUFDest']-components['vICMSMono']-components['vISSQN']+components['vIS'])
        base_xml=_money(_dec(tax,'./n:IBSCBS/n:gIBSCBS/n:vBC'))
        if not has_base_group:base_calc=ZERO
        ibs_rate=_dec(tax,'./n:IBSCBS/n:gIBSCBS/n:gIBSUF/n:pIBSUF')+_dec(tax,'./n:IBSCBS/n:gIBSCBS/n:gIBSMun/n:pIBSMun')
        cbs_rate=_dec(tax,'./n:IBSCBS/n:gIBSCBS/n:gCBS/n:pCBS')
        ibs_xml=_money(_dec(tax,'./n:IBSCBS/n:gIBSCBS/n:vIBS') or (_dec(tax,'./n:IBSCBS/n:gIBSCBS/n:gIBSUF/n:vIBSUF')+_dec(tax,'./n:IBSCBS/n:gIBSCBS/n:gIBSMun/n:vIBSMun')))
        cbs_xml=_money(_dec(tax,'./n:IBSCBS/n:gIBSCBS/n:gCBS/n:vCBS'))
        special=bool(tax.xpath('.//n:IBSCBS//n:gRed | .//n:IBSCBS//n:gDif | .//n:IBSCBS//n:gDevTrib | .//n:IBSCBS//n:gIBSCBSMono | .//n:IBSCBS//n:gTransfCred',namespaces=NS))
        ibs_calc=_money(_money(base_xml*_dec(tax,'./n:IBSCBS/n:gIBSCBS/n:gIBSUF/n:pIBSUF')/100)+_money(base_xml*_dec(tax,'./n:IBSCBS/n:gIBSCBS/n:gIBSMun/n:pIBSMun')/100))
        cbs_calc=_money(base_xml*cbs_rate/Decimal('100'))
        if special:
            findings.append(finding('COVERAGE-IBSCBS-001','medium','coverage','Cenário IBS/CBS requer revisão','Redução, diferimento, devolução ou tributação especial: recálculo não certificado neste cenário.',document_ref,nitem,{'scope':'not_recalculated'},'Revisão fiscal necessária.','Conferir a regra vigente e os grupos especiais do XML.'))
            ibs_calc=ibs_xml;cbs_calc=cbs_xml

        ncm=re.sub(r'\D','',_text(prod,'./n:NCM'));ex_code=_text(prod,'./n:EXTIPI') or None
        actual_cst=_text(tax,'./n:IBSCBS/n:CST') or None;actual_cc=_text(tax,'./n:IBSCBS/n:cClassTrib') or None
        if catalog.cst and actual_cst and actual_cst not in catalog.cst:
            findings.append(finding('CST-CATALOG-001','high','classification','CST ausente na referência','CST do XML não consta da tabela congelada nesta auditoria.',document_ref,nitem,{'actual_cst':actual_cst,'catalog_version_id':catalog.version_id}))
        if catalog.cclass and actual_cc:
            official=catalog.cclass.get(actual_cc)
            problems=[]
            if not official:problems.append('Código não localizado')
            else:
                if official['cst']!=actual_cst:problems.append('CST incompatível')
                if issued_on and ((official.get('valid_from') and issued_on.isoformat()<official['valid_from']) or (official.get('valid_to') and issued_on.isoformat()>official['valid_to'])):problems.append('Fora da vigência da referência')
                indicator='indNFCe' if _text(inf,'./n:ide/n:mod')=='65' else 'indNFe'
                applicable=(official.get('indicators') or {}).get(indicator)
                if applicable in ('0','Não','Nao','NÃO') or (applicable is None and official.get('applicable_nfe') is False):problems.append('Não indicado para este modelo')
            if problems:findings.append(finding('CCLASS-CATALOG-001','high','classification','Revisar cClassTrib na referência','; '.join(problems)+'. A referência é versionada; confirme sua vigência normativa.',document_ref,nitem,{'actual_cst':actual_cst,'actual_cclass_trib':actual_cc,'reference':official,'catalog_version_id':catalog.version_id}))
        match=catalog.match(ncm or None,ex_code,issued_on);entry=match.get('entry');expected_cst=entry.expected_cst if entry else None;expected_cc=entry.expected_cclass_trib if entry else None
        class_status=match['status']
        if class_status=='MATCH':
            if actual_cst==expected_cst and actual_cc==expected_cc:class_status='MATCH_EXACT'
            elif not actual_cst or not actual_cc:class_status='DOCUMENT_CLASSIFICATION_MISSING'
            elif actual_cst!=expected_cst and actual_cc!=expected_cc:class_status='DOCUMENT_CST_CCLASS_DIVERGENT'
            elif actual_cst!=expected_cst:class_status='DOCUMENT_CST_DIVERGENT'
            else:class_status='DOCUMENT_CCLASS_DIVERGENT'
        evidence={'ncm':ncm,'ex_code':ex_code,'actual_cst':actual_cst,'actual_cclass_trib':actual_cc,'expected_cst':expected_cst,'expected_cclass_trib':expected_cc,'strategy':match.get('strategy'),'parameter_source_row':entry.source_row if entry else None,'catalog_version_id':catalog.version_id}
        if class_status!='MATCH_EXACT':
            sev='high' if 'DIVERGENT' in class_status or class_status in {'PARAMETER_INVALID','AMBIGUOUS_PARAMETERIZATION'} else 'medium'
            findings.append(finding('NCM-CLASS-001',sev,'ncm_class_trib','Divergência NCM × ClassTrib',f'Situação identificada: {class_status}.',document_ref,nitem,evidence,'Pode comprometer o enquadramento fiscal, a alíquota e a apuração assistida.','Revisar a parametrização e o XML conforme o catálogo vigente.'))
        if has_base_group and not special and abs(base_xml-base_calc)>CENT:
            findings.append(finding('UB16-10-BASE-001','medium','calculation','Conferência assistida da base IBS/CBS','A base diverge da fórmula recuperada UB16-10; confirmar vigência e exceções antes de corrigir.',document_ref,nitem,{'base_xml':str(base_xml),'base_recalculated':str(base_calc),'difference':str(base_xml-base_calc),'components':{k:str(v) for k,v in components.items()}},'Pode alterar os débitos de IBS e CBS.','Reprocessar o cálculo do item e revisar os componentes da base.'))
        if abs(ibs_xml-ibs_calc)>CENT or abs(cbs_xml-cbs_calc)>CENT:
            findings.append(finding('IBS-CBS-VALUE-001','high','calculation','IBS/CBS divergente','Os tributos destacados divergem do recálculo item a item.',document_ref,nitem,{'ibs_xml':str(ibs_xml),'ibs_recalculated':str(ibs_calc),'cbs_xml':str(cbs_xml),'cbs_recalculated':str(cbs_calc),'ibs_rate':str(ibs_rate),'cbs_rate':str(cbs_rate)},'Pode causar diferença na apuração.','Revisar alíquotas, base e arredondamento Decimal half-up.'))
        pis_base=_dec(tax,'.//n:PIS/*/n:vBC');pis_rate=_dec(tax,'.//n:PIS/*/n:pPIS');pis_xml=_money(_dec(tax,'.//n:PIS/*/n:vPIS'));pis_expected=_money(pis_base*pis_rate/Decimal('100'))
        cof_base=_dec(tax,'.//n:COFINS/*/n:vBC');cof_rate=_dec(tax,'.//n:COFINS/*/n:pCOFINS');cof_xml=_money(_dec(tax,'.//n:COFINS/*/n:vCOFINS'));cof_expected=_money(cof_base*cof_rate/Decimal('100'))
        # Em operações de veículos usados, PIS e COFINS normalmente compartilham a mesma base.
        # A base explícita do XML é preservada para conciliação exata; inferência por alíquota
        # combinada é usada apenas como fallback quando o documento não trouxer vBC.
        pis_cofins_base=_money(pis_base or cof_base)
        if (pis_base and abs(pis_xml-pis_expected)>ZERO) or (cof_base and abs(cof_xml-cof_expected)>ZERO):
            findings.append(finding('PIS-COFINS-ROUND-001','medium','rounding','Arredondamento de PIS/COFINS divergente','O valor informado diverge do arredondamento comercial para centavos.',document_ref,nitem,{'pis_base':str(pis_base),'pis_rate':str(pis_rate),'pis_xml':str(pis_xml),'pis_expected':str(pis_expected),'cofins_base':str(cof_base),'cofins_rate':str(cof_rate),'cofins_xml':str(cof_xml),'cofins_expected':str(cof_expected)},'A diferença propaga-se para a base IBS/CBS.','Padronizar o motor fiscal para Decimal ROUND_HALF_UP e validar a tolerância documental.'))
        used=_text(prod,'./n:indBemMovelUsado')=='1';additional=_text(det,'./n:infAdProd');identifiers=_additional_identifiers(additional)
        chassis=next((identifier['value'] for identifier in identifiers if identifier['type']=='chassis'),None);plate=next((identifier['value'] for identifier in identifiers if identifier['type']=='plate'),None)
        if chassis and ncm and not ncm.startswith('87'):
            findings.append(finding('NCM-VEHICLE-001','high','ncm','NCM incompatível com veículo','Item identificado como bem móvel usado/veículo está fora do capítulo 87.',document_ref,nitem,{'ncm':ncm,'description':_text(prod,'./n:xProd'),'chassis':chassis},'Pode afetar incidência, obrigações acessórias e Imposto Seletivo.','Revisar o cadastro fiscal do produto.'))
        tax_groups={}
        for group in ['ICMS','IPI','PIS','COFINS','IBSCBS','ISSQN','II','IS']:
            elements=tax.xpath(f'./n:{group}//*[not(*)]',namespaces=NS)
            values={etree.QName(element).localname:(element.text or '').strip() for element in elements if (element.text or '').strip()}
            if values:tax_groups[group]=values
        traceability=[]
        for trace in prod.xpath('./n:rastro',namespaces=NS):
            entry={key:value for key,value in {
                'lot':_text(trace,'./n:nLote'),'quantity':_text(trace,'./n:qLote'),
                'manufactured_at':_text(trace,'./n:dFab'),'expires_at':_text(trace,'./n:dVal'),
                'aggregation_code':_text(trace,'./n:cAgreg'),
            }.items() if value}
            if entry:
                traceability.append(entry)
                if entry.get('aggregation_code'):
                    identifiers.append({'type':'aggregation_code','value':entry['aggregation_code'],'source':'prod/rastro/cAgreg','confidence':'exact'})
        product_code=_text(prod,'./n:cProd') or None;ean=_text(prod,'./n:cEAN') or None;ean_taxable=_text(prod,'./n:cEANTrib') or None
        if product_code:identifiers.append({'type':'product_code','value':product_code,'source':'prod/cProd','confidence':'contextual'})
        if ean:identifiers.append({'type':'gtin','value':ean,'source':'prod/cEAN','confidence':'high'})
        if ean_taxable and ean_taxable!=ean:identifiers.append({'type':'gtin_taxable','value':ean_taxable,'source':'prod/cEANTrib','confidence':'high'})
        details={
            'tax_path_values':{'/'.join([etree.QName(a).localname for a in list(element.iterancestors())[:list(element.iterancestors()).index(tax)]][::-1]+[etree.QName(element).localname]):(element.text or '').strip() for element in tax.xpath('.//*[not(*)]')},
            'calculation_memory':{'rounding':'ROUND_HALF_UP','scale':2,'PIS':{'base':str(pis_base),'rate':str(pis_rate),'original':str(pis_xml),'recalculated':str(pis_expected),'scope':'ad_valorem' if tax.xpath('.//n:PIS/*/n:vBC',namespaces=NS) and tax.xpath('.//n:PIS/*/n:pPIS',namespaces=NS) else 'not_recalculated'},'COFINS':{'base':str(cof_base),'rate':str(cof_rate),'original':str(cof_xml),'recalculated':str(cof_expected),'scope':'ad_valorem' if tax.xpath('.//n:COFINS/*/n:vBC',namespaces=NS) and tax.xpath('.//n:COFINS/*/n:pCOFINS',namespaces=NS) else 'not_recalculated'}},
            'ean':ean,'ean_taxable':ean_taxable,
            'unit':_text(prod,'./n:uCom') or None,'quantity':_text(prod,'./n:qCom') or None,
            'unit_value':_text(prod,'./n:vUnCom') or None,'taxable_unit':_text(prod,'./n:uTrib') or None,
            'taxable_quantity':_text(prod,'./n:qTrib') or None,'taxable_unit_value':_text(prod,'./n:vUnTrib') or None,
            'origin':_text(tax,'.//n:ICMS/*/n:orig') or None,'icms_cst':_text(tax,'.//n:ICMS/*/n:CST') or _text(tax,'.//n:ICMS/*/n:CSOSN') or None,
            'pis_cst':_text(tax,'.//n:PIS/*/n:CST') or None,'cofins_cst':_text(tax,'.//n:COFINS/*/n:CST') or None,
            'additional_information':additional or None,'identifiers':identifiers,'traceability':traceability,'taxes':tax_groups,
        }
        item_data={'item_number':nitem,'product_code':product_code,'description':_text(prod,'./n:xProd') or None,'ncm':ncm or None,'ex_code':ex_code,'cfop':_text(prod,'./n:CFOP') or None,'actual_cst':actual_cst,'actual_cclass_trib':actual_cc,'expected_cst':expected_cst,'expected_cclass_trib':expected_cc,'classification_status':class_status,'product_value':str(_money(components['vProd'])),'ibs_cbs_base_xml':str(base_xml),'ibs_cbs_base_recalculated':str(base_calc),'base_difference':str(_money(base_xml-base_calc)),'ibs_xml':str(ibs_xml),'ibs_recalculated':str(ibs_calc),'cbs_xml':str(cbs_xml),'cbs_recalculated':str(cbs_calc),'tax_components':{k:str(v) for k,v in components.items()},'catalog_match':evidence,'details':details,'chassis':chassis,'plate':plate,'used_movable_good':used,'pis_cofins':str(_money(components['vPIS']+components['vCOFINS'])),'pis_cofins_base':str(pis_cofins_base)}
        item_data['calculation_scope']='unsupported_special' if special else 'regular' if has_base_group else 'absent'
        details['reconciliation_identity']=item_identity(item_data)
        items.append(item_data)
    total=sum((Decimal(i['product_value']) for i in items),ZERO);base=sum((Decimal(i['ibs_cbs_base_xml']) for i in items),ZERO);ibs=sum((Decimal(i['ibs_xml']) for i in items),ZERO);cbs=sum((Decimal(i['cbs_xml']) for i in items),ZERO)
    payments=[]
    for payment in inf.xpath('./n:pag/n:detPag',namespaces=NS):
        payments.append({'method':_text(payment,'./n:tPag'),'value':str(_money(_dec(payment,'./n:vPag'))),'description':_text(payment,'./n:xPag') or None})
    references=[value for value in inf.xpath('./n:ide/n:NFref/n:refNFe/text()',namespaces=NS) if value]
    invoice_total_names=['vBC','vICMS','vICMSDeson','vFCP','vBCST','vST','vFCPST','vFCPSTRet','vProd','vFrete','vSeg','vDesc','vII','vIPI','vIPIDevol','vPIS','vCOFINS','vOutro','vNF','vTotTrib']
    identification=_present({
        'model':_text(inf,'./n:ide/n:mod'),'series':_text(inf,'./n:ide/n:serie'),'number':_text(inf,'./n:ide/n:nNF'),
        'cUF':_text(inf,'./n:ide/n:cUF'),'cNF':_text(inf,'./n:ide/n:cNF'),'nature':_text(inf,'./n:ide/n:natOp'),
        'issued_at':issued_at,'exited_at':_iso(_text(inf,'./n:ide/n:dhSaiEnt') or _text(inf,'./n:ide/n:dSaiEnt')),
        'operation_type':tp_nf,'destination':_text(inf,'./n:ide/n:idDest'),'municipality_code':_text(inf,'./n:ide/n:cMunFG'),
        'print_type':_text(inf,'./n:ide/n:tpImp'),'emission_type':_text(inf,'./n:ide/n:tpEmis'),'check_digit':_text(inf,'./n:ide/n:cDV'),
        'purpose':_text(inf,'./n:ide/n:finNFe'),'consumer':_text(inf,'./n:ide/n:indFinal'),'presence':_text(inf,'./n:ide/n:indPres'),
        'process_type':_text(inf,'./n:ide/n:procEmi'),'process_version':_text(inf,'./n:ide/n:verProc'),'environment':_text(inf,'./n:ide/n:tpAmb'),
        'contingency_at':_iso(_text(inf,'./n:ide/n:dhCont')),'contingency_reason':_text(inf,'./n:ide/n:xJust'),'references':references,
    })
    billing=_present({
        'invoice_number':_text(inf,'./n:cobr/n:fat/n:nFat'),
        'original_value':str(_money(_dec(inf,'./n:cobr/n:fat/n:vOrig'))) if _text(inf,'./n:cobr/n:fat/n:vOrig') else None,
        'discount':str(_money(_dec(inf,'./n:cobr/n:fat/n:vDesc'))) if _text(inf,'./n:cobr/n:fat/n:vDesc') else None,
        'net_value':str(_money(_dec(inf,'./n:cobr/n:fat/n:vLiq'))) if _text(inf,'./n:cobr/n:fat/n:vLiq') else None,
        'installments':[_present({'number':_text(dup,'./n:nDup'),'due_at':_text(dup,'./n:dVenc'),'value':_text(dup,'./n:vDup')}) for dup in inf.xpath('./n:cobr/n:dup',namespaces=NS)],
    })
    transport=_present({
        'freight_mode':_text(inf,'./n:transp/n:modFrete'),'carrier':_party(inf,'./n:transp/n:transporta','enderTransporta'),
        'vehicle_plate':_text(inf,'./n:transp/n:veicTransp/n:placa'),'vehicle_state':_text(inf,'./n:transp/n:veicTransp/n:UF'),
        'vehicle_rntc':_text(inf,'./n:transp/n:veicTransp/n:RNTC'),
        'volumes':[_present({'quantity':_text(volume,'./n:qVol'),'kind':_text(volume,'./n:esp'),'brand':_text(volume,'./n:marca'),'numbering':_text(volume,'./n:nVol'),'net_weight':_text(volume,'./n:pesoL'),'gross_weight':_text(volume,'./n:pesoB')}) for volume in inf.xpath('./n:transp/n:vol',namespaces=NS)],
    })
    normalized={
        'issuer_name':_text(inf,'./n:emit/n:xNome'),'recipient_name':_text(inf,'./n:dest/n:xNome'),'nature':_text(inf,'./n:ide/n:natOp'),
        'identification':identification,
        'issuer':_party(inf,'./n:emit','enderEmit'),'recipient':_party(inf,'./n:dest','enderDest'),
        'totals':_money_map(inf,'./n:total/n:ICMSTot',invoice_total_names),
        'transport':transport,'billing':billing,
        'payments':payments,'additional_information':_present({'tax_authority':_text(inf,'./n:infAdic/n:infAdFisco'),'taxpayer':_text(inf,'./n:infAdic/n:infCpl')}),
        'protocol':{'number':_text(root,'.//n:protNFe/n:infProt/n:nProt'),'status_code':_text(root,'.//n:protNFe/n:infProt/n:cStat'),'status_reason':_text(root,'.//n:protNFe/n:infProt/n:xMotivo'),'received_at':_iso(_text(root,'.//n:protNFe/n:infProt/n:dhRecbto'))},
        'xml_sha256':sha256(data).hexdigest(),
    }
    doc={'document_ref':document_ref,'source_file_id':source_file_id,'access_key':access_key or None,'model':_text(inf,'./n:ide/n:mod') or None,'series':_text(inf,'./n:ide/n:serie') or None,'number':_text(inf,'./n:ide/n:nNF') or None,'issued_at':issued_at,'direction':direction,'status':'authorized' if _text(root,'.//n:protNFe/n:infProt/n:cStat') in {'100','150'} else 'parsed','issuer_tax_id':issuer,'recipient_tax_id':recipient,'total_value':str(_money(_dec(inf,'./n:total/n:ICMSTot/n:vNF') or total)),'ibs_cbs_base':str(_money(base)),'ibs_value':str(_money(ibs)),'cbs_value':str(_money(cbs)),'item_count':len(items),'normalized':normalized,'xml_storage_path':xml_storage_path,'danfe_storage_path':None,'items':items}
    return doc,findings
