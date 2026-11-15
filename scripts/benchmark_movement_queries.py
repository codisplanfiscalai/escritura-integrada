"""Comparable synthetic movement queries; never opens an existing application database."""
import argparse
import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--label',default='')
    parser.add_argument('--source-sha',default='')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repetitions',type=int,default=5)
    args=parser.parse_args();repo=args.repo.resolve();sys.path.insert(0,str(repo))
    if args.repetitions < 1: parser.error('--repetitions must be positive')
    with tempfile.TemporaryDirectory(prefix='movement-bootstrap-') as bootstrap, tempfile.TemporaryDirectory(prefix='movement-synthetic-') as folder:
        os.environ['ESCRITURA_DATA_DIR']=bootstrap;os.environ['ESCRITURA_DEMO']='0'
        from app.api import create_app
        from fastapi.testclient import TestClient
        from scripts.benchmark_workspace import seed_workspace
        app=create_app(folder,demo=True);core=app.state.core
        core.create_exercise(1,{"module":"accounting","year":2025},"synthetic")
        with core.db.transaction() as conn:
            accounts={r['access_code']:r['id'] for r in conn.execute('SELECT * FROM accounts WHERE company_id=1')}
            for period in ['2025-09','2026-08','2026-09']:
                for i in range(100):
                    core._create_journal(conn,1,{'date':period+'-10','document':f'SYN-{period}-{i}','history':'Synthetic benchmark','idempotency_key':f'SYN-{period}-{i}','lines':[{'account_id':accounts['3'],'debit':'10.00','credit':'0'},{'account_id':accounts['5'],'credit':'10.00','debit':'0'}]},'synthetic')
            for month in ['08','09']:
                for i in range(430):
                    core._create_document(conn,1,{'direction':'incoming','number':f'SYN-{month}-{i}','series':'1','model':'55','issue_date':f'2026-{month}-01','posting_date':f'2026-{month}-02','partner_name':'Fictitious supplier','total':'100.00','items':[{'number':str(j),'description':'Synthetic item','total':'20.00'} for j in range(5)]},'synthetic')
        meta=seed_workspace(core)
        report={'label':args.label,'source_files_sha256':{name:hashlib.sha256((repo/name).read_bytes()).hexdigest() for name in ['app/api.py','app/core.py','frontend/src/views/DashboardView.vue']},'scope':'Synthetic in-process HTTP; no production, browser rendering or network latency','source_sha':args.source_sha or subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip(),'fixture':{'accounts':22597,'journals_added':300,'documents_added':860,'periods':['2025-09','2026-08','2026-09'],'demo_company':1},'results':{}}
        with TestClient(app) as client:
            session=client.post('/api/demo-login').json();client.headers['X-CSRF-Token']=session['csrf_token']
            r=client.post('/api/context',json={'company_id':1,'period':'2026-09','module':'fiscal'});r.raise_for_status()
            paths=['/accounts','/accounts?page=1&per_page=50','/documents?year=2026','/documents?period=2026-09','/journals?year=2026','/journals?period=2026-09','/dashboard?period=2026-09']
            original=core.db.read;queries=[]
            @contextmanager
            def traced(*a,**kw):
                with original(*a,**kw) as conn:
                    conn.set_trace_callback(lambda sql:queries.append(sql) if sql.lstrip().upper().startswith('SELECT') else None)
                    try:yield conn
                    finally:conn.set_trace_callback(None)
            core.db.read=traced
            for path in paths:
                samples=[];counts=[]
                for i in range(args.repetitions+1):
                    queries.clear();start=time.perf_counter();r=client.get('/api/companies/1'+path);elapsed=(time.perf_counter()-start)*1000;r.raise_for_status();payload=r.json()
                    if i:samples.append(round(elapsed,3));counts.append(len(queries))
                report['results'][path]={'samples_ms':samples,'median_ms':round(statistics.median(samples),3),'read_selects':counts,'response_bytes':len(r.content),'rows':len(payload) if isinstance(payload,list) else len(payload.get('items',[]))}
            core.db.read=original
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
