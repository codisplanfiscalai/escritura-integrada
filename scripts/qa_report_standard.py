"""Matriz PDF sintética reproduzível; não lê dados operacionais."""
from pathlib import Path
from copy import deepcopy
from io import BytesIO
import json, subprocess, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from pypdf import PdfReader
from app.report_models import CATALOG,report_model_pdf
from test_accounting_report_models import fixture
from test_fiscal_report_models import sample as fiscal
from test_fiscal_book_models import sample as book
out=ROOT/'artifacts'/'report-standard';out.mkdir(parents=True,exist_ok=True)
coverage=[]
for model in CATALOG:
    kind=model['kind']
    for count in [0,45]:
        result=book(kind=='fiscal-entries',count) if kind in ['fiscal-entries','fiscal-outputs'] else fiscal(kind,count) if kind.startswith('fiscal-') and kind!='fiscal-book' else fixture(kind,count)
        if kind=='ledger':result['ledger_groups']=[dict(account_name='Conta sintética',opening_cents=0,rows=result['rows'])]
        if count and kind not in ['fiscal-entries','fiscal-outputs','ledger']:result['rows'][0]['description']='Descrição extensa sintética '*20+' FIM-DESCRICAO'
        if kind=='bank-movements':
            for row in result['rows']:row.update(bank_account='CONTA SINTETICA',inflow_cents=12345,outflow_cents=0,balance_cents=None,opening_cents=None,closing_cents=None)
            result['totals'].update(opening_cents=None,closing_cents=None)
        before=deepcopy(result);raw,_=report_model_pdf(result,model['id'],first_page=7)
        assert before==result
        path=out/f'{kind}-{count}.pdf';path.write_bytes(raw)
        pdf=PdfReader(BytesIO(raw));coverage.append(dict(kind=kind,count=count,pages=len(pdf.pages),unchanged=True))
        if count:
            for page,suffix in [(1,''),(len(pdf.pages),'-last')]:
                subprocess.run(['pdftoppm','-scale-to','1100','-f',str(page),'-singlefile','-png',str(path),str(path.with_suffix(''))+suffix],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
(out/'coverage.json').write_text(json.dumps(coverage,indent=2))
print(len(coverage),'PDF cases generated')
