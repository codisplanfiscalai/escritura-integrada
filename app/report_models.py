"""Modelos com evidência explícita; impressão Razão baseada no exemplar fornecido."""
from io import BytesIO
from decimal import Decimal
import re
import textwrap
from .core import DomainError

CATALOG=[
 {'id':'prosoft-ledger-v1','name':'Razão Analítico Individual','kind':'ledger','source':'RAZAO_CAIXA_082026_REENVIADO.PDF, 7 folhas (00002–00008)','evidence':'Cabeçalhos, 9 colunas, conta, saldo anterior, saldo diário, saldo final, continuação e geometria 794 × 1122','status':'numeric_validated_visual_partial','limitations':'Comparação numérica sem diferenças; tipografia e algumas quebras ainda diferem do exemplar. Número inicial de folha configurável. Contrapartidas múltiplas explicitadas como Diversos.'},
 *[{'id':'internal-'+kind,'kind':kind,'name':name,'source':source,'evidence':'Campos, filtros e totalizações recuperados; relatório operacional do Escritura','status':'operational_reference_pending','limitations':'Falta saída impressa equivalente com os mesmos dados e filtros para certificar aparência Prosoft.'} for kind,name,source in [
 ('diary','Diário Geral','CTB020600 / formulários'),('consolidated-diary','Diário Consolidado','CTB020800 / formulários'),('trial-balance','Balancete','CTB021400 / formulários'),('balance-sheet','Balanço','CTB030200 / formulários; saída impressa ausente'),('income-statement','Demonstração do resultado','CTB021400 / opção DRE'),('cost-centers','Centro de custo','CTB020700, CTB021500 e CTB021700 / variantes'),('fiscal-entries','Livro de entradas','LFSLIVROS / formulários'),('fiscal-outputs','Livro de saídas','LFSLIVROS / formulários'),('fiscal-assessments','Apurações','LFSLIVROSAPUR / formulários')]]]


def ledger_pdf(result,first_page=1,show_numbers=False):
    if result['kind']!='ledger':raise DomainError('Modelo disponível somente para Razão.')
    if not 1<=first_page<=99999:raise DomainError('Folha inicial deve estar entre 1 e 99999.')
    from reportlab.pdfgen import canvas
    out=BytesIO();c=canvas.Canvas(out,pagesize=(794,1122));c.setTitle('Razão Analítico Individual');c.setAuthor('Escritura Integrada')
    page=first_page;printed=False
    def draw(x,top,value,bold=False,size=9,right=False):
        value=str(value or '');font='Courier-Bold' if bold else 'Courier'
        c.setFont(font,size)
        if right:c.drawRightString(x,1122-top-7,value)
        else:c.drawString(x,1122-top-7,value)
    def money(v):return f'{Decimal(abs(v))/100:,.2f}'.replace(',','X').replace('.',',').replace('X','.')
    def balance(top,v):draw(733,top,money(v),right=True);draw(750,top,'D' if v>=0 else 'C')
    def date(v):return '/'.join(v.split('-')[::-1])
    def header(group,continuation=False):
        for top in [47,71,116,141,166]:c.setLineWidth(.5);c.line(43,1122-top,790,1122-top)
        draw(43,55,'RAZÃO ANALÍTICO INDIVIDUAL',True,10);draw(659,55,'Folha:',True,10);draw(732,55,f'{page:05d}')
        draw(43,79,'Empresa:',True,10);draw(101,82,str(result.get('company_code',''))+' '+result['company_name'])
        tax=result.get('company_tax_id','');tax=re.sub(r'^(.{2})(.{3})(.{3})(.{4})(.{2})$',r'\1.\2.\3/\4-\5',tax)
        draw(43,97,'CNPJ:',True,10);draw(122,97,tax)
        draw(43,121,'Período:',True,10);draw(108,121,date(result['start'])+' a '+date(result['end']))
        for x,label in [(43,'LCTO'),(103,'DCTO'),(160,'DATA'),(216,'C/PART.'),(276,'C/C'),(316,'H I S T Ó R I C O'),(497,'DÉBITO'),(590,'CRÉDITO'),(702,'SALDO')]:draw(x,148,label,True,10)
        draw(43,174,'Conta');draw(75,174,group.get('access_code'));draw(120,174,group.get('classifier'));draw(206,174,group.get('account_name'))
        if continuation:draw(732,174,'(C.)')
    groups=result.get('ledger_groups') or []
    if not groups:groups=[{'account_name':'Sem movimentos no período','rows':[],'opening_cents':0}]
    for group in groups:
        if printed:c.showPage();page+=1
        printed=True;header(group);slot=0
        def top():return int(186.666666+slot*40/3)+.746
        draw(316,top(),'SALDO ANTERIOR................');balance(top(),group['opening_cents']);slot+=1
        lines=group['rows'];debits=credits=0;closing=group['opening_cents']
        for index,row in enumerate(lines):
            history=textwrap.wrap(str(row.get('history','')),width=32,replace_whitespace=False,drop_whitespace=True) or ['']
            for part,line in enumerate(history):
                if top()>1041:c.showPage();page+=1;header(group,True);slot=0
                y=top()
                if part==0:
                    if show_numbers:draw(43,y,row.get('number'));draw(103,y,str(row.get('document',''))[:9])
                    draw(160,y,date(row['date'])[:5]);draw(216,y,row.get('counterpart',''));draw(276,y,str(row.get('cost_center_code',''))[:6])
                draw(316,y,line)
                if part==len(history)-1:
                    if row['debit_cents']:draw(560,y,money(row['debit_cents']),right=True)
                    if row['credit_cents']:draw(646,y,money(row['credit_cents']),right=True)
                    debits+=row['debit_cents'];credits+=row['credit_cents'];closing+=row['debit_cents']-row['credit_cents']
                    if index==len(lines)-1 or lines[index+1]['date']!=row['date']:balance(y,closing)
                slot+=1
        if top()>1041:c.showPage();page+=1;header(group,True);slot=0
        draw(316,top(),'SALDO FINAL...................');draw(560,top(),money(debits),right=True);draw(646,top(),money(credits),right=True);balance(top(),closing)
    c.save();return out.getvalue(),'application/pdf'
