"""Chromium acceptance for rebuilt resources; no fiscal network or real certificate."""
from pathlib import Path
import json,os,socket,subprocess,sys,tempfile,time,traceback,urllib.request
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'artifacts/browser-reception-rebuild'

def server(data,port):
    sys.path.insert(0,str(ROOT/'tests'))
    import uvicorn
    from app.api import create_app
    from app.reception_service import ReceptionService
    from app.reception_transport import RemoteReply
    from test_reception_remote import MATRIX,BRANCH,THIRD,FakeCredentials,FakeTransport
    from test_reception import FIXTURE,SUMMARY,response
    from test_reception_adn import page,packet,EVENT
    from test_reception_workspace import nfse
    app=create_app(data,demo=True);core=app.state.core
    with core.db.transaction() as conn:
        ids=[r['id'] for r in conn.execute('SELECT id FROM companies ORDER BY id')]
        for cid,tax_id in zip(ids,[MATRIX,BRANCH]):conn.execute('UPDATE companies SET tax_id=? WHERE id=?',(tax_id,cid))
    token=core.demo_login();uid=core.session(token)['user']['id'];core.logout(token)
    packets=[]
    for i,(issuer,taker) in enumerate([(MATRIX,BRANCH),(THIRD,MATRIX),(MATRIX,MATRIX)],1):
        xml=nfse(issuer,taker).replace(b'<nNFSe>9</nNFSe>',('<nNFSe>'+str(i)+'</nNFSe>').encode())
        packets.append(packet(i,xml=xml)|{'ChaveAcesso':'SYNTHETIC-NFSE-'+str(i)})
    packets.append(packet(4,kind='EVENTO',xml=EVENT)|{'ChaveAcesso':'SYNTHETIC-NFSE-1'})
    packets.append(packet(5,xml=xml)|{'ChaveAcesso':'SYNTHETIC-NFSE-3'})
    packets.append(packet(6,xml=xml.replace(b'PRESTADOR SINTETICO',b'VERSAO SINTETICA PARA REVISAO'))|{'ChaveAcesso':'SYNTHETIC-NFSE-3'})
    seed=ReceptionService(core,FakeCredentials(),FakeTransport(RemoteReply(200,json.dumps(page(packets)).encode())))
    seed.query(ids[0],{'provider':'nfse_adn','environment':'restricted_production','period':'2026-11','idempotency_key':'synthetic-seed-adn-001'},'synthetic',uid)
    class Transport:
        def send(self,plan,identity):
            assert plan['provider']=='nfe_distribution' and identity.tax_id==MATRIX
            raw=FIXTURE.read_bytes().replace(b'12345678000195',MATRIX.encode())
            if 'www1.nfe.fazenda.gov.br' in plan['url']:raw=raw.replace(b'<tpAmb>2</tpAmb>',b'<tpAmb>1</tpAmb>')
            return RemoteReply(200,response([('1','procNFe_v4.00.xsd',raw),('2','resNFe_v1.01.xsd',SUMMARY)],last='2',maximum='3',environment='1' if 'www1.nfe.fazenda.gov.br' in plan['url'] else '2'))
    app.state.reception.transport=Transport()  # No HTTP/socket implementation.
    uvicorn.run(app,host='127.0.0.1',port=int(port),log_level='warning')

def main():
    from playwright.sync_api import sync_playwright,expect
    sys.path.insert(0,str(ROOT/'tests'))
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization.pkcs12 import serialize_key_and_certificates
    OUT.mkdir(parents=True,exist_ok=True);report={'ok':False,'checks':[],'console_errors':[]};process=None;previous_data=os.environ.get('ESCRITURA_DATA_DIR')
    try:
        with tempfile.TemporaryDirectory(prefix='reception-rebuilt-') as directory:
            root=Path(directory);os.environ['ESCRITURA_DATA_DIR']=str(root/'runner-bootstrap')
            from test_reception_remote import make_certificate,MATRIX,PASSWORD
            key,cert=make_certificate(MATRIX)
            pfx=root/'SYNTHETIC.P12';pfx.write_bytes(serialize_key_and_certificates(b'SYNTHETIC',key,cert,None,serialization.BestAvailableEncryption(PASSWORD)))
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            url=f'http://127.0.0.1:{port}'
            with (OUT/'server.log').open('w') as log:
                process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--server',str(root/'data'),str(port)],cwd=ROOT,env=dict(os.environ,ESCRITURA_DATA_DIR=str(root/'bootstrap'),ESCRITURA_RECEPTION_VAULT_DIR=str(root/'keys')),stdout=log,stderr=log)
                for _ in range(100):
                    try:urllib.request.urlopen(url+'/api/health',timeout=1);break
                    except OSError:time.sleep(.2)
                else:raise RuntimeError('Synthetic server did not start')
                with sync_playwright() as p:
                    browser=p.chromium.launch(headless=True,**({'executable_path':os.environ['ESCRITURA_TEST_BROWSER']} if os.environ.get('ESCRITURA_TEST_BROWSER') else {}))
                    page=browser.new_page(viewport={'width':1440,'height':1000});page.set_default_timeout(15000)
                    page.on('pageerror',lambda e:report['console_errors'].append(str(e)))
                    requests=[]
                    page.on('request',lambda r:requests.append((r.method,r.url)))
                    def nav(label):
                        expect(page.locator('#active-company')).to_be_enabled()
                        button=page.get_by_role('navigation',name='Navegação principal').get_by_role('button',name=label,exact=True,include_hidden=True)
                        details=button.locator('xpath=ancestor::details')
                        if details.count() and details.get_attribute('open') is None:details.locator('summary').click()
                        button.click()
                    def shot(name):page.screenshot(path=str(OUT/name),full_page=True)
                    try:
                        page.goto(url);page.get_by_role('button',name='Entrar na demonstração').click()
                        expect(page.get_by_role('heading',name='Visão geral',exact=True)).to_be_visible()
                        cid=page.request.get(url+'/api/session').json()['active_company_id'];scope='/api/companies/'+str(cid)
                        before=page.request.get(url+scope+'/documents').json()
                        companies=page.request.get(url+'/api/companies').json();other=next(c for c in companies if c['id']!=cid)
                        nav('DF-e');expect(page.get_by_role('heading',name='DF-e',exact=True)).to_be_visible()
                        expect(page.get_by_text('Nenhum documento local encontrado para estes filtros.',exact=True)).to_be_visible()
                        nav('NFS-e Nacional');expect(page.get_by_role('heading',name='NFS-e Nacional',exact=True)).to_be_visible()
                        box=page.get_by_role('region',name='Caixa de documentos');expect(box.locator('tbody tr')).to_have_count(4)
                        expect(page.get_by_role('button',name='Consultar uma página',exact=True)).to_be_disabled()
                        expect(page.locator('select[aria-label="Ambiente de recepção"]')).to_have_count(0)
                        start=len(requests);page.reload();expect(page.locator('#active-company')).to_be_enabled();nav('DF-e');nav('NFS-e Nacional')
                        expect(box.locator('tbody tr')).to_have_count(4)
                        assert all(address.startswith(url+'/') for _,address in requests[start:]),requests[start:]
                        assert not [(method,address) for method,address in requests[start:] if method!='GET' and any(part in address for part in ['/reception/','/reception-credential'])],requests[start:]
                        report['checks'].append('Reload e navegação leem somente recursos locais; nenhum check A1, upload ou consulta externa automática; views sem seletor de ambiente')
                        box.get_by_label('Direção dos documentos').select_option('both');box.get_by_role('button',name='Consultar acervo local').click();expect(box.locator('tbody tr')).to_have_count(1)
                        box.get_by_label('Competência declarada no XML').fill('2026-09')
                        with page.expect_response(lambda r:'/reception/nfse_adn?' in r.url and 'competence=2026-09' in r.url and r.request.method=='GET'):
                            box.get_by_role('button',name='Consultar acervo local').click()
                        expect(box.locator('tbody tr')).to_have_count(1)
                        with page.expect_download() as download:box.get_by_role('link',name='Relatório CSV do acervo').click()
                        csv=Path(download.value.path()).read_text(encoding='utf-8-sig');assert '2026-09-01' in csv and ';both;' in csv and '2026-11' in csv
                        shot('nfse-local-acervo.png')
                        box.get_by_role('button',name='Versões e origens',exact=True).click()
                        versions=page.get_by_role('region',name='Versões e origens do documento')
                        expect(versions.locator('tbody tr')).to_have_count(2);expect(versions).to_contain_text('3 recepção(ões)')
                        expect(versions).to_contain_text('Bytes distintos não comprovam divergência fiscal')
                        with page.expect_download() as download:versions.get_by_role('link',name='Baixar versão',exact=True).first.click()
                        assert b'PRESTADOR SINTETICO' in Path(download.value.path()).read_bytes()
                        with page.expect_download() as download:box.get_by_role('link',name='CSV das recepções',exact=True).click()
                        import csv as csv_module,io
                        sources=list(csv_module.DictReader(io.StringIO(Path(download.value.path()).read_text(encoding='utf-8-sig')),delimiter=';'))
                        assert len(sources)==3 and len({r['nsu'] for r in sources})==3
                        versions.scroll_into_view_if_needed();shot('nfse-versions.png')
                        nav('DF-e');nav('NFS-e Nacional');expect(box.locator('tbody tr')).to_have_count(1);expect(versions).not_to_be_visible()
                        report['checks'].append('Reconsulta agrupada: dois XMLs, três origens, primeiro original preservado, CSV completo e navegação repetida sem dados antigos')

                        report['checks'].append('Views e menus separados; acervo ADN local, ambos os papéis, competência declarada e CSV sem chamada fiscal')
                        page.get_by_role('button',name='Configurar empresa',exact=True).click()
                        dialog=page.get_by_role('dialog',name='Editar empresa')
                        expect(dialog.get_by_role('tab',name='Recepção fiscal',exact=True)).to_have_attribute('aria-selected','true')
                        dialog.get_by_label('Ambiente padrão DF-e',exact=True).select_option('production');dialog.get_by_label('Ambiente padrão NFS-e',exact=True).select_option('production')
                        for checkbox in dialog.get_by_role('checkbox',name='Produção',exact=True).all():checkbox.check()
                        dialog.get_by_role('checkbox',name='Homologação',exact=True).check();dialog.get_by_role('checkbox',name='Produção restrita',exact=True).check()
                        dialog.get_by_label('Arquivo A1',exact=True).set_input_files(str(pfx));dialog.get_by_label('Senha de proteção do A1',exact=True).fill('WRONG-SYNTHETIC')
                        dialog.get_by_role('button',name='Salvar recepção fiscal').click();expect(dialog.get_by_role('alert')).to_contain_text('Não foi possível carregar o A1')
                        expect(dialog.get_by_label('Senha de proteção do A1',exact=True)).to_have_value('')
                        dialog.get_by_label('Arquivo A1',exact=True).set_input_files(str(pfx));dialog.get_by_label('Senha de proteção do A1',exact=True).fill(PASSWORD.decode())
                        with page.expect_response(lambda r:r.url.endswith(scope+'/reception-settings') and r.request.method=='PUT') as saved:
                            dialog.get_by_role('button',name='Salvar recepção fiscal').click()
                        assert saved.value.ok;expect(dialog.get_by_text('A1 protegido no cofre.',exact=False)).to_be_visible()
                        assert PASSWORD.decode() not in page.request.get(url+scope+'/reception-settings').text()
                        shot('company-a1.png');dialog.get_by_role('button',name='Cancelar',exact=True).click()
                        nav('DF-e');expect(page.locator('.receive-query')).to_contain_text('Ambiente do cadastro: Produção');expect(page.locator('.receive-query select')).to_have_count(0)
                        page.get_by_role('button',name='Conferir A1 local').click();expect(page.get_by_text('A1, identidade e validade conferidos localmente.',exact=False)).to_be_visible()
                        page.get_by_role('button',name='Consultar uma página',exact=True).click();expect(box.locator('tbody tr')).to_have_count(2)
                        expect(box).to_contain_text('Resumo; XML íntegro pendente')
                        with page.expect_download() as download:box.get_by_role('link',name='Baixar resumo',exact=True).click()
                        assert b'resNFe' in Path(download.value.path()).read_bytes()
                        assert before==page.request.get(url+scope+'/documents').json()
                        shot('dfe-local-documents.png')
                        report['checks'].append('Cadastro A1 sintético com senha inválida/válida, cofre sem leitura de segredo, consulta NFe por stub e download sem escrituração')
                        nav('NFS-e Nacional');expect(page.locator('.receive-query')).to_contain_text('Ambiente do cadastro: Produção');expect(box.locator('tbody tr')).to_have_count(0)
                        nav('Empresas');page.get_by_role('button',name='Ativar empresa '+other['name'],exact=True).click();nav('NFS-e Nacional')
                        expect(box.locator('tbody tr')).to_have_count(0);expect(page.get_by_text('Nenhum documento local encontrado para estes filtros.',exact=True)).to_be_visible()
                        page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(300);page.locator('#workspace-panel').evaluate('(e)=>e.scrollTop=0');shot('nfse-mobile.png')
                        report['checks'].append('Troca de empresa limpa o acervo e mantém isolamento; layout móvel')
                        assert not report['console_errors'],report['console_errors'];report['ok']=True
                    except Exception:
                        shot('failure.png');(OUT/'failure-visible.txt').write_text(page.locator('body').inner_text());raise
                    finally:browser.close()
    except Exception as e:report.update(error=str(e),traceback=traceback.format_exc())
    finally:
        if process:process.terminate();process.wait(timeout=15)
        if previous_data is None:os.environ.pop('ESCRITURA_DATA_DIR',None)
        else:os.environ['ESCRITURA_DATA_DIR']=previous_data
        (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['ok'] else 1

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--server':server(sys.argv[2],sys.argv[3])
    else:raise SystemExit(main())
