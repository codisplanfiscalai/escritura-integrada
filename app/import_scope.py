"""Elegibilidade de lotes anuais, reavaliada antes de qualquer gravação."""
from .core import DomainError, ensure_open, iso_date

def eligibility(conn,cid,module,day,year):
    try:
        day=iso_date(day)
        if day[:4]!=str(year):return {'status':'outside_year','reason':'Fora do exercício selecionado','period':day[:7]}
        ensure_open(conn,cid,day[:7],module)
        return {'status':'eligible','reason':'Elegível','period':day[:7]}
    except DomainError as e:
        return {'status':'blocked','reason':e.detail,'code':e.code,'period':str(day or '')[:7]}

def classify(conn,cid,parsed,year):
    for kind,module,field in [('documents','fiscal','posting_date'),('transactions','financial','date')]:
        for index,row in enumerate(parsed.get(kind,[])):
            row['_selection']=f'{kind}:{index}'
            row['_eligibility']=eligibility(conn,cid,module,row.get(field),year)
    return parsed

def selected_rows(parsed,payload):
    all_rows=[r for k in ('documents','transactions','records') for r in parsed.get(k,[])]
    ids=[r['_selection'] for r in all_rows]
    selected=payload.get('selected')
    if selected is None:
        if all_rows and all(r['_eligibility'].get('code')=='period_closed' for r in all_rows):
            raise DomainError(all_rows[0]['_eligibility']['reason'],409,'period_closed')
        if any(r['_eligibility']['status']!='eligible' for r in all_rows):
            raise DomainError('O lote contém recusas. Selecione explicitamente os registros elegíveis.',409,'selection_required')
        selected=ids
    if not isinstance(selected,list) or not selected or len(set(selected))!=len(selected) or any(x not in ids for x in selected):
        raise DomainError('Seleção de registros inválida.')
    for r in all_rows:
        if r['_selection'] in selected and r['_eligibility']['status']!='eligible':
            raise DomainError(r['_eligibility']['reason'],409,'import_blocked')
    return set(selected)
