"""Benchmark local reproduzível de leitura fiscal com dados sintéticos descartáveis."""
import sys,json,time,tempfile,statistics
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.db import Database
from app.business import BusinessCore
from app.core import now
with tempfile.TemporaryDirectory() as folder:
 db=Database(folder);core=BusinessCore(db,demo=True)
 with db.transaction() as c:
  cid=c.execute('SELECT id FROM companies ORDER BY id LIMIT 1').fetchone()[0]
  sample=dict(c.execute('SELECT * FROM documents WHERE company_id=? LIMIT 1',(cid,)).fetchone())
  cols=[k for k in sample if k!='id']
  for i in range(3000):
   r=sample|{'number':f'PERF-{i}','business_key':f'performance:{i}','journal_id':None,'status':'pending','posting_date':'2026-02-01','period':'2026-02'}
   c.execute(f'INSERT INTO documents({",".join(cols)}) VALUES({",".join("?" for _ in cols)})',[r[k] for k in cols])
  uid=c.execute("INSERT INTO users(username,password_hash,role,active,created_at) VALUES('benchmark','invalid','custom',1,?)",(now(),)).lastrowid
  c.execute('INSERT INTO user_companies(user_id,company_id) VALUES(?,?)',(uid,cid))
  c.execute("INSERT INTO user_permissions(user_id,company_id,routine,action,effect) VALUES(?,?,'*','*','allow')",(uid,cid))
  token=core._new_session(c,uid)
 counter=[0];connect=db.connect
 def traced():
  c=connect();c.set_trace_callback(lambda _:counter.__setitem__(0,counter[0]+1));return c
 db.connect=traced
 results={}
 for name,fn in [('session',lambda:core.session(token)),('fiscal_report',lambda:core.fiscal_report(cid,'fiscal-documents','2026-01-01','2026-12-31')),('documents',lambda:core.documents(cid))]:
  times=[]
  for _ in range(3):
   counter[0]=0;start=time.perf_counter();data=fn();times.append((time.perf_counter()-start)*1000)
  results[name]={'median_ms':round(statistics.median(times),2),'sql_statements':counter[0],'rows':len(data.get('rows',[])) if isinstance(data,dict) else len(data)}
 counter[0]=0;start=time.perf_counter();core.session(token,include_permissions=False);results['request_session']={'ms':round((time.perf_counter()-start)*1000,2),'sql_statements':counter[0]}
 print(json.dumps(results,indent=2))
