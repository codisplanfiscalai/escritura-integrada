import test from 'node:test';
import assert from 'node:assert/strict';
import {createProsoftExport,prosoftDefaults,prosoftDownload,prosoftManifest} from '../src/lib/prosoft-export.js';
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
function setup(area='fiscal'){
 const ctx={cid:1,year:'2026',module:area,period:'2026-11',area},calls=[];
 const saved={settings:prosoftDefaults(area,'0099'),version:2};
 let request=async(c,method,path,body)=>{calls.push({c:{...c},method,path,body});return method==='GET'?saved:method==='PUT'?{...saved,settings:body.settings,version:3}:{preview_hash:'synthetic',sha256:'synthetic-sha',manifest:{text_changes:[]},id:8,filename:'synthetic.zip'};};
 const controller=createProsoftExport({context:()=>ctx,request:(...args)=>request(...args),references:async()=>({accounts:[],centers:[],parties:[]})});
 return {...controller,ctx,calls,setRequest:value=>request=value,saved};
}
test('per-company saved values load, edits dirty the form and invalidate preview and download',async()=>{
 const c=setup();await c.load();assert.equal(c.s.version,2);assert.equal(c.dirty.value,false);
 await c.run();c.s.reviewed=true;await c.run(true);assert.equal(c.s.result.id,8);
 c.s.config.plan_code='0052';assert.equal(c.dirty.value,true);assert.equal(c.s.preview,null);assert.equal(c.s.result,null);assert.equal(c.s.reviewed,false);
 await c.save();assert.equal(c.s.version,3);assert.equal(c.dirty.value,false);assert.match(c.s.message,/salvos/);c.dispose();
});
test('preview snapshots company, competence, selected plan, config version and mappings',async()=>{
 const c=setup();await c.load();c.s.config.species[55]={code:'NFE',confirmed:true};c.s.config.record_types=['outgoing_notes'];await c.run();
 const call=c.calls.at(-1);assert.equal(call.c.cid,1);assert.equal(call.body.period,'2026-11');assert.equal(call.body.settings_version,2);assert.deepEqual(call.body.record_types,['outgoing_notes']);
 assert.deepEqual(call.body.species[55],{code:'NFE',confirmed:true});assert.equal(call.path,'/prosoft-fiscal/preview');
 c.s.config.species[55].code='NF';assert.equal(call.body.species[55].code,'NFE');c.dispose();
});
test('company switch discards pending load and clears all previous mapping and file state',async()=>{
 const c=setup();const pending=deferred();c.setRequest(()=>pending.promise);const old=c.load();
 c.ctx.cid=2;c.reset('0088');pending.resolve(c.saved);await old;
 assert.equal(c.s.loaded,false);assert.equal(c.s.config.company_code,'0088');assert.equal(c.s.preview,null);assert.equal(c.s.loading,false);c.dispose();
});
test('a late preview cannot cross month, year, company or module boundaries',async()=>{
 for(const change of [{period:'2026-12'},{year:'2027'},{cid:2},{module:'accounting'}]){
  const c=setup();await c.load();const pending=deferred();c.setRequest(()=>pending.promise);const old=c.run();
  Object.assign(c.ctx,change);c.invalidate();pending.resolve({preview_hash:'wrong'});await old;
  assert.equal(c.s.preview,null);assert.equal(c.s.result,null);assert.equal(c.s.busy,false);c.dispose();
 }
});
test('editing during a pending preview discards its response and confirmations',async()=>{
 const c=setup();await c.load();const pending=deferred();c.setRequest(()=>pending.promise);const old=c.run();
 c.s.config.plan_code='0053';pending.resolve({preview_hash:'wrong'});await old;assert.equal(c.s.preview,null);assert.equal(c.s.busy,false);c.dispose();
});
test('a late save cannot overwrite another company, even if it was accepted on the server',async()=>{
 const c=setup();await c.load();const pending=deferred();c.setRequest(()=>pending.promise);const save=c.save();
 c.ctx.cid=2;c.reset('0088');pending.resolve({settings:prosoftDefaults('fiscal','0099'),version:3});await save;
 assert.equal(c.s.config.company_code,'0088');assert.equal(c.s.version,0);assert.equal(c.s.message,'');c.dispose();
});
test('stale save conflict retains local draft and explicit reload replaces it',async()=>{
 const c=setup();await c.load();c.s.config.plan_code='0052';c.setRequest(async()=>{throw new Error('Os mapeamentos mudaram');});
 await c.save();assert.match(c.s.error,/mudaram/);assert.equal(c.s.config.plan_code,'0052');assert.equal(c.s.version,2);
 c.setRequest(async()=>({...c.saved,version:4}));await c.load(true);assert.equal(c.s.config.plan_code,'0050');assert.equal(c.s.version,4);assert.equal(c.dirty.value,false);c.dispose();
});
test('changing competence keeps unsaved company mappings while clearing preview',async()=>{
 const c=setup();await c.load();c.s.config.plan_code='0052';c.ctx.period='2026-10';await c.load();
 assert.equal(c.s.config.plan_code,'0052');assert.equal(c.dirty.value,true);assert.equal(c.s.preview,null);c.dispose();
});
test('another session settings change is reported without clobbering local drafts',async()=>{
 const c=setup();await c.load();c.s.config.plan_code='0052';c.setRequest(async()=>({...c.saved,version:3}));await c.load();
 assert.equal(c.s.config.plan_code,'0052');assert.equal(c.s.version,2);assert.match(c.s.error,/mudaram/);c.dispose();
});
test('ASCII and destination review apply to the displayed preview without changing config',async()=>{
 const c=setup();await c.load();await c.run();c.s.ascii=true;c.s.reviewed=true;assert.ok(c.s.preview);await c.run(true);
 const call=c.calls.at(-1);assert.equal(call.body.preview_hash,'synthetic');assert.equal(call.body.allow_ascii,true);assert.equal(call.body.destination_reviewed,true);
 assert.equal(c.dirty.value,false);assert.equal(prosoftDownload(c.s.result),'/api/companies/1/prosoft-fiscal/exports/8/download');c.dispose();
});
test('accounting uses its own endpoint and legacy file route',async()=>{
 const c=setup('accounting');await c.load();await c.run();c.s.reviewed=true;await c.run(true);
 assert.equal(c.calls.at(-1).path,'/prosoft/confirm');assert.equal(c.calls.at(-1).body.batch,'1');
 assert.equal(prosoftDownload(c.s.result),'/api/companies/1/exports/8/download');assert.equal(prosoftManifest(c.s.result),'/api/companies/1/prosoft/exports/8/manifest?download=1');c.dispose();
});
test('deactivated or disposed views reject pending work',async()=>{
 const c=setup();await c.load();const pending=deferred();c.setRequest(()=>pending.promise);const old=c.run();c.dispose();pending.resolve({preview_hash:'wrong'});await old;
 assert.equal(c.s.preview,null);assert.equal(c.s.result,null);
});

test('unsaved mappings follow immutable global identity when an alias gains a local ID',async()=>{
 const ctx={cid:1,year:'2026',module:'accounting',period:'2026-11',area:'accounting'};
 let records={accounts:[{id:-7,shared_entry_id:7,analytical:true,access_code:'123'}],used:[-7],centers:[],parties:[]};
 const c=createProsoftExport({context:()=>ctx,request:async()=>({settings:prosoftDefaults('accounting','99'),version:0}),references:async()=>records});
 await c.load();c.s.config.accounts[-7].code='700';c.s.config.accounts[-7].confirmed=true;
 records={...records,accounts:[{id:81,shared_entry_id:7,analytical:true,access_code:'123'}],used:[81]};await c.load();
 assert.equal(c.s.config.accounts[81].code,'700');assert.equal(c.s.config.accounts[-7],undefined);assert.equal(c.dirty.value,true);assert.equal(c.s.loading,false);c.dispose();
});
test('unmapped accounts outside the selected month are not expanded into the saved draft',async()=>{
 const ctx={cid:1,year:'2026',module:'accounting',period:'2026-11',area:'accounting'};
 const accounts=Array.from({length:10000},(_,i)=>({id:i+1,analytical:true,access_code:String(i+1)}));
 const c=createProsoftExport({context:()=>ctx,request:async()=>({settings:prosoftDefaults('accounting','99'),version:0}),references:async()=>({accounts,used:[3],centers:[],parties:[]})});
 await c.load();assert.deepEqual(Object.keys(c.s.config.accounts),['3']);c.ensureAccounts(accounts.slice(0,100));assert.equal(Object.keys(c.s.config.accounts).length,100);c.dispose();
});
test('a confirmed file response cannot recreate a download link after switching companies',async()=>{
 const c=setup();await c.load();await c.run();c.s.reviewed=true;
 const pending=deferred();c.setRequest(()=>pending.promise);const confirm=c.run(true);
 c.ctx.cid=2;c.reset('0088');pending.resolve({id:99,filename:'old-company.zip'});await confirm;
 assert.equal(c.s.result,null);assert.equal(c.s.preview,null);assert.equal(c.s.config.company_code,'0088');c.dispose();
});

test('reference map URL uses the confirmed company and cannot become a fiscal download',()=>{
 assert.equal(prosoftManifest({cid:7,id:91,area:'accounting'}),'/api/companies/7/prosoft/exports/91/manifest?download=1');
 assert.equal(prosoftManifest({cid:7,id:91,area:'fiscal'}),'');
});
