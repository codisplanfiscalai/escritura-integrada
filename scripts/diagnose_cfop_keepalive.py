"""Reproduce idle-close races using only a disposable demo server and database.

This is a diagnostic, not a retry policy or a CI gate. No URL/data-dir argument
is accepted, and it never changes the application's production keep-alive.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SERVER = '''
import json, os, time, uvicorn
from uvicorn.protocols.http.h11_impl import H11Protocol
from app.api import app

def event(kind, **values):
 print(json.dumps({'event':kind,'time':time.monotonic(),**values}),flush=True)

class Traced(H11Protocol):
 def timeout_keep_alive_handler(self):
  event('idle_close',client=list(self.client));super().timeout_keep_alive_handler()

async def traced(scope, receive, send):
 if scope['type']=='http' and scope['path'].endswith('/cfop-source-loads'):
  event('handler',client=list(scope['client']),query=scope['query_string'].decode('ascii'))
 await app(scope,receive,send)

uvicorn.run(traced,host='127.0.0.1',port=int(os.environ['CFOP_PROBE_PORT']),
 http=Traced,timeout_keep_alive=float(os.environ['CFOP_PROBE_IDLE']),access_log=False)
'''


def probe(pw, idle, samples, output, executable):
    with tempfile.TemporaryDirectory(prefix='cfop-keepalive-') as data:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        url=f'http://127.0.0.1:{port}'
        path=output/f'server-{idle}.log'
        with path.open('w') as log:
            process=subprocess.Popen([sys.executable,'-c',SERVER],cwd=ROOT,
                env=dict(os.environ,ESCRITURA_DATA_DIR=data,ESCRITURA_DEMO='1',CFOP_PROBE_PORT=str(port),CFOP_PROBE_IDLE=str(idle)),stdout=log,stderr=log)
            browser=None
            try:
                for _ in range(100):
                    try:
                        with urllib.request.urlopen(url+'/api/health',timeout=1):break
                    except OSError:time.sleep(.1)
                else:raise RuntimeError('Disposable diagnostic server did not start')
                browser=pw.chromium.launch(headless=True,**({'executable_path':executable} if executable else {'channel':'chromium'}))
                page=browser.new_page()
                login=page.request.post(url+'/api/demo-login',data={})
                assert login.ok
                endpoint=url+'/api/companies/1/cfop-source-loads'
                cases=[]
                delays=[.010,.012,.014,.016,.017,.018,.019,.020,.021]
                for index in range(samples):
                    seed=page.request.get(endpoint+f'?seed={index}')
                    assert seed.ok and seed.json()==[]
                    start=time.monotonic();delay=delays[index % len(delays)];time.sleep(delay)
                    try:
                        response=page.request.get(endpoint+f'?probe={index}')
                        assert response.ok and response.json()==[]
                        case={'status':response.status}
                    except Exception as error:
                        # Keep cookies, authorization headers and raw request logs out.
                        message=str(error).split('Call log:')[0].strip()
                        if not any(code in message for code in ['ECONNRESET','socket hang up']):raise
                        case={'error':message}
                    cases.append(case|{'index':index,'start':start,'end':time.monotonic(),'delay':delay})
            finally:
                if browser:browser.close()
                process.terminate();process.wait(timeout=15)
        events=[]
        for line in path.read_text().splitlines():
            if line.startswith('{'):events.append(json.loads(line))
        failures=[]
        for case in cases:
            if 'error' not in case:continue
            seed=next(e for e in events if e['event']=='handler' and e['query']==f'seed={case["index"]}')
            received=any(e['event']=='handler' and e['query']==f'probe={case["index"]}' for e in events)
            closed=any(e['event']=='idle_close' and e['client']==seed['client'] and case['start']<=e['time']<=case['end'] for e in events)
            failures.append(case|{'handler_received':received,'idle_close_during_request':closed})
        return {'idle_seconds':idle,'requests':samples,'failures':failures,'failure_count':len(failures)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples',type=int,default=270)
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts'/'cfop-keepalive-diagnostic')
    args=parser.parse_args()
    if not 1<=args.samples<=1000:parser.error('Use 1 a 1000 amostras por cenário.')
    args.output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        results=[probe(pw,idle,args.samples,args.output,os.environ.get('ESCRITURA_TEST_BROWSER')) for idle in [.02,.2]]
    report={'synthetic_only':True,'diagnostic_only':True,'results':results}
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'synthetic_only':True,'results':[{'idle_seconds':r['idle_seconds'],'requests':r['requests'],'failures':r['failure_count'],
        'failed_requests_reaching_handler':sum(f['handler_received'] for f in r['failures']),
        'failures_with_idle_close':sum(f['idle_close_during_request'] for f in r['failures'])} for r in results]},indent=2))


if __name__=='__main__':main()
