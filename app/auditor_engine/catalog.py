from dataclasses import dataclass
from datetime import date
@dataclass(slots=True)
class ParamEntry:
    id:str;ncm:str;ex_code:str|None;expected_cst:str|None;expected_cclass_trib:str|None;description:str|None;status:str;validation_issues:list;source_row:int|None;reduction_type:str|None;valid_from:date|None;valid_to:date|None
class CatalogSnapshot:
    def __init__(self,snapshot=None):
        snapshot=snapshot or {}
        self.version_id=snapshot.get('sha256','sem-catalogo');self.issues=[];self.by_key={};self.cclass={};self.cst=set()
        for n,row in enumerate(snapshot.get('entries',[]),1):
            e=ParamEntry(str(n),row['ncm'],row.get('ex_code') or None,row['cst'],row['cclass_trib'],row.get('description'), 'valid', [],row.get('source_row',n),row.get('reduction_type'),
                         date.fromisoformat(snapshot['valid_from']),date.fromisoformat(snapshot['valid_to']))
            self.by_key.setdefault((e.ncm,e.ex_code),[]).append(e)
    def match(self,ncm:str|None,ex_code:str|None,issued_on:date|None):
        if not ncm:return {'status':'DOCUMENT_NCM_MISSING','entry':None,'strategy':'none'}
        candidates=self.by_key.get((ncm,ex_code)) if ex_code else self.by_key.get((ncm,None))
        strategy='NCM_EXACT_WITH_EX' if ex_code else 'NCM_EXACT'
        if not candidates and ex_code:candidates=self.by_key.get((ncm,None));strategy='NCM_FALLBACK_WITHOUT_EX'
        if not candidates:return {'status':'NCM_NOT_PARAMETERIZED','entry':None,'strategy':'none'}
        eligible=[e for e in candidates if (not issued_on or (not e.valid_from or e.valid_from<=issued_on) and (not e.valid_to or issued_on<=e.valid_to))]
        if not eligible:return {'status':'PARAMETER_OUT_OF_VALIDITY','entry':candidates[0],'strategy':strategy}
        if len(eligible)>1:return {'status':'AMBIGUOUS_PARAMETERIZATION','entry':eligible[0],'strategy':strategy,'candidates':len(eligible)}
        e=eligible[0]
        return {'status':'PARAMETER_INVALID' if e.status=='error' else 'MATCH','entry':e,'strategy':strategy}
