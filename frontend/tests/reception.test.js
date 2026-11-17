import test from 'node:test';
import assert from 'node:assert/strict';
import {reactive,nextTick} from 'vue';
import {createReception} from '../src/lib/reception.js';
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const overview=(provider='nfe_distribution')=>({preferences:{version:0,nfe_environment:'homologation',nfse_environment:'restricted_production'},state:{cursor:'0',busy:false,next_allowed_at:0},documents:[],receipts:[],offset:0,has_more:false,capabilities:{remote_available:provider==='nfe_distribution'}});
const tick=async()=>{await nextTick();await Promise.resolve();};
function setup(provider='nfe_distribution'){
 const state=reactive({companyId:1,period:'2026-11',module:'fiscal',session:{user:{id:8}},editor:null}),calls=[];let access=true;
 const c=createReception({state,provider,can:()=>access,scope:(s,cid=state.companyId)=>'/companies/'+cid+s,api:(path,options={})=>{const d=deferred();calls.push({path,options,...d});return d.promise;}});
 return {c,m:c.m,state,calls,deny:()=>{access=false;}};
}
test('distinct resources open through local GET only and ADN remote remains disabled',async()=>{
 const dfe=setup(),adn=setup('nfse_adn');dfe.c.activate();adn.c.activate();
 assert.match(dfe.calls[0].path,/\/reception\/nfe_distribution\?/);assert.match(adn.calls[0].path,/\/reception\/nfse_adn\?/);
 assert.equal(dfe.calls[0].options.method,undefined);dfe.calls[0].resolve(overview());adn.calls[0].resolve(overview('nfse_adn'));await tick();
 await adn.c.capture();assert.equal(adn.calls.length,1);assert.equal(dfe.m.provider,'nfe_distribution');assert.equal(adn.m.provider,'nfse_adn');
});
test('late loads and receipt selections cannot cross company or overwrite a later selection',async()=>{
 const f=setup();f.c.activate();const old=f.calls[0];f.state.companyId=2;f.c.reset();assert.equal(old.options.signal.aborted,true);
 old.resolve({...overview(),documents:[{nsu:'OLD'}]});f.calls[1].resolve(overview());await tick();assert.deepEqual([...f.m.data.documents],[]);
 const a=f.c.receipt('receipt-001'),b=f.c.receipt('receipt-002');f.calls[3].resolve({provider:'nfe_distribution',receipt_key:'receipt-002'});await b;f.calls[2].resolve({provider:'nfe_distribution',receipt_key:'receipt-001'});await a;assert.equal(f.m.receipt.receipt_key,'receipt-002');
 f.c.deactivate();assert.equal(f.m.receipt,null);assert.equal(f.m.data,null);
});
test('capture is single flight and an explicit uncertain retry reuses the same identification',async()=>{
 const f=setup();f.c.activate();f.calls[0].resolve(overview());await tick();
 const first=f.c.capture(),request=f.calls.at(-1);await f.c.capture();assert.equal(f.calls.length,2);assert.equal(f.state.editor.companyId,1);
 request.reject(Object.assign(new Error('Timeout'),{status:502}));await first;const body={...f.m.intent.body};assert.equal(f.state.editor,null);
 await f.c.capture();assert.equal(f.calls.length,2);
 const again=f.c.capture(true);assert.deepEqual(f.calls.at(-1).options.body,body);f.calls.at(-1).resolve({provider:'nfe_distribution',receipt_key:body.idempotency_key,state:'received'});await tick();f.calls.at(-1).resolve(overview());await again;
 assert.equal(f.m.intent,null);assert.equal(f.state.editor,null);
});
test('a previous company write cannot unlock the current operation or leave secrets/data behind',async()=>{
 const f=setup();f.c.activate();f.calls[0].resolve(overview());await tick();
 const older=f.c.check(),request=f.calls.at(-1);f.state.companyId=2;f.c.reset();f.calls.at(-1).resolve(overview());await tick();
 const current=f.c.check(),newer=f.calls.at(-1),editor=f.state.editor;request.resolve({ready:true,message:'old'});await older;assert.equal(f.state.editor,editor);assert.equal(f.m.check,null);assert.equal(f.m.busy,true);
 newer.resolve({ready:false,message:'new'});await current;assert.equal(f.m.check.message,'new');assert.equal(f.state.editor,null);
 f.deny();f.c.reset();const count=f.calls.length;await f.c.check();await f.c.capture();assert.equal(f.calls.length,count);assert.equal(f.c.report(),'');assert.equal(f.c.download({receipt_key:'x',nsu:'1'}),'');
});
test('report follows applied filters; editing a draft search does not export different unseen results',async()=>{
 const f=setup();f.c.activate();f.calls[0].resolve(overview());await tick();f.m.query='applied';const load=f.c.load();f.m.query='draft';f.calls.at(-1).resolve(overview());await load;
 assert.match(f.c.report(),/query=applied/);assert.doesNotMatch(f.c.report(),/query=draft/);
});
test('version requests and receipt responses cannot survive an environment change',async()=>{
 const f=setup();f.c.activate();f.calls[0].resolve(overview());await tick();
 const old=f.c.versions('a'.repeat(64)),request=f.calls.at(-1),receipt=f.c.receipt('old-environment-receipt'),oldReceipt=f.calls.at(-1);
 f.c.environment('production');f.calls.at(-1).resolve({...overview(),environment:'production'});await tick();
 request.resolve({provider:'nfe_distribution',environment:'homologation',record_id:'a'.repeat(64),versions:[{sha256:'OLD'}]});oldReceipt.resolve({provider:'nfe_distribution',environment:'homologation',receipt_key:'old'});await old;await receipt;
 assert.equal(f.m.document,null);assert.equal(f.m.receipt,null);assert.equal(f.m.documentLoading,false);
 const current=f.c.versions('b'.repeat(64));assert.match(f.calls.at(-1).path,/environment=production/);f.calls.at(-1).resolve({provider:'nfe_distribution',environment:'production',record_id:'b'.repeat(64),versions:[]});await current;assert.equal(f.m.document.record_id,'b'.repeat(64));
 f.c.deactivate();assert.equal(f.m.document,null);const count=f.calls.length;await f.c.versions('b'.repeat(64));assert.equal(f.calls.length,count);f.c.activate();assert.equal(f.calls.at(-1).options.method,undefined);f.calls.at(-1).resolve(overview());await tick();
});
test('later version selection wins; company change clears both provenance and old metadata',async()=>{
 const f=setup('nfse_adn');f.c.activate();f.calls[0].resolve(overview('nfse_adn'));await tick();
 const first=f.c.versions('a'.repeat(64)),a=f.calls.at(-1),second=f.c.versions('b'.repeat(64)),b=f.calls.at(-1);
 b.resolve({provider:'nfse_adn',environment:'restricted_production',record_id:'b'.repeat(64),versions:[]});await second;
 a.resolve({provider:'nfse_adn',environment:'restricted_production',record_id:'a'.repeat(64),versions:[]});await first;assert.equal(f.m.document.record_id,'b'.repeat(64));
 f.state.companyId=2;f.c.reset();assert.equal(f.m.document,null);assert.equal(f.m.documentLoading,false);f.calls.at(-1).resolve(overview('nfse_adn'));await tick();
 const wrong=f.c.versions('b'.repeat(64));f.calls.at(-1).resolve({provider:'nfse_adn',environment:'production',record_id:'b'.repeat(64),versions:[]});await wrong;assert.equal(f.m.document,null);assert.match(f.m.error,/outro serviço ou ambiente/);
});
