"""Read-only acervo metadata; original XML and bookkeeping dates are never changed.

NF-e: infNFe/emit,dest. NFS-e: infNFSe/DPS/infDPS/prest,toma,interm
(NT 008/2026 DANFSe field mapping). Missing/ambiguous identities stay unknown.
"""
import re
from .importers import _xml_tree
NFE='http://www.portalfiscal.inf.br/nfe'
NFSE='http://www.sped.fazenda.gov.br/nfse'

def path(root,value,namespace):
    return root.findall('/'.join('{'+namespace+'}'+p for p in value.split('/')))

def text(root,value,namespace):
    nodes=path(root,value,namespace)
    return nodes[0].text.strip() if len(nodes)==1 and nodes[0].text and len(nodes[0].text)<=256 else ''

def identity(root,namespace):
    nodes=root.findall('{'+namespace+'}CNPJ')+root.findall('{'+namespace+'}CPF')
    if len(nodes)!=1 or not nodes[0].text:return ''
    value=nodes[0].text.strip()
    return value if re.fullmatch(r'(?:[0-9A-Z]{12}[0-9]{2}|[0-9]{11})',value) else ''

def classify(raw,provider,target):
    root=_xml_tree(raw)
    result={'direction':'unknown','company_roles':[]}
    if provider=='nfe_distribution':
        infos=path(root,'NFe/infNFe',NFE) if root.tag=='{'+NFE+'}nfeProc' else []
        namespace=NFE;issuer='emit';recipient='dest';intermediary=None
        if len(infos)!=1:return result
        info=infos[0]
        key=info.get('Id','')
        if re.fullmatch(r'NFe[0-9A-Z]{44}',key):result['xml_access_key']=key[3:]
        result['issue_date']=text(info,'ide/dhEmi',namespace) or text(info,'ide/dEmi',namespace)
        result['number']=text(info,'ide/nNF',namespace)
    else:
        infos=path(root,'infNFSe/DPS/infDPS',NFSE) if root.tag=='{'+NFSE+'}NFSe' else []
        namespace=NFSE;issuer='prest';recipient='toma';intermediary='interm'
        if len(infos)!=1:return result
        info=infos[0]
        result['declared_competence']=text(info,'dCompet',namespace)
        result['issue_date']=text(info,'dhEmi',namespace)
        result['number']=text(root,'infNFSe/nNFSe',namespace)
    parties={}
    for role,field in [('issuer',issuer),('recipient',recipient),('intermediary',intermediary)]:
        if not field:continue
        nodes=path(info,field,namespace)
        if len(nodes)>1:return {'direction':'unknown','company_roles':[]}
        node=nodes[0] if nodes else None
        value=identity(node,namespace) if node is not None else ''
        parties[role]=value
        if role=='issuer':
            result['issuer_tax_id']=value
            result['issuer_name']=text(node,'xNome',namespace) if node is not None else ''
        if value==target:result['company_roles'].append(role)
    emitted='issuer' in result['company_roles']
    received=bool(set(result['company_roles'])&{'recipient','intermediary'})
    result['direction']='both' if emitted and received else 'issued' if emitted else 'received' if received else 'unknown'
    return result
