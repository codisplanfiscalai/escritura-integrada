"""Modelos com evidência explícita; impressão Razão baseada no exemplar fornecido."""
from io import BytesIO
from decimal import Decimal
import re
import textwrap
from .core import DomainError
from .fiscal_reports import FISCAL_REPORTS

CATALOG=[
 {'id':'prosoft-ledger-v1','name':'Razão Analítico Individual','kind':'ledger','source':'RAZAO_CAIXA_082026_REENVIADO.PDF, 7 folhas (00002–00008)','evidence':'Cabeçalhos, 9 colunas, conta, saldo anterior, saldo diário, saldo final, continuação e geometria 794 × 1122','status':'numeric_validated_visual_partial','limitations':'Comparação numérica sem diferenças; tipografia e algumas quebras ainda diferem do exemplar. Número inicial de folha configurável. Contrapartidas múltiplas explicitadas como Diversos.'},
 *[{'id':mid,'name':name,'kind':kind,'source':'Livros fiscais fornecidos de setembro/2026, modelos P1/A e P2/A',
    'evidence':'Quadro ICMS em paisagem 842 × 595, cabeçalhos hierárquicos, grade, transportes e resumo por CFOP sem alterar as linhas',
    'status':'reference_layout_partial_not_homologated','supported':True,
    'limitations':'Em homologação. Campos ausentes em branco; códigos contábeis não inferidos. Anexos IPI, UF e observações não reproduzidos. Não certifica aceite Prosoft.'}
   for mid,name,kind in [('reference-entries-p1a-v1','Registro de entradas P1/A — quadro ICMS','fiscal-entries'),
                         ('reference-outputs-p2a-v1','Registro de saídas P2/A — quadro ICMS','fiscal-outputs')]],
 *[{'id':'internal-'+kind,'kind':kind,'name':name,'source':source,
    'evidence':'Campos e variantes recuperados; impressão baseada nos campos, layout não homologado',
    'status':'field_based_not_homologated','supported':True,
    'limitations':'Falta exemplar impresso equivalente para certificar aparência Prosoft. Não equivale a livro legal homologado.'}
   for kind,name,source in [
    ('diary','Diário Geral','CTB020600 / formulários'),
    ('consolidated-diary','Diário Consolidado','CTB020800 / formulários'),
    ('trial-balance','Balancete','CTB021400 / formulários'),
    ('balance-sheet','Balanço patrimonial','CTB030200 / formulários; saída impressa ausente'),
    ('income-statement','Demonstração do resultado','CTB021400 / opção DRE'),
    ('cost-centers','Centro de custo','CTB020700, CTB021500 e CTB021700 / variantes'),
    *[(kind,name,'LFSLIVROSAPUR / formulários' if kind=='fiscal-assessments' else 'LFSLIVROS / formulários; agrupamentos operacionais do Escritura')
      for kind,name in FISCAL_REPORTS.items()]] if kind not in {'fiscal-entries','fiscal-outputs'}]]
CATALOG[0]['supported'] = True

# URLs antigas continuam funcionando, mas não reintroduzem impressões
# genéricas ou alternativas auxiliares já substituídas no catálogo.
MODEL_ALIASES = {
    'internal-fiscal-entries': 'reference-entries-p1a-v1',
    'internal-fiscal-outputs': 'reference-outputs-p2a-v1',
}


def resolve_model_id(kind, requested='internal'):
    if requested in (None, '', 'internal'):
        selected = next((m for m in CATALOG if m['kind'] == kind and m.get('supported', True)), None)
        return selected['id'] if selected else None
    requested = MODEL_ALIASES.get(requested, requested)
    if not any(m['id'] == requested and m['kind'] == kind and m.get('supported', True) for m in CATALOG):
        raise DomainError('Modelo incompatível com o relatório.')
    return requested


def report_model_pdf(result, model_id, first_page=1, show_numbers=False):
    """Despacha apenas pares modelo/relatório explicitamente cadastrados."""
    from .accounting_report_models import accounting_pdf, validate_first_page
    validate_first_page(first_page)
    model_id = resolve_model_id(result.get('kind'), model_id)
    model = next((item for item in CATALOG if item['id'] == model_id), None)
    if model is None:
        raise DomainError('Modelo de impressão não encontrado.', 404)
    if model['kind'] != result.get('kind'):
        raise DomainError('Modelo de impressão incompatível com o relatório selecionado.')
    if model_id in {'reference-entries-p1a-v1', 'reference-outputs-p2a-v1'}:
        from .fiscal_book_models import fiscal_book_pdf
        return fiscal_book_pdf(result, model_id, first_page)
    if model_id == 'prosoft-ledger-v1':
        return ledger_pdf(result, first_page, show_numbers)
    if result['kind'] in FISCAL_REPORTS:
        from .fiscal_report_models import fiscal_pdf
        return fiscal_pdf(result, first_page=first_page, show_numbers=show_numbers)
    return accounting_pdf(result, first_page=first_page, show_numbers=show_numbers)



def ledger_pdf(result,first_page=1,show_numbers=False):
    if result['kind']!='ledger':raise DomainError('Modelo disponível somente para Razão.')
    from .accounting_report_models import validate_first_page
    validate_first_page(first_page)
    from reportlab.pdfgen import canvas
    out=BytesIO();c=canvas.Canvas(out,pagesize=(794,1122));c.setTitle('Razão Analítico Individual');c.setAuthor('Escritura Integrada')
    page=first_page;printed=False
    def draw(x,top,value,bold=False,size=9,right=False,char_space=0,word_space=0):
        value=str(value or '');font='Courier-Bold' if bold else 'Courier'
        baseline=1122-top-(8 if size==10 else 7)
        if right:x-=c.stringWidth(value,font,size)+max(0,len(value)-1)*char_space+value.count(' ')*word_space
        text=c.beginText(x,baseline);text.setFont(font,size)
        text.setCharSpace(char_space);text.setWordSpace(word_space);text.textOut(value);c.drawText(text)
    def money(v):return f'{Decimal(abs(v))/100:,.2f}'.replace(',','X').replace('.',',').replace('X','.')
    # Visible right edges measured in the supplied model (16-column money fields).
    debit_right,credit_right,balance_right=560.4,645.4,733.4
    def balance(top,v):draw(balance_right,top,money(v),right=True);draw(750,top,'D' if v>=0 else 'C')
    def date(v):return '/'.join(v.split('-')[::-1])
    def header(group,continuation=False):
        if page>99999:raise DomainError('Paginação excede a folha 99999.')
        for top in [47,71,116,141,166]:c.setLineWidth(.5);c.line(43,1122-top,790,1122-top)
        draw(43,55,'RAZÃO ANALÍTICO INDIVIDUAL',True,10,char_space=-.833,word_space=-3);draw(659,55,'Folha:',True,10,char_space=-1.2);draw(732,55,f'{page:05d}',size=10,char_space=-1.25)
        draw(43,79,'Empresa:',True,10,char_space=-1);draw(101,82,str(result.get('company_code',''))+' '+result['company_name'],word_space=-2.2)
        tax=result.get('company_tax_id','');tax=re.sub(r'^(.{2})(.{3})(.{3})(.{4})(.{2})$',r'\1.\2.\3/\4-\5',tax)
        draw(43,97,'CNPJ:',True,10,char_space=-1.25);draw(122,97,tax,size=10,char_space=-1.059)
        draw(43,121,'Período:',True,10,char_space=-1);draw(108,121,date(result['start'])+' a '+date(result['end']),size=10,char_space=-.81,word_space=-3)
        if group.get('filtered'):
            draw(43,130,'Pesquisa restringe movimentos exibidos, saldos incluem todos os movimentos.',size=7)
        for x,label,spacing in [(43,'LCTO',-1.333),(103,'DCTO',-1.333),(160,'DATA',-1.333),(216,'C/PART.',-1.167),(276,'C/C',-1.5),(316,'H I S T Ó R I C O',0),(497,'DÉBITO',0),(590.142,'CRÉDITO',-.429),(702,'SALDO',-1.25)]:draw(x,148,label,True,10,char_space=spacing,word_space=-2.125 if x==316 else 0)
        draw(43,174,'Conta',True,char_space=-.4);draw(75,174,group.get('access_code'),char_space=-.5);draw(120,174,group.get('classifier'),char_space=-.444);draw(206,174,group.get('account_name'),word_space=-.5)
        if continuation:draw(732,174,'(C.)')
    groups=result.get('ledger_groups') or []
    if not groups:groups=[{'account_name':'Sem movimentos no período','rows':[],'opening_cents':0}]
    for group in groups:
        if printed:c.showPage();page+=1
        printed=True;header(group);slot=0
        def top():return (560+slot*40)//3+1
        draw(316,top(),'SALDO ANTERIOR................',char_space=-.321,word_space=-2.7);balance(top(),group['opening_cents']);slot+=1
        lines=group['rows'];debits=credits=0;closing=group['opening_cents']
        for index,row in enumerate(lines):
            history=textwrap.wrap(str(row.get('history','')),width=32,replace_whitespace=False,drop_whitespace=True) or ['']
            for part,line in enumerate(history):
                if top()>1041:c.showPage();page+=1;header(group,True);slot=0
                y=top()
                if part==0:
                    if show_numbers:draw(43,y,row.get('number'));draw(103,y,str(row.get('document') or '')[:9])
                    draw(160,y,date(row['date'])[:5],char_space=-.5);draw(216,y,row.get('counterpart',''),char_space=-.5);draw(276,y,str(row.get('cost_center_code') or '')[:6])
                draw(316,y,line,word_space=-2.5)
                if part==len(history)-1:
                    if row['debit_cents']:draw(debit_right,y,money(row['debit_cents']),right=True)
                    if row['credit_cents']:draw(credit_right,y,money(row['credit_cents']),right=True)
                    debits+=row['debit_cents'];credits+=row['credit_cents'];closing=row.get('balance_cents',closing+row['debit_cents']-row['credit_cents'])
                    if index==len(lines)-1 or lines[index+1]['date']!=row['date']:balance(y,closing)
                slot+=1
        if top()>1041:c.showPage();page+=1;header(group,True);slot=0
        draw(316,top(),'SALDO FINAL...................',char_space=-.321,word_space=-2.7);draw(debit_right,top(),money(debits),right=True);draw(credit_right,top(),money(credits),right=True);balance(top(),group.get('closing_cents',closing))
        c.setLineWidth(.5);c.line(43,1122-top()-19,790,1122-top()-19)
    c.save();return out.getvalue(),'application/pdf'
