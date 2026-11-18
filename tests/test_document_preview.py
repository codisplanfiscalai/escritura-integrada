"""Original PDF consultation through the real API, synthetic data only."""
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch
import zipfile
from fastapi.testclient import TestClient
from pypdf import PdfReader
import test_core as base

FIXTURES = Path(__file__).parent / 'fixtures'


def synthetic_xml(name, company_tax_id):
    if name == 'auditor_cte_stress':
        from lxml import etree
        from copy import deepcopy
        root = etree.fromstring(synthetic_xml('auditor_cte_long', company_tax_id))
        ns = {'c':'http://www.portalfiscal.inf.br/cte'}
        tag = '{'+ns['c']+'}'
        root.find('.//c:nCT',ns).text = '99203225'
        old_key=root.find('.//c:infCte',ns).get('Id')[3:]
        new_key=old_key[:-2]+'83'
        for node in root.iter():
            if node.text:
                node.text = node.text.replace(old_key,new_key)
            for key in node.attrib:
                node.attrib[key] = node.attrib[key].replace(old_key,new_key)
        info = root.find('.//c:infCte',ns)
        rem = info.find('c:rem',ns)
        for kind,address in [('exped','enderExped'),('receb','enderReceb')]:
            party = deepcopy(rem);party.tag=tag+kind
            party.find('c:enderReme',ns).tag=tag+address
            party.find('c:xNome',ns).text=kind.upper()+' SINTETICO TRANSPORTES COM NOME COMPLETO PRESERVADO'
            info.insert(list(info).index(rem)+1,party)
        for kind in ('emit','rem','dest'):
            party=info.find('c:'+kind,ns)
            party.find('c:xNome',ns).text=kind.upper()+' SINTETICO COM NOME EXTENSO INTEGRAL E MARCADOR FINAL'
            party.find('.//c:xLgr',ns).text='RUA '+kind.upper()+' SINTETICA EXTENSA COM COMPLEMENTO E FINAL DISTINTO'
        toma3=root.find('.//c:toma3',ns);toma3.getparent().remove(toma3)
        payer=deepcopy(rem);payer.tag=tag+'toma4';payer.find('c:CNPJ',ns).tag=tag+'CPF';payer.find('c:CPF',ns).text='00000000000'
        payer.find('c:enderReme',ns).tag=tag+'enderToma'
        payer.find('c:xNome',ns).text='TOMADOR CPF SINTETICO COMPLETO SEM VALOR FISCAL'
        etree.SubElement(payer,tag+'toma').text='4';root.find('.//c:ide',ns).append(payer)
        refs=root.find('.//c:infDoc',ns)
        for child in list(refs):refs.remove(child)
        for i in range(1,121):
            etree.SubElement(etree.SubElement(refs,tag+'infNFe'),tag+'chave').text='352601'+'0'*14+'55001'+str(i).zfill(19)
        comp=root.find('.//c:compl',ns)
        for i in range(1,31):
            obs=etree.SubElement(comp,tag+'ObsCont',xCampo='SINTETICO '+str(i))
            etree.SubElement(obs,tag+'xTexto').text=f'OBSERVACAO {i:03d} '+('CONTEUDO SINTETICO INTEGRAL SEM VALOR FISCAL '*3)+f'FIM{i:03d}'
        return etree.tostring(root,encoding='utf-8',xml_declaration=True)
    raw = (FIXTURES / (('auditor_demo' if name == 'auditor_long' else 'auditor_cte' if name == 'auditor_cte_long' else name) + '.xml')).read_bytes()
    if name == 'auditor_long':
        item = re.search(br'<det nItem="1">.*?</det>', raw, re.S)[0]
        raw = raw.replace(item, b''.join(item.replace(b'nItem="1"', f'nItem="{i}"'.encode()) for i in range(1,81)))
        raw = raw.replace(b'<nNF>1</nNF>', b'<nNF>81</nNF>')
        raw = re.sub(br'<total>.*?</total>', lambda m: m[0].replace(b'65000.00',b'5200000.00'),raw,flags=re.S)
    # Only the emitter becomes this synthetic company. Other parties remain
    # fictitious and distinct, including fixtures reusing the same tax ID.
    model = {'auditor_demo':'55','auditor_nfce':'65','auditor_cte':'57','auditor_long':'55','auditor_cte_long':'57'}[name]
    # Structured, deliberately non-fiscal key (zero CNPJ); no real identity.
    key = ('352601' + '0'*14 + model + '0010000000011000000010').encode()
    if name == 'auditor_long':
        key = key[:-2] + b'81'
    if name == 'auditor_cte_long':
        key = key[:-2] + b'82'
        raw = raw.replace(b'<nCT>99203223</nCT>', b'<nCT>99203224</nCT>')
        raw = raw.replace(b'DADOS SINTETICOS SEM VALOR FISCAL', b'EMPRESA SINTETICA DE TRANSPORTES E LOGISTICA SEM VALOR FISCAL')
        raw = raw.replace(b'</qrCodCTe>', b'&amp;ambiente=homologacao&amp;teste=sem-valor-fiscal</qrCodCTe>')
        source = re.search(br'<infNFe>.*?</infNFe>', raw, re.S)[0]
        raw = raw.replace(source, b''.join(b'<infNFe><chave>' + ('352601'+'0'*14+'55001'+str(i).zfill(19)).encode() + b'</chave></infNFe>' for i in range(1,31)))
    raw = raw.replace(b'9'*44, key)
    if model == '57':
        raw = re.sub(br'<chCTe>[^<]+</chCTe>', b'<chCTe>'+key+b'</chCTe>', raw)
    return re.sub(br'(<emit>\s*<CNPJ>)[^<]+',
                  lambda match: match[1] + company_tax_id.encode(), raw, count=1)


class DocumentPreviewTests(unittest.TestCase):
    setUp = base.CoreApiTests.setUp
    tearDown = base.CoreApiTests.tearDown
    create_company = base.CoreApiTests.create_company
    activate = base.CoreApiTests.activate
    scope = base.CoreApiTests.scope
    document = base.CoreApiTests.document

    def imported(self, name='auditor_demo', *, archive=False):
        raw = synthetic_xml(name, self.a['tax_id'])
        content, filename = raw, name + '.xml'
        if archive:
            out = io.BytesIO()
            with zipfile.ZipFile(out, 'w') as pack:
                pack.writestr('other/nota.xml', raw.replace(b'<nNF>1</nNF>', b'<nNF>999</nNF>').replace(re.search(br'Id="NFe([0-9]+)"',raw)[1], b'8'*44))
                pack.writestr('wanted/nota.xml', raw)
            content, filename = out.getvalue(), 'synthetic.zip'
        response = self.client.post(self.scope('/imports/preview'), json={
            'filename': filename, 'period': '2026-11',
            'options': {'posting_date': '2026-11-06'},
            'content_base64': base64.b64encode(content).decode(),
        })
        self.assertEqual(200, response.status_code, response.text)
        batch = response.json()
        self.assertTrue(batch['can_confirm'], batch.get('issues'))
        index = next(i for i,d in enumerate(batch['documents']) if d['source_hash'] == hashlib.sha256(raw).hexdigest())
        response = self.client.post(self.scope(f"/imports/{batch['id']}/confirm"), json={
            'preview_hash':batch['preview_hash'], 'posting_mode':'pending', 'selected':[f'documents:{index}'],
        })
        self.assertEqual(200, response.status_code, response.text)
        doc = next(d for d in self.core.documents(self.a['id']) if d['source_hash'] == hashlib.sha256(raw).hexdigest())
        return doc, raw, batch

    def snapshot(self):
        with self.core.db.read() as conn:
            return {table:[tuple(r) for r in conn.execute(f'SELECT * FROM {table} ORDER BY id')]
                    for table in ('documents','document_sources','imports','titles','journals','masters','audit')}

    def url(self, doc, cid=None):
        return self.scope(f"/documents/{doc['id']}/auxiliary", cid)

    def test_real_models_render_pdf_and_repeat_without_writes(self):
        for fixture, renderer in [('auditor_demo','Danfe'),('auditor_nfce','Danfce'),('auditor_cte','Dacte')]:
            with self.subTest(fixture=fixture):
                doc, raw, _ = self.imported(fixture)
                before = self.snapshot()
                for _ in range(2):
                    response = self.client.get(self.url(doc))
                    self.assertEqual(200, response.status_code, response.text[:200] if not response.content.startswith(b'%PDF') else '')
                    self.assertEqual('application/pdf', response.headers['content-type'])
                    self.assertEqual('no-store', response.headers['cache-control'])
                    self.assertIn(renderer, response.headers['x-document-renderer'])
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), response.headers['x-source-sha256'])
                    self.assertGreaterEqual(len(PdfReader(io.BytesIO(response.content)).pages),1)
                self.assertEqual(before, self.snapshot())

    def test_dacte_qr_repair_preserves_xml_and_environment(self):
        for fixture in ('auditor_cte', 'auditor_cte_long'):
            with self.subTest(fixture=fixture):
                doc, raw, _ = self.imported(fixture)
                before = self.snapshot()
                response = self.client.get(self.url(doc))
                self.assertEqual(200, response.status_code)
                text = ' '.join(p.extract_text() for p in PdfReader(io.BytesIO(response.content)).pages)
                self.assertIn('EMITIDO EM AMBIENTE DE', text)
                self.assertIn('HOMOLOGAÇÃO - SEM VALOR FISCAL', text)
                if fixture == 'auditor_cte_long':
                    self.assertEqual(3, len(PdfReader(io.BytesIO(response.content)).pages))
                    for key in re.findall(br'<chave>([0-9]+)</chave>', raw):
                        self.assertIn(key.decode(), text)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), response.headers['x-source-sha256'])
                self.assertEqual(before, self.snapshot())

    def test_dacte_long_fields_and_multiple_continuations_keep_all_content(self):
        from app.dacte_preview import PreviewDacte
        from lxml import etree
        doc, raw, _ = self.imported('auditor_cte_stress')
        before=self.snapshot()
        response=self.client.get(self.url(doc))
        self.assertEqual(200,response.status_code,response.text[:200])
        pdf=PdfReader(io.BytesIO(response.content))
        self.assertGreaterEqual(len(pdf.pages),4)
        text=' '.join(page.extract_text() for page in pdf.pages)
        compact=re.sub(r'\s+','',text)
        root=etree.fromstring(raw)
        for node in root.xpath('.//*[local-name()="xNome" or local-name()="xLgr" or local-name()="xCpl" or local-name()="xMun" or local-name()="xTexto" or local-name()="chave"]'):
            self.assertIn(re.sub(r'\s+','',node.text or ''),compact)
        self.assertNotIn('...',text)
        for index,page in enumerate(pdf.pages,1):
            self.assertIn(f'{index}/{len(pdf.pages)}',page.extract_text())
            self.assertIn('HOMOLOGAÇÃO - SEM VALOR FISCAL',page.extract_text())
        self.assertEqual(before,self.snapshot())
        layout=PreviewDacte(raw.decode())
        for page,x,y,w,h in layout.layout_boxes:
            self.assertGreaterEqual(x,layout.l_margin-0.01)
            self.assertLessEqual(x+w,layout.w-layout.r_margin+0.01)
            self.assertLessEqual(y+h,layout.h-28+0.01)

    def test_unreviewed_dacte_profiles_are_explicit_not_lossy_fallbacks(self):
        from app.auxiliary import render_danfe
        from app.core import DomainError
        raw=synthetic_xml('auditor_cte',self.a['tax_id'])
        for old,new in [(b'<modal>01',b'<modal>02'),(b'<tpImp>1',b'<tpImp>2'),(b'<tpEmis>1',b'<tpEmis>5'),(b'<tpServ>0',b'<tpServ>1')]:
            with self.subTest(new=new),self.assertRaises(DomainError) as caught:
                render_danfe(raw.replace(old,new),document_preview=True)
            self.assertEqual('renderer_not_validated',caught.exception.code)

    def test_multipage_danfe_preserves_all_items(self):
        doc, _, _ = self.imported('auditor_long')
        response = self.client.get(self.url(doc))
        self.assertEqual(200,response.status_code)
        pdf = PdfReader(io.BytesIO(response.content))
        self.assertGreater(len(pdf.pages),1)
        self.assertEqual(80,sum(page.extract_text().count('PRODUTO SINTÉTICO PARA TESTE') for page in pdf.pages))

    def test_zip_same_basename_exact_original_even_after_bookkeeping_edit(self):
        doc, raw, _ = self.imported(archive=True)
        response = self.client.put(self.scope(f"/documents/{doc['id']}"), json={
            'version':doc['version'], 'partner_name':'Nome corrigido somente na escrituração',
            'total':'123.45', 'reason':'Teste sintético de independência da origem',
        })
        self.assertEqual(200,response.status_code,response.text)
        before = self.snapshot()
        with patch('app.auxiliary.render_danfe',return_value=(b'%PDF-test','fixture')) as render:
            self.assertEqual(200,self.client.get(self.url(doc)).status_code)
            render.assert_called_once_with(raw, document_preview=True)
        self.assertEqual(before,self.snapshot())

    def test_missing_tampered_and_wrong_identity_are_refused(self):
        doc, raw, batch = self.imported()
        endpoint = self.url(doc)
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE imports SET original=? WHERE id=?',(raw+b' ',batch['id']))
        self.assertEqual('source_unavailable',self.client.get(endpoint).json()['code'])
        with self.core.db.transaction() as conn:
            conn.execute('UPDATE imports SET original=? WHERE id=?',(raw,batch['id']))
            conn.execute('UPDATE documents SET key=? WHERE id=?',('8'*44,doc['id']))
        self.assertEqual('source_unavailable',self.client.get(endpoint).json()['code'])
        with self.core.db.transaction() as conn:
            conn.execute("UPDATE imports SET original=X'' WHERE id=?",(batch['id'],))
        self.assertEqual(422,self.client.get(endpoint).status_code)
        self.assertEqual(404,self.client.get(self.url(doc,self.b['id'])).status_code)

    def test_manual_unsupported_and_invalid_xml_have_explicit_errors(self):
        response=self.client.post(self.scope('/documents'),json=self.document())
        self.assertEqual(201,response.status_code,response.text)
        doc=response.json()
        self.assertEqual('source_unavailable',self.client.get(self.url(doc)).json()['code'])
        for model in ('67','58','99'):
            with self.core.db.transaction() as conn:
                conn.execute('UPDATE documents SET model=? WHERE id=?',(model,doc['id']))
            self.assertEqual('renderer_not_validated',self.client.get(self.url(doc)).json()['code'])
        with self.core.db.transaction() as conn:
            conn.execute("UPDATE documents SET model='NFSE' WHERE id=?",(doc['id'],))
        self.assertEqual('source_unavailable',self.client.get(self.url(doc)).json()['code'])
        doc, _, batch=self.imported()
        invalid=b'<invalid'
        hashed=hashlib.sha256(invalid).hexdigest()
        with self.core.db.transaction() as conn:
            parsed=json.loads(conn.execute('SELECT parsed_json FROM imports WHERE id=?',(batch['id'],)).fetchone()[0])
            parsed['documents'][0]['source_hash']=hashed
            conn.execute('UPDATE imports SET original=?,parsed_json=? WHERE id=?',(invalid,json.dumps(parsed),batch['id']))
            conn.execute('UPDATE documents SET source_hash=? WHERE id=?',(hashed,doc['id']))
        self.assertEqual('source_unavailable',self.client.get(self.url(doc)).json()['code'])

    def test_read_and_export_permissions_required_without_import_permissions(self):
        doc, _, _=self.imported()
        permissions=[{'company_id':self.a['id'],'routine':'fiscal.documents','action':action,'effect':'allow'} for action in ('read','export')]
        response=self.client.post('/api/users',json={'username':'preview-only','password':'Senha-ficticia-123!','role':'custom','company_ids':[self.a['id']],'permissions':permissions})
        self.assertEqual(201,response.status_code,response.text)
        with TestClient(self.app) as client:
            session=client.post('/api/login',json={'username':'preview-only','password':'Senha-ficticia-123!'}).json()
            client.headers['X-CSRF-Token']=session['csrf_token'];self.activate(self.a['id'],client=client)
            self.assertEqual(200,client.get(self.url(doc)).status_code)
            self.assertEqual(403,client.get(self.url(doc,self.b['id'])).status_code)
            for denied in ('read','export'):
                with self.core.db.transaction() as conn:
                    conn.execute("UPDATE user_permissions SET effect=CASE WHEN action=? THEN 'deny' ELSE 'allow' END WHERE user_id=?",(denied,session['user']['id']))
                self.assertEqual(403,client.get(self.url(doc)).status_code)


if __name__ == '__main__':
    unittest.main()
