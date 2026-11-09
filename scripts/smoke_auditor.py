"""Smoke HTTP completo executado contra a imagem construída, sem importar seu motor no host."""
import base64
import json
import time
import urllib.request
from io import BytesIO
from zipfile import ZipFile
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.auditor_smoke import xml_fixture


def run(opener,url,session):
    def request(path,body=None):
        headers={'Content-Type':'application/json','X-CSRF-Token':session['csrf_token']}
        with opener.open(urllib.request.Request(url+'/api'+path,data=json.dumps(body).encode() if body is not None else None,headers=headers),timeout=40) as r:return json.load(r)
    company=request('/companies',{'code':'AUDIT-SMOKE','name':'AUDITOR SINTETICO','tax_id':'99999999000191','state':'SP','regime':'outros'})
    cid=company['id'];request('/context',{'company_id':cid,'module':'auditor','period':'2026-01'})
    cfop=request(f'/companies/{cid}/cfop-reference?date=2026-11-01')
    assert cfop['total']==619 and any(r['code']=='1102' for r in cfop['rows'])
    base=f'/companies/{cid}/auditor'
    raw=xml_fixture(company['tax_id'],2026).encode()
    created=request(base+'/jobs',{'mode':'standalone','start':'2026-01-01','end':'2026-12-31','idempotency_key':'image-auditor-smoke','files':[{'filename':'smoke.xml','content_base64':base64.b64encode(raw).decode()}]})
    for _ in range(120):
        job=request(base+f"/jobs/{created['id']}")
        if job['status'] not in {'queued','running'}:break
        time.sleep(.25)
    assert job['status']=='completed',job.get('error')
    assert job['result']['totals']['total_cents']==10000 and len(job['result']['documents'])==1
    assert len(job['reports'])==2
    reports={}
    for fmt in ('pdf','xlsx'):
        with opener.open(url+'/api'+base+f"/jobs/{job['id']}/report?format={fmt}",timeout=40) as r:data=r.read()
        if fmt=='pdf':assert data.startswith(b'%PDF') and b'%%EOF' in data[-100:]
        else:
            with ZipFile(BytesIO(data)) as archive:
                assert archive.testzip() is None
                assert 'Memória de Cálculo' in archive.read('xl/workbook.xml').decode()
        reports[fmt]=len(data)
    catalog=request(base+'/catalogs/reference',{'name':'Histórico original','valid_from':'2026-01-01','valid_to':'2026-12-31'})
    assert catalog['entry_count']==15638 and len(catalog['reference']['cclass'])==142
    assert request(f'/companies/{cid}/documents')==[]
    return {'job_id':job['id'],'documents':1,'total_cents':10000,'reports':reports,'catalog_rows':catalog['entry_count'],'cfop_codes':cfop['total'],'bookkeeping_unchanged':True}
