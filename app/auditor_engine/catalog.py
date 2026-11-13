from dataclasses import dataclass
from datetime import date
@dataclass(slots=True)
class ParamEntry:
    id:str;ncm:str;ex_code:str|None;expected_cst:str|None;expected_cclass_trib:str|None;description:str|None;status:str;validation_issues:list;source_row:int|None;reduction_type:str|None;valid_from:date|None;valid_to:date|None;conditions:object=None;requires_condition_review:bool=False
class CatalogSnapshot:
    def __init__(self,snapshot=None):
        snapshot=snapshot or {}
        self.version_id=snapshot.get('sha256','sem-catalogo');self.issues=[];self.by_key={};self.cclass={};self.cst=set()
        reference=snapshot.get('reference') or {}
        self.cclass={r['cclass_trib']:r for r in reference.get('cclass',[])}
        self.cst={r['cst'] for r in reference.get('cst',[])}
        for n,row in enumerate(snapshot.get('entries',[]),1):
            if row.get('ncm_level','item')!='item':continue
            ex=row.get('ex_code') or None
            if ex and ex.isdigit():ex=ex.zfill(2)
            e=ParamEntry(str(n),row['ncm'],ex,row.get('cst'),row.get('cclass_trib'),row.get('description'), row.get('status','valid'), row.get('validation_issues',[]),row.get('source_row',n),row.get('reduction_type'),
                         max(date.fromisoformat(row.get('valid_from') or snapshot['valid_from']),date.fromisoformat(snapshot['valid_from'])),min(date.fromisoformat(row.get('valid_to') or snapshot['valid_to']),date.fromisoformat(snapshot['valid_to'])),row.get('conditions'),bool(row.get('requires_condition_review')))
            self.by_key.setdefault((e.ncm,e.ex_code),[]).append(e)
    def match(self,ncm:str|None,ex_code:str|None,issued_on:date|None):
        if not ncm:return {'status':'DOCUMENT_NCM_MISSING','entry':None,'strategy':'none'}
        if ex_code and ex_code.isdigit():ex_code=ex_code.zfill(2)
        candidates=self.by_key.get((ncm,ex_code)) if ex_code else self.by_key.get((ncm,None))
        strategy='NCM_EXACT_WITH_EX' if ex_code else 'NCM_EXACT'
        if not candidates and ex_code:candidates=self.by_key.get((ncm,None));strategy='NCM_FALLBACK_WITHOUT_EX'
        if not candidates:return {'status':'NCM_NOT_PARAMETERIZED','entry':None,'strategy':'none'}
        eligible=[e for e in candidates if (not issued_on or (not e.valid_from or e.valid_from<=issued_on) and (not e.valid_to or issued_on<=e.valid_to))]
        if not eligible:return {'status':'PARAMETER_OUT_OF_VALIDITY','entry':candidates[0],'strategy':strategy}
        if len(eligible)>1:return {'status':'AMBIGUOUS_PARAMETERIZATION','entry':eligible[0],'strategy':strategy,'candidates':len(eligible)}
        e=eligible[0]
        if e.status!='error' and e.requires_condition_review:
            return {'status':'CONDITION_REVIEW_REQUIRED','entry':e,'strategy':strategy}
        return {'status':'PARAMETER_INVALID' if e.status=='error' else 'MATCH','entry':e,'strategy':strategy}
