"""Reviewed errata for the bundled historical reference; never mutate source files."""
from copy import deepcopy

SOURCE_SHA = '9c5b0660b318bf1137fb830fea543df9e4afc24bfa395f6eb67d3b625bd3d81a'
SVRS = 'https://dfe-portal.svrs.rs.gov.br/DFE/ClassificacaoTributaria'
LAW = 'https://www.fazenda.mg.gov.br/export/sites/fazenda/empresas/legislacao_tributaria/leis/2025/lc214_2025.pdf'
# Changes are specific to original erroneous rows, not blanket NCM tax rules.
ERRATA = (
    (638, '03099000', {'cst':'2000','cclass_trib':'200038','reduction_type':'Redução de 60%'},
     {'cst':'200'}, 'Anexo IX, item 21 / art. 138',
     'Confirmar destinação direta à fabricação de ração ou alimentação animal, exceto animais domésticos.'),
    (1505, '15132120', {'cst':'200','cclass_trib':'200003','reduction_type':'Redução de 60%'},
     {'reduction_type':'Redução de 100%'}, 'Anexo I, item 9 / art. 125',
     'Óleo de babaçu em conformidade com os requisitos legais relativos ao consumo como alimento.'),
    (6024, '34011190', {'cst':'200','cclass_trib':None,'reduction_type':'Sem redução'},
     {'cclass_trib':'200035','reduction_type':'Redução de 60%'}, 'Anexo VIII, item 1 / art. 136',
     'Confirmar que o produto é sabão de toucador; o NCM isolado não comprova essa condição.'),
)


def corrected_reference(entries, reference):
    """Return a separate reviewed draft; customized rows are never overwritten."""
    from .core import DomainError
    sources = reference.get('manifest', {}).get('sources', [])
    if not any(s.get('sha256') == SOURCE_SHA for s in sources):
        raise DomainError('As erratas verificadas são exclusivas da referência histórica 1.2.2.')
    entries, reference = deepcopy(entries), deepcopy(reference)
    changes = []
    for source_row, ncm, expected, patch, basis, condition in ERRATA:
        for row in entries:
            if row.get('source_row') != source_row or row.get('ncm') != ncm:
                continue
            if any(row.get(k) != v for k, v in expected.items()):
                continue
            before = {k:row.get(k) for k in patch}
            row.update(patch, status='valid', validation_issues=[])
            existing_conditions = row.get('conditions') or []
            row['conditions'] = (existing_conditions if isinstance(existing_conditions,list) else [existing_conditions]) + [condition]
            row['requires_condition_review'] = True
            row['correction_evidence'] = {'source_row':source_row,'before':before,'after':patch,
                'legal_basis':basis,'sources':[SVRS,LAW],'verified_at':'2026-11-13'}
            changes.append(row['correction_evidence'])
    reference['verified_errata'] = {'verified_at':'2026-11-13','changes':changes,
        'scope':'Correções pontuais; não representa homologação integral ou atualização de toda a referência.'}
    return entries, reference
