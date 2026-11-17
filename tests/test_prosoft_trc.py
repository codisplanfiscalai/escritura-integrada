"""TRC PJ proofs against supplied CTBLCTOS sheets 1,3,4; synthetic only."""
from copy import deepcopy
from hashlib import sha256
import unittest
from fastapi.testclient import TestClient
from app.core import DomainError, cnpj_digits
from app.prosoft import encode_journals
import test_core as base
import test_prosoft_increment as prior

CNPJ = '11222333000181'


def registration(**changes):
    return {'destination_missing':True,'person_type':'legal','name':'Synthetic Legal Entity',
            'alias':'Synthetic PJ','state':'SP',**changes}


def mapping(**changes):
    return {'code':CNPJ,'confirmed':True,'third_type':'normal','create_third':registration(),**changes}


def journal():
    return {'id':1,'number':1,'date':'2026-11-06','document':'SYNTRC','history':'Synthetic',
            'total_cents':10001,'lines':[
                {'account_id':1,'access_code':'1','participant_id':7,'debit_cents':10001,'credit_cents':0},
                {'account_id':2,'access_code':'2','debit_cents':0,'credit_cents':10001}]}


def accounts():
    return {'1':{'code':'123','confirmed':True,'third_mode':'optional'},
            '2':{'code':'456','confirmed':True}}


def read_trc(raw):
    # Independent literal positions from PDF sheet 3; no encoder constants.
    rows=raw[:-2].split(b'\r\n')
    assert raw.endswith(b'\r\n') and all(all(32<=c<=126 for c in r) for r in rows)
    result=[]
    for row in rows:
        if not row.startswith(b'TRC'):continue
        assert len(row)==646 and row[8:10]==b'  ' and row[10:11]==b'0'
        assert row[105:274]==b' '*169 and row[276:]==b' '*370
        result.append({'order':int(row[3:8]),'cnpj':row[11:25].decode('ascii'),
                       'name':row[25:85].decode('ascii').rstrip(),'alias':row[85:105].decode('ascii').rstrip(),
                       'state':row[274:276].decode('ascii'),'sha256':sha256(row).hexdigest()})
    return result


class TrcCodecTests(unittest.TestCase):
    def encode(self,journals=None,parties=None,types=None,mappings=None,**kw):
        return encode_journals(journals or [journal()],mappings or accounts(),{},'1',
                               participants=parties or {'7':mapping()},record_types=types or ['LC1','LC2','TRC'],**kw)

    def test_minimal_pj_positions_blank_optional_fields_and_lc_reference(self):
        j=journal();p={'7':mapping()};before=deepcopy((j,p))
        raw,m=self.encode([j],p)
        self.assertEqual([646,448],[len(r) for r in raw.splitlines()])
        self.assertEqual([{'order':1,'cnpj':CNPJ,'name':'Synthetic Legal Entity','alias':'Synthetic PJ','state':'SP',
            'sha256':sha256(raw.splitlines()[0]).hexdigest()}],read_trc(raw))
        self.assertEqual(CNPJ.encode(),raw.splitlines()[1][73:87])
        self.assertEqual({'CTA':0,'LC1':1,'LC2':0,'TRC':1},m['record_counts'])
        self.assertEqual({'participant_id':7,'destination_code':CNPJ,'journal_ids':[1],'order':1,
            'record_sha256':read_trc(raw)[0]['sha256']},m['third_registrations'][0])
        self.assertFalse(m['homologated_in_destination']);self.assertEqual(before,(j,p))
        self.assertEqual((raw,m),self.encode([j],p))

    def test_trc_is_explicit_and_legacy_bytes_and_manifest_are_preserved(self):
        legacy,manifest=encode_journals([journal()],accounts(),{},'1',participants={'7':mapping()})
        without=dict(mapping());without.pop('create_third')
        old,old_manifest=encode_journals([journal()],accounts(),{},'1',participants={'7':without})
        self.assertEqual((old,old_manifest),(legacy,manifest))
        self.assertEqual(['LC1','LC2','CTA'],manifest['selected_record_types'])
        self.assertNotIn('third_registrations',manifest);self.assertNotIn('TRC',manifest['record_counts'])

    def test_only_participants_actually_referenced_in_selected_journals_emit(self):
        parties={'7':mapping(),'9':mapping(create_third={'unsupported':True})}
        raw,m=self.encode(parties=parties)
        self.assertEqual([7],[t['participant_id'] for t in m['third_registrations']])
        a=accounts();a['1']['third_mode']='none'
        raw,m=self.encode(parties=parties,mappings=a)
        self.assertEqual([],read_trc(raw));self.assertEqual([],m['third_registrations'])
        self.assertEqual(0,m['record_counts']['TRC'])

    def test_duplicate_cnpj_definitions_deduplicate_and_conflicts_fail(self):
        j=journal();other=deepcopy(j);other.update(id=2,number=2);other['lines'][0]['participant_id']=8
        p={'7':mapping(),'8':mapping()}
        raw,m=self.encode([other,j],p)
        self.assertEqual(1,len(read_trc(raw)))
        self.assertEqual([1,1],[x['order'] for x in m['third_registrations']])
        self.assertEqual([[1],[2]],[x['journal_ids'] for x in m['third_registrations']])
        p['8']['create_third']['name']='Different Synthetic Entity'
        with self.assertRaises(DomainError) as e:self.encode([j,other],p)
        self.assertEqual('third_registration_conflict',e.exception.code)

    def test_sorted_independent_trc_order_before_lc1_and_lc2(self):
        j=journal();j['lines']=[dict(j['lines'][0],debit_cents=5000),
            dict(j['lines'][0],account_id=3,access_code='3',participant_id=8,debit_cents=5001),j['lines'][1]]
        a=accounts();a['3']={'code':'789','confirmed':True,'third_mode':'optional'}
        second='223334440001'+cnpj_digits('223334440001')
        raw,m=self.encode([j],{'7':mapping(code=second),'8':mapping()},mappings=a)
        self.assertEqual([b'TRC',b'TRC',b'LC1',b'LC2',b'LC2',b'LC2'],[r[:3] for r in raw.splitlines()])
        self.assertEqual([CNPJ,second],[r['cnpj'] for r in read_trc(raw)])
        self.assertEqual(second.encode(),raw.splitlines()[3][17:31])
        self.assertEqual(CNPJ.encode(),raw.splitlines()[4][17:31])
        self.assertEqual(10001,m['debit_cents']);self.assertEqual(m['debit_cents'],m['credit_cents'])

    def test_cta_and_trc_both_precede_journals_with_independent_orders(self):
        a=accounts();a['1']['create_account']={'destination_missing':True,'classifier':'1.01','name':'Synthetic Account',
            'cost_center_mode':'0','reconciliation':'0'}
        raw,m=self.encode(mappings=a,types=['TRC','CTA','LC2','LC1'])
        self.assertEqual([b'CTA00001',b'TRC00001',b'LC100001'],[r[:8] for r in raw.splitlines()])
        self.assertEqual(['LC1','LC2','CTA','TRC'],m['selected_record_types'])

    def test_malformed_unsupported_or_unconfirmed_data_are_never_fabricated(self):
        invalid=[mapping(code='12345678901'),mapping(code='12ABC34501DE35'),mapping(code='00000000000000'),
            mapping(code='11222333000180'),mapping(code=' '+CNPJ),mapping(confirmed=False),mapping(third_type='free')]
        for field,value in [('destination_missing',False),('person_type','physical'),('person_type','free'),
            ('name',''),('name','x'*61),('name','\nSynthetic'),('name','😀'),('alias',''),('alias','x'*21),
            ('state','sp'),('state','BRA'),('state',''),('unknown','x')]:
            invalid.append(mapping(create_third=registration(**{field:value})))
        invalid.extend([mapping(create_third=[]),mapping(create_third={})])
        for value in invalid:
            with self.subTest(value=value),self.assertRaises(DomainError):self.encode(parties={'7':value})

    def test_ascii_conversion_requires_review_and_never_mutates_originals(self):
        p={'7':mapping(create_third=registration(name='Razão Sintética',alias='Apelído'))};before=deepcopy(p)
        raw,m=self.encode(parties=p)
        self.assertTrue(m['needs_ascii_review']);self.assertEqual('Razao Sintetica',read_trc(raw)[0]['name'])
        self.assertEqual(2,len(m['text_changes']));self.assertEqual(before,p)
        accepted,accepted_m=self.encode(parties=p,allow_ascii=True)
        self.assertEqual(raw,accepted);self.assertFalse(accepted_m['needs_ascii_review'])


class TrcApiTests(unittest.TestCase):
    setUp=base.CoreApiTests.setUp
    tearDown=base.CoreApiTests.tearDown
    create_company=base.CoreApiTests.create_company
    activate=base.CoreApiTests.activate
    scope=base.CoreApiTests.scope
    journal=base.CoreApiTests.journal
    post=prior.ProsoftApiTests.post
    economic_snapshot=prior.ProsoftApiTests.economic_snapshot

    def party(self,code='TRCSYN'):
        return self.post('/masters/participant',{'code':code,'name':'Synthetic PJ','tax_id':'','data':{}},201)['id']

    def prepare(self):
        pid=self.party();j=self.journal()|{'document':'SYNTRC','history':'Synthetic'}
        j['lines'][0]['participant_id']=pid
        created=self.core.create_journal(self.a['id'],j,'synthetic')
        payload={'period':'2026-11','company_code':'99','record_types':['LC1','LC2','TRC'],
            'accounts':{str(a['id']):{'code':a['access_code'],'confirmed':True} for a in self.accounts},
            'participants':{str(pid):mapping()}}
        payload['accounts'][str(self.aid['3'])]['third_mode']='optional'
        return pid,created,payload

    def confirm(self,payload):
        pre=self.post('/prosoft/preview',payload)
        saved=self.post('/prosoft/confirm',payload|{'preview_hash':pre['preview_hash'],'destination_reviewed':True})
        return pre,saved

    def test_saved_per_company_settings_preview_download_manifest_replay_and_closed_period(self):
        pid,j,p=self.prepare();before=self.economic_snapshot()
        cfg={k:v for k,v in p.items() if k!='period'}
        response=self.client.put(self.scope('/prosoft/settings'),json={'version':0,'settings':cfg})
        self.assertEqual(200,response.status_code,response.text);settings=response.json()
        self.assertEqual(mapping(),settings['settings']['participants'][str(pid)])
        self.assertEqual({},self.client.get(self.scope('/prosoft/settings',self.b['id'])).json()['settings']['participants'])
        self.post('/periods/close',{'module':'accounting','period':'2026-11','reason':'Synthetic'})
        p=settings['settings']|{'period':'2026-11','settings_version':settings['version']}
        pre,saved=self.confirm(p);again=self.post('/prosoft/confirm',p|{'preview_hash':pre['preview_hash'],'destination_reviewed':True})
        self.assertEqual(saved['id'],again['id']);self.assertTrue(again['duplicate'])
        response=self.client.get(self.scope(f"/exports/{saved['id']}/download"))
        self.assertEqual(200,response.status_code);raw=response.content
        self.assertEqual(pre['sha256'],sha256(raw).hexdigest());self.assertEqual(CNPJ,read_trc(raw)[0]['cnpj'])
        manifest=self.client.get(self.scope(f"/prosoft/exports/{saved['id']}/manifest?download=1")).json()
        self.assertEqual(pre['manifest'],manifest);self.assertEqual(saved['manifest'],manifest)
        self.assertEqual([j['id']],manifest['third_registrations'][0]['journal_ids'])
        self.assertEqual(before,self.economic_snapshot())
        self.activate(self.b['id'])
        self.assertEqual(404,self.client.get(self.scope(f"/exports/{saved['id']}/download",self.b['id'])).status_code)

    def test_explicit_trc_empty_selection_has_own_immutable_manifest_identity(self):
        _,_,p=self.prepare();p['participants'][next(iter(p['participants']))].pop('create_third')
        pre,selected=self.confirm(p)
        legacy_pre,legacy=self.confirm(p|{'record_types':['LC1','LC2']})
        self.assertEqual(pre['sha256'],legacy_pre['sha256']);self.assertNotEqual(selected['id'],legacy['id'])
        self.assertEqual(0,selected['manifest']['record_counts']['TRC'])
        self.assertNotIn('TRC',legacy['manifest']['record_counts'])
        self.assertEqual(selected['manifest'],self.client.get(self.scope(f"/prosoft/exports/{selected['id']}/manifest")).json())

    def test_settings_version_and_foreign_reference_guards_preserved(self):
        pid,_,p=self.prepare();cfg={k:v for k,v in p.items() if k!='period'}
        saved=self.client.put(self.scope('/prosoft/settings'),json={'version':0,'settings':cfg}).json()
        p=saved['settings']|{'period':'2026-11','settings_version':1};pre=self.post('/prosoft/preview',p)
        changed=deepcopy(saved['settings']);changed['participants'][str(pid)]['create_third']['alias']='New Synthetic Alias'
        self.assertEqual(200,self.client.put(self.scope('/prosoft/settings'),json={'version':1,'settings':changed}).status_code)
        self.post('/prosoft/confirm',p|{'preview_hash':pre['preview_hash'],'destination_reviewed':True},409)
        self.activate(self.b['id']);foreign=self.client.post(self.scope('/masters/participant',self.b['id']),json={'code':'OTHER','name':'Synthetic Other','data':{}}).json()['id']
        self.activate(self.a['id']);changed['participants']={str(foreign):mapping()}
        response=self.client.put(self.scope('/prosoft/settings'),json={'version':2,'settings':changed})
        self.assertEqual(400,response.status_code,response.text)
        self.assertIn('Cadastro não pertence',response.json()['detail'])
        with self.core.db.read() as conn:self.assertEqual(0,conn.execute('SELECT COUNT(*) FROM export_batches').fetchone()[0])

    def test_conflicting_trc_cannot_create_batch_or_export_audit(self):
        pid,_,p=self.prepare();other=self.party('TRCOTHER')
        payload=self.journal('second')|{'document':'SYN2','history':'Synthetic'}
        payload['lines'][0]['participant_id']=other
        self.core.create_journal(self.a['id'],payload,'synthetic')
        p['participants'][str(other)]=mapping()
        preview=self.post('/prosoft/preview',p)
        with self.core.db.read() as conn:
            before={t:conn.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('export_batches','audit')}
        changed=deepcopy(p);changed['participants'][str(other)]['create_third']['alias']='Different Synthetic'
        error=self.post('/prosoft/confirm',changed|{'preview_hash':preview['preview_hash'],'destination_reviewed':True},409)
        self.assertEqual('third_registration_conflict',error['code'])
        with self.core.db.read() as conn:
            self.assertEqual(before,{t:conn.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in before})

    def test_trc_selection_follows_journal_and_competence_without_reading_master_data(self):
        pid,j,p=self.prepare()
        other=self.party('TRCLATER');self.activate(self.a['id'],'2026-12')
        data=self.journal('later',day='2026-12-01')|{'document':'SYNDEC','history':'Synthetic'}
        data['lines'][0]['participant_id']=other
        later=self.core.create_journal(self.a['id'],data,'synthetic')
        self.activate(self.a['id'])
        p['participants'][str(other)]=mapping(code='223334440001'+cnpj_digits('223334440001'))
        preview,saved=self.confirm(p|{'journal_ids':[j['id']]})
        self.assertEqual([pid],[t['participant_id'] for t in saved['manifest']['third_registrations']])
        self.post('/prosoft/preview',p|{'journal_ids':[later['id']]},400)
        self.activate(self.a['id'],'2026-12')
        _,december=self.confirm(p|{'period':'2026-12'})
        self.assertEqual([other],[t['participant_id'] for t in december['manifest']['third_registrations']])

    def test_ascii_review_is_required_before_any_trc_batch_is_written(self):
        pid,_,p=self.prepare();p['participants'][str(pid)]['create_third']['name']='Razão Sintética'
        pre=self.post('/prosoft/preview',p);self.assertTrue(pre['manifest']['needs_ascii_review'])
        self.post('/prosoft/confirm',p|{'preview_hash':pre['preview_hash'],'destination_reviewed':True},400)
        with self.core.db.read() as conn:self.assertEqual(0,conn.execute('SELECT COUNT(*) FROM export_batches').fetchone()[0])
        saved=self.post('/prosoft/confirm',p|{'preview_hash':pre['preview_hash'],'destination_reviewed':True,'allow_ascii':True})
        raw=self.client.get(self.scope(f"/exports/{saved['id']}/download")).content
        self.assertEqual('Razao Sintetica',read_trc(raw)[0]['name'])
        self.assertEqual('Razão Sintética',p['participants'][str(pid)]['create_third']['name'])

    def test_invalid_registration_and_permissions_cannot_bypass_settings_or_export(self):
        _,_,p=self.prepare();cfg={k:v for k,v in p.items() if k!='period'}
        bad=deepcopy(cfg);bad['participants'][next(iter(bad['participants']))]['create_third']['person_type']='physical'
        self.assertEqual(400,self.client.put(self.scope('/prosoft/settings'),json={'version':0,'settings':bad}).status_code)
        self.post('/prosoft/preview',bad|{'period':'2026-11'},400)
        self.assertEqual(403,self.client.put(self.scope('/prosoft/settings'),headers={'X-CSRF-Token':''},json={'version':0,'settings':cfg}).status_code)
        created=self.client.post('/api/users',json={'username':'trc-reader','password':'Senha-ficticia-123!','role':'operator',
            'company_ids':[self.a['id']],'permissions':[{'company_id':self.a['id'],'routine':'accounting.prosoft','action':'read','effect':'allow'}]})
        self.assertEqual(201,created.status_code)
        with TestClient(self.app) as other:
            login=other.post('/api/login',json={'username':'trc-reader','password':'Senha-ficticia-123!'}).json()
            other.headers['X-CSRF-Token']=login['csrf_token'];self.activate(self.a['id'],client=other)
            self.assertEqual(403,other.post(self.scope('/prosoft/preview'),json=p).status_code)
            self.assertEqual(403,other.put(self.scope('/prosoft/settings'),json={'version':0,'settings':cfg}).status_code)


if __name__=='__main__':unittest.main()
