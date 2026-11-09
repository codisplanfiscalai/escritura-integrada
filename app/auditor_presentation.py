"""Agregações de apresentação do Auditor; não cria regras ou efeitos fiscais."""
from collections import Counter
from decimal import Decimal

COMPONENTS = ['vProd','vServ','vFrete','vSeg','vOutro','vII','vDesc','vPIS','vCOFINS','vICMS','vICMSUFDest','vFCP','vFCPUFDest','vICMSMono','vISSQN','vIS']
DEDUCTIONS = {'vDesc','vPIS','vCOFINS','vICMS','vICMSUFDest','vFCP','vFCPUFDest','vICMSMono','vISSQN'}
SEVERITY_ORDER = {'critical':0,'high':1,'medium':2,'low':3,'info':4}

def decimal(value):
    return Decimal(str(value or 0))

def eligible(document):
    return document.get('status') not in {'cancelled','outside_period'}

def counterpart(document):
    n=document.get('normalized') or {}
    side='issuer' if document.get('direction')=='entrada' else 'recipient'
    return (n.get(side) or {}).get('name') or n.get(side+'_name') or n.get('partner_name') or document.get(side+'_tax_id') or 'Não informado'

def analysis_details(documents,findings):
    active=[d for d in documents if eligible(d)]
    pairs=[(d,i) for d in active for i in d.get('items',[])]
    # Somente cenários efetivamente recalculados podem integrar o comparativo.
    comparable=[(d,i) for d,i in pairs if i.get('calculation_scope','legacy') in {'regular','legacy'}]
    components=[{'code':k,'sign':'-' if k in DEDUCTIONS else '+',
        'value':str(sum((decimal(i.get('tax_components',{}).get(k)) for _,i in comparable),Decimal(0)))} for k in COMPONENTS]
    taxes=[]
    for label,original,recalculated in [('Base IBS/CBS','ibs_cbs_base_xml','ibs_cbs_base_recalculated'),('IBS','ibs_xml','ibs_recalculated'),('CBS','cbs_xml','cbs_recalculated')]:
        original_value=sum((decimal(i.get(original)) for _,i in comparable),Decimal(0))
        recalc=sum((decimal(i.get(recalculated)) for _,i in comparable),Decimal(0))
        taxes.append({'label':label,'original':str(original_value),'recalculated':str(recalc),'difference':str(original_value-recalc),'items':len(comparable)})
    open_findings=[f for f in findings if f.get('status','open') in {'open','reviewing'}]
    return {'components':components,'tax_comparison':taxes,'comparable_items':len(comparable),
        'excluded_documents':len(documents)-len(active),'not_recalculated_items':len(pairs)-len(comparable),
        'open_findings':len(open_findings),'classification_ok':sum(i.get('classification_status')=='MATCH_EXACT' for _,i in pairs),
        'priorities':sorted(open_findings,key=lambda f:(SEVERITY_ORDER.get(f['severity'],9),f.get('id',0)))[:10],
        'coverage_counts':dict(Counter(i.get('calculation_scope','legacy') for _,i in pairs))}
