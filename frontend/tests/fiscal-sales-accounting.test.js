import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createRenderer,reactive,computed,nextTick,h,ref,KeepAlive} from 'vue';
const require=createRequire(import.meta.url),vue=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
const url=code=>`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`;
const flush=async()=>{await nextTick();await new Promise(r=>setTimeout(r,8));await nextTick();};let counter=0;
const doc=(id,extra={})=>({id,version:3,direction:'outgoing',number:`S${id}`,partner_name:'Cliente fictício',model:'55',series:'1',key:'',cfop:'5102',status:'booked',journal_id:null,total_cents:1001,issue_date:'2026-10-30',posting_date:'2026-11-06',period:'2026-11',...extra});
const model=(id=7,extra={})=>({id,active:true,name:'Modelo sintético',code:'VENDA',data:{status:'validated',direction:'outgoing',valid_from:'2026-01-01',valid_to:'',...extra}});
const cfg=(mode='individual',version=0)=>({mode,version,notice:'Histórico preservado.'});
const result=(extra={})=>({created_count:1,accounted_count:2,skipped:[],journals:[{id:10,number:1,date:'2026-11-06',total_cents:2002}],sources:[],notice:'Complementos preservam histórico.',...extra});
async function harness({denied=[],accountRows=[{id:31,access_code:'6',name:'Despesa sintética',active:true,analytical:true},{id:32,access_code:'4',name:'Fornecedor sintético',active:true,analytical:true}],centerRows=[]}={}){
 const key=`__salesAccounting${++counter}`,requests=[],lookups=[],visible=ref(true),updates=[];
 const state=reactive({companyId:1,module:'fiscal',period:'2026-11',contextBusy:false,refresh:0,editor:null,yearLocks:{},contextPreferences:{},session:{user:{role:'operator'},permissions:{}}});
 const can=(r,a='read')=>{void state.session.permissions;return !denied.includes(`${r}:${a}`)},captureContext=()=>({companyId:state.companyId,year:state.period.slice(0,4),module:state.module}),contextMatches=c=>c.companyId===state.companyId&&c.year===state.period.slice(0,4)&&c.module===state.module;
 globalThis[key]={state,company:computed(()=>({code:`SYN${state.companyId}`,name:'Empresa fictícia'})),can,captureContext,contextMatches,scope:(p,cid=state.companyId)=>`/companies/${cid}${p}`,changed:()=>updates.push(true),api:(path,options={})=>{if(path.endsWith('/accounts')||path.endsWith('/cost-centers')){lookups.push({path,options});return Promise.resolve(path.endsWith('/accounts')?accountRows:centerRows);}return new Promise((resolve,reject)=>requests.push({path,options,resolve,reject}));}};
 const mock=url(`export const {state,company,can,captureContext,contextMatches,scope,changed,api}=globalThis.${key};`);
 const source=await readFile(new URL('../src/views/FiscalSalesAccountingView.vue',import.meta.url),'utf8');
 const code=compileScript(parse(source).descriptor,{id:key}).content.replace(/from ['"]vue['"]/g,`from '${vue}'`).replace(/import (\w+) from ['"][^'"]+\.vue['"];?/g,'const $1={};').replace("from '../lib/workspace'",`from '${mock}'`).replace("from '../lib/format'",`from '${new URL('../src/lib/format.js',import.meta.url).href}'`).replace("from '../lib/context-preferences.js'",`from '${new URL('../src/lib/context-preferences.js',import.meta.url).href}'`);
 const component=(await import(url(code))).default;let view;const setup=component.setup;component.setup=(p,c)=>{view=setup(p,c);return()=>null;};
 const renderer=createRenderer({createElement:()=>({}),createText:()=>({}),setText:()=>{},setElementText:()=>{},createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null,patchProp:()=>{}});
 const app=renderer.createApp({setup:()=>()=>h(KeepAlive,null,()=>visible.value?h(component):null)});app.mount({});await flush();
 return {view,state,requests,lookups,updates,visible,denied,close:()=>{app.unmount();delete globalThis[key];}};
}
async function ready(h,docs=[doc(1),doc(2)],mode='individual',version=0,mods=[model()]){const start=h.requests.length-3;h.requests[start].resolve(cfg(mode,version));h.requests[start+1].resolve(docs);h.requests[start+2].resolve(mods);await flush();}
function select(h){h.view.selectFiltered();h.view.commonModel.value=7;h.view.applyModel();}

test('consulta captura empresa/exercício e nunca cria movimentos ao carregar',async()=>{
 const h=await harness();try{assert.deepEqual(h.requests.map(r=>r.path),['/companies/1/fiscal-sales-accounting/settings','/companies/1/documents?year=2026','/companies/1/masters/accounting_model']);await ready(h,[doc(1),doc(3,{direction:'incoming'})]);assert.equal(h.view.documents.value.length,1);assert.equal(h.view.config.value.mode,'individual');assert.ok([...h.requests,...h.lookups].every(r=>!r.options.method));assert.equal(h.lookups.length,2);assert.equal(h.view.selectedIds.value.length,0);assert.equal(h.view.canSubmit.value,false);}finally{h.close();}
});
test('seleção inclui páginas, exige contas explícitas ou modelo opcional e filtros limpam sem confundir emissão',async()=>{
 const h=await harness();try{await ready(h,Array.from({length:53},(_,i)=>doc(i+1)).concat([doc(80,{period:'2026-12',posting_date:'2026-12-02'}),doc(81,{journal_id:9}),doc(82,{status:'pending'}),doc(83,{book_cancellation:{}})]));h.view.selectFiltered();assert.equal(h.view.selection.value.length,53);assert.equal(h.view.visible.value.length,50);assert.match(h.view.selectionIssue.value,/contas/);h.view.commonModel.value=7;h.view.applyModel();assert.equal(h.view.canSubmit.value,true);assert.equal(h.view.selectedTotal.value,53053n);h.view.page.value=2;await flush();assert.equal(h.view.selection.value.length,53);h.view.query.value='S80';await flush();assert.equal(h.view.selection.value.length,0);assert.equal(h.view.filtered.value.length,0);h.view.month.value='12';assert.equal(h.view.filtered.value.length,1);assert.equal(h.state.period,'2026-11');}finally{h.close();}
});
test('modelos vencidos, não revisados ou de entrada não são escolhidos automaticamente',async()=>{
 const h=await harness();try{await ready(h,[doc(1)],'individual',0,[model(),model(8,{direction:'incoming'}),model(9,{status:'draft'}),model(10,{valid_to:'2026-10-31'})]);assert.deepEqual(h.view.availableModels.value.map(m=>m.id),[7,10]);h.view.selectFiltered();h.view.commonModel.value=10;h.view.applyModel();assert.match(h.view.error.value,/vigente/);assert.equal(h.view.canSubmit.value,false);h.view.commonModel.value=7;h.view.applyModel();assert.equal(h.view.canSubmit.value,true);}finally{h.close();}
});
test('modo é persistido por empresa com versão e dupla gravação é impedida',async()=>{
 const h=await harness();try{await ready(h);h.view.mode.value='daily';select(h);assert.equal(h.view.canSubmit.value,false);const p=h.view.saveMode();await h.view.saveMode();assert.equal(h.requests.length,4);assert.deepEqual(h.requests[3].options.body,{version:0,mode:'daily'});assert.deepEqual(h.requests[3].options.context,{companyId:1,year:'2026',module:'fiscal'});h.requests[3].resolve(cfg('daily',1));await p;assert.equal(h.view.modeDirty.value,false);assert.equal(h.view.config.value.version,1);assert.equal(h.state.editor,null);assert.equal(h.updates.length,0,'configuração não anuncia geração');}finally{h.close();}
});
test('conflito ao salvar preserva a edição e resposta tardia não troca a configuração de outra empresa',async()=>{
 const h=await harness();try{await ready(h);h.view.mode.value='daily';let p=h.view.saveMode();h.requests[3].reject(Object.assign(new Error('Versão obsoleta'),{status:409}));await p;assert.equal(h.view.mode.value,'daily');assert.equal(h.view.config.value.version,0);assert.match(h.view.error.value,/obsoleta/);p=h.view.saveMode();h.state.companyId=2;await flush();h.requests[4].resolve(cfg('daily',1));await p;await flush();await ready(h,[doc(90)],'individual');assert.equal(h.view.config.value.mode,'individual');assert.equal(h.view.documents.value[0].id,90);}finally{h.close();}
});
test('cargas fora de ordem e erros antigos não vencem empresa/exercício mais recentes',async()=>{
 const h=await harness();try{const old=h.requests.slice();h.state.companyId=2;h.state.period='2027-01';await flush();await ready(h,[doc(99,{period:'2027-01',posting_date:'2027-01-02'})],'daily',4);old[0].reject(new Error('Erro da empresa antiga'));old[1].resolve([doc(1)]);old[2].resolve([model()]);await flush();assert.equal(h.view.error.value,'');assert.equal(h.view.config.value.version,4);assert.equal(h.view.documents.value[0].id,99);assert.equal(h.view.loading.value,false);}finally{h.close();}
});
test('geração envia versões/modelos e uma só chave; clique repetido produz uma requisição',async()=>{
 const h=await harness();try{await ready(h,undefined,'daily',2);select(h);const p=h.view.generate();await h.view.generate();assert.equal(h.requests.length,4);const r=h.requests[3];assert.equal(r.path,'/companies/1/fiscal-sales-accounting/generate');assert.equal(r.options.body.settings_version,2);assert.deepEqual(r.options.body.entries,[{document_id:1,version:3,model_id:7},{document_id:2,version:3,model_id:7}]);assert.ok(r.options.body.idempotency_key);assert.equal(h.state.editor.companyId,1);r.resolve(result());await p;assert.equal(h.view.result.value.created_count,1);assert.equal(h.view.intent.value,null);assert.equal(h.view.selectedIds.value.length,0);assert.equal(h.updates.length,1);assert.equal(h.state.editor,null);}finally{h.close();}
});
test('interrupção mantém a intenção e repetição usa exatamente a chave/corpo anteriores',async()=>{
 const h=await harness();try{await ready(h);select(h);let p=h.view.generate();const before=JSON.stringify(h.requests[3].options.body);h.requests[3].reject(new TypeError('Failed to fetch'));await p;assert.equal(h.view.result.value,null);assert.match(h.view.error.value,/não foi confirmado/);assert.equal(h.view.locked.value,true);h.view.commonModel.value=999;h.view.applyModel();await h.view.generate();assert.equal(h.requests.length,4);p=h.view.generate(true);assert.equal(JSON.stringify(h.requests[4].options.body),before);h.requests[4].resolve(result({duplicate:true}));await p;assert.equal(h.view.result.value.duplicate,true);assert.equal(h.view.intent.value,null);}finally{h.close();}
});
test('erro HTTP não aparece como sucesso e permite corrigir intenção; atualização confere resultado incerto',async()=>{
 const h=await harness();try{await ready(h);select(h);let p=h.view.generate();h.requests[3].reject(Object.assign(new Error('Modelo revogado'),{status:403}));await p;assert.equal(h.view.result.value,null);assert.equal(h.view.intent.value,null);assert.match(h.view.error.value,/revogado/);p=h.view.generate();h.requests[4].reject(Object.assign(new Error('Unavailable'),{status:503}));await p;assert.ok(h.view.intent.value);p=h.view.load({discardIntent:true});await ready(h,[doc(1,{journal_id:10}),doc(2,{journal_id:10})]);await p;assert.equal(h.view.intent.value,null);h.view.selectFiltered();assert.equal(h.view.selectedIds.value.length,0);assert.equal(h.updates.length,0);}finally{h.close();}
});
test('competência fechada impede geração mesmo sob configuração legada permissiva e reabertura libera',async()=>{
 const h=await harness();try{await ready(h);select(h);h.state.yearLocks={accounting:{'2026-11':{closed:true}}};await flush();assert.equal(h.view.canSubmit.value,false);assert.match(h.view.selectionIssue.value,/fechada/);await h.view.generate();assert.equal(h.requests.length,3);h.state.yearLocks.accounting['2026-11'].closed=false;await flush();assert.equal(h.view.canSubmit.value,true);}finally{h.close();}
});
test('consulta negada não busca dados; revogação apaga dados e rastreabilidade já carregados',async()=>{
 const h=await harness({denied:['accounting.accounts:read']});try{assert.equal(h.requests.length,0);h.denied.length=0;h.state.session.permissions={changed:['read']};await flush();await ready(h);const p=h.view.showTrace('journal',10);h.requests[3].resolve({journal:result().journals[0],sources:[]});await p;assert.ok(h.view.trace.value.data);h.denied.push('accounting.accounts:read');h.state.session.permissions={changed:[]};await flush();assert.equal(h.view.trace.value,null);assert.equal(h.view.config.value,null);assert.equal(h.view.documents.value.length,0);}finally{h.close();}
});
test('rastros fechados, substituídos e de outro contexto ignoram respostas e erros tardios',async()=>{
 const h=await harness();try{await ready(h);let p=h.view.showTrace('journal',10);h.view.closeTrace();h.requests[3].resolve({sources:[{document_id:1}]});await p;assert.equal(h.view.trace.value,null);p=h.view.showTrace('document',1);const latest=h.view.showTrace('journal',20);h.requests[5].resolve({journal:{id:20},sources:[]});await latest;h.requests[4].reject(new Error('antigo'));await p;assert.equal(h.view.trace.value.data.journal.id,20);assert.equal(h.view.traceError.value,'');p=h.view.showTrace('document',2);h.state.companyId=2;await flush();h.requests[6].resolve({document:doc(2)});await p;assert.equal(h.view.trace.value,null);}finally{h.close();}
});
test('KeepAlive cancela leitura oculta e recarrega; resposta pós-unmount não remove editor de outro componente',async()=>{
 const h=await harness();try{const old=h.requests.slice();h.visible.value=false;await flush();old[0].resolve(cfg('daily',8));old[1].resolve([doc(1)]);old[2].resolve([model()]);await flush();assert.equal(h.view.config.value,null);h.visible.value=true;await flush();await ready(h);select(h);const p=h.view.generate();const request=h.requests.at(-1);h.close();const owner={name:'Outro editor'};h.state.editor=owner;request.resolve(result());await p;assert.equal(h.state.editor.name,owner.name);assert.equal(h.updates.length,0);}finally{/* unmounted above */}
});
test('limite não trunca notas e resultados com ignoradas preservam a informação',async()=>{
 const h=await harness();try{await ready(h,Array.from({length:1001},(_,i)=>doc(i+1)));h.view.selectFiltered();assert.equal(h.view.selectedIds.value.length,0);assert.match(h.view.error.value,/mais de 1000/);h.view.query.value='S1001';select(h);const p=h.view.generate();h.requests[3].resolve(result({created_count:0,accounted_count:0,journals:[],skipped:[{document_id:1001,reason:'already_accounted'}]}));await p;assert.equal(h.view.result.value.created_count,0);assert.equal(h.view.result.value.skipped.length,1);}finally{h.close();}
});

test('total selecionado conserva centavos além do inteiro seguro de JavaScript',async()=>{
 const h=await harness();try{await ready(h,Array.from({length:101},(_,i)=>doc(i+1,{total_cents:99999999999999})));h.view.selectFiltered();assert.equal(h.view.selectedTotal.value,10099999999999899n);assert.equal(h.view.selectedAmount.value,'R$ 100.999.999.999.998,99');}finally{h.close();}
});

test('entradas usam endpoint próprio, modelos compatíveis e modo individual sem salvar modo das saídas',async()=>{
 const h=await harness();try{await ready(h,undefined,'daily',3);select(h);h.view.direction.value='incoming';await flush();assert.equal(h.view.selectedIds.value.length,0);assert.equal(h.view.result.value,null);await ready(h,[doc(8,{direction:'incoming',cfop:'1102'}),doc(9)],'daily',3,[model(),model(8,{direction:'incoming'}),model(9,{direction:'both'})]);assert.equal(h.view.documents.value.length,1);assert.deepEqual(h.view.availableModels.value.map(m=>m.id),[8,9]);assert.equal(h.view.modeDirty.value,false);h.view.selectFiltered();h.view.commonModel.value=8;h.view.applyModel();const count=h.requests.length;await h.view.saveMode();assert.equal(h.requests.length,count);let p=h.view.generate();let first=h.requests.at(-1);assert.equal(first.path,'/companies/1/fiscal-purchases-accounting/generate');first.reject(new TypeError('Resposta perdida'));await p;p=h.view.generate(true);assert.equal(h.requests.at(-1).path,first.path);assert.deepEqual(h.requests.at(-1).options.body,first.options.body);h.requests.at(-1).resolve(result({mode:'individual',duplicate:true}));await p;assert.equal(h.view.result.value.duplicate,true);}finally{h.close();}
});
test('prévia não exige execução, não marca dados alterados e fechar ignora resposta tardia',async()=>{
 const h=await harness();try{await ready(h);select(h);const p=h.view.showPreview();const r=h.requests.at(-1);assert.equal(r.path,'/companies/1/fiscal-sales-accounting/preview');assert.equal(h.state.editor,null);assert.equal(h.view.intent.value,null);h.view.clearPreview();assert.ok(r.options.signal.aborted);r.resolve(result({preview:true}));await p;assert.equal(h.view.preview.value,null);assert.equal(h.updates.length,0);assert.equal(h.view.canSubmit.value,true);const next=h.view.showPreview();h.requests.at(-1).resolve(result({preview:true,journals:[]}));await next;assert.ok(h.view.preview.value.preview);h.view.reason.value='Histórico editado';assert.equal(h.view.preview.value,null);}finally{h.close();}
});
test('troca de sentido aborta prévia e descarta cargas e erros antigos sem misturar seleção',async()=>{
 const h=await harness();try{await ready(h);select(h);const p=h.view.showPreview(),old=h.requests.at(-1);h.view.direction.value='incoming';await flush();assert.ok(old.options.signal.aborted);await ready(h,[doc(44,{direction:'incoming'})],'daily',2,[model(8,{direction:'incoming'})]);old.reject(new Error('Prévia antiga'));await p;assert.equal(h.view.error.value,'');assert.equal(h.view.preview.value,null);assert.equal(h.view.documents.value[0].id,44);assert.equal(h.view.selectedIds.value.length,0);h.view.selectFiltered();h.view.commonModel.value=8;h.view.applyModel();const q=h.view.showPreview();assert.equal(h.requests.at(-1).path,'/companies/1/fiscal-purchases-accounting/preview');h.state.module='accounting';await flush();h.requests.at(-4).resolve(result({preview:true}));await q;assert.equal(h.view.preview.value,null);}finally{h.close();}
});
test('os dois menus aprovados abrem o mesmo componente com permissões de cada área',async()=>{
 const app=await readFile(new URL('../src/App.vue',import.meta.url),'utf8');
 assert.match(app,/id:'sales-accounting',label:'Integração Contábil',icon:'journal',component:FiscalSalesAccountingView,module:'fiscal',routine:'fiscal.documents'/);
 assert.match(app,/id:'fiscal-accounting',label:'Integração Fiscal',icon:'documents',component:FiscalSalesAccountingView,module:'accounting',routine:'accounting.journals'/);
});

test('contas diretas são o caminho padrão sem modelos nem permissão de modelos',async()=>{
 const h=await harness({denied:['accounting.histories:read']});try{
 assert.equal(h.requests.length,2);assert.ok(!h.requests.some(r=>r.path.includes('accounting_model')));
 h.requests[0].resolve(cfg('daily',2));h.requests[1].resolve([doc(1),doc(2)]);await flush();
 h.view.selectFiltered();assert.equal(h.view.models.value.length,0);assert.equal(h.view.canSubmit.value,false);
 h.view.debitAccount.value=31;h.view.creditAccount.value=32;assert.equal(h.view.canSubmit.value,true);
 const p=h.view.showPreview();const r=h.requests.at(-1);assert.equal(r.path,'/companies/1/fiscal-sales-accounting/preview');
 assert.deepEqual(r.options.body.entries,[1,2].map(id=>({document_id:id,version:3,debit_account_id:31,credit_account_id:32,cost_center_id:null})));
 assert.equal(h.state.editor,null);r.resolve(result({preview:true}));await p;assert.ok(h.view.preview.value);
 const q=h.view.generate();const call=h.requests.at(-1);assert.ok(!('model_id' in call.options.body.entries[0]));call.resolve(result());await q;assert.equal(h.updates.length,1);
 }finally{h.close();}
});

test('centro exigido, contas iguais e histórico alterado invalidam prévia direta',async()=>{
 const h=await harness({accountRows:[{id:31,active:true,analytical:true,requires_cost_center:true},{id:32,active:true,analytical:true}],centerRows:[{id:9,code:'C9',active:true}]});try{
 await ready(h);h.view.selectFiltered();h.view.debitAccount.value=31;h.view.creditAccount.value=31;assert.match(h.view.selectionIssue.value,/diferentes/);
 h.view.creditAccount.value=32;assert.match(h.view.selectionIssue.value,/centro/);h.view.costCenter.value=9;assert.equal(h.view.canSubmit.value,true);
 const p=h.view.showPreview();assert.equal(h.requests.at(-1).options.body.entries[0].cost_center_id,9);h.requests.at(-1).resolve(result({preview:true}));await p;
 h.view.reason.value='Histórico escolhido';assert.equal(h.view.preview.value,null);assert.equal(h.view.canSubmit.value,true);
 }finally{h.close();}
});

test('modelo é opcional por nota e pode voltar a contas diretas sem nova geração',async()=>{
 const h=await harness();try{await ready(h);select(h);h.view.debitAccount.value=31;h.view.creditAccount.value=32;
 h.view.modelIds.value[2]='';assert.deepEqual(h.view.accountingEntries(),[{document_id:1,version:3,model_id:7},{document_id:2,version:3,debit_account_id:31,credit_account_id:32,cost_center_id:null}]);
 h.view.useDirectAccounts();assert.ok(h.view.accountingEntries().every(e=>!('model_id' in e)));assert.equal(h.requests.length,3);assert.equal(h.updates.length,0);
 h.state.companyId=2;await flush();assert.equal(h.view.debitAccount.value,'');assert.equal(h.view.creditAccount.value,'');assert.equal(h.view.selectedIds.value.length,0);
 }finally{h.close();}
});

test('intenção direta perdida conserva contas e histórico exatos na repetição',async()=>{
 const h=await harness();try{await ready(h);h.view.selectFiltered();h.view.debitAccount.value=31;h.view.creditAccount.value=32;h.view.reason.value='Escolha sintética';
 let p=h.view.generate();const first=h.requests.at(-1);first.reject(new TypeError('Resposta perdida'));await p;assert.ok(h.view.intent.value);
 h.view.debitAccount.value=32;h.view.reason.value='Edição não enviada';p=h.view.generate(true);assert.deepEqual(h.requests.at(-1).options.body,first.options.body);
 h.requests.at(-1).resolve(result({duplicate:true}));await p;assert.equal(h.view.result.value.duplicate,true);
 }finally{h.close();}
});

test('alias de conta global continua válido após materialização e não permite débito/crédito equivalentes',async()=>{
 const h=await harness({accountRows:[{id:-81,shared_entry_id:81,active:true,analytical:true},{id:-82,shared_entry_id:82,active:true,analytical:true}]});try{
 await ready(h);h.view.selectFiltered();h.view.debitAccount.value=-81;h.view.creditAccount.value=-82;assert.equal(h.view.canSubmit.value,true);
 h.view.accounts.value=[{id:41,shared_entry_id:81,active:true,analytical:true},{id:42,shared_entry_id:82,active:true,analytical:true}];
 assert.equal(h.view.canSubmit.value,true);assert.equal(h.view.accountingEntries()[0].debit_account_id,-81);
 h.view.creditAccount.value=41;assert.match(h.view.selectionIssue.value,/diferentes/);assert.equal(h.view.canSubmit.value,false);
 }finally{h.close();}
});

test('subguias preservam seleção, contas, histórico, filtros e prévia sem novas consultas',async()=>{
 const h=await harness();try{await ready(h);h.view.selectFiltered();h.view.debitAccount.value=31;h.view.creditAccount.value=32;h.view.reason.value='Histórico sintético';
 h.view.selectSection('accounting');const p=h.view.showPreview();h.requests.at(-1).resolve(result({preview:true}));await p;
 const requests=h.requests.length,lookups=h.lookups.length,body=JSON.stringify(h.view.accountingEntries());
 for(const section of ['notes','settings','accounting','notes','accounting','settings','notes','accounting']){h.view.selectSection(section);await flush();}
 assert.equal(h.requests.length,requests);assert.equal(h.lookups.length,lookups);assert.equal(JSON.stringify(h.view.accountingEntries()),body);
 assert.equal(h.view.reason.value,'Histórico sintético');assert.equal(h.view.month.value,'11');assert.equal(h.view.status.value,'all');assert.equal(h.view.preview.value.preview,true);assert.equal(h.updates.length,0);
 }finally{h.close();}
});

test('cabeçalho acompanha o módulo e contexto novo retorna à consulta sem reutilizar seleção',async()=>{
 const h=await harness();try{await ready(h);assert.equal(h.view.accessTitle.value,'Integração Contábil');select(h);h.view.selectSection('settings');
 h.state.module='accounting';await flush();assert.equal(h.view.accessTitle.value,'Integração Fiscal');assert.equal(h.view.section.value,'notes');assert.equal(h.view.selectedIds.value.length,0);
 await ready(h);h.view.selectFiltered();h.view.debitAccount.value=31;h.view.creditAccount.value=32;h.view.selectSection('accounting');
 h.state.companyId=2;h.state.period='2027-01';await flush();assert.equal(h.view.section.value,'notes');assert.equal(h.view.debitAccount.value,'');assert.equal(h.view.config.value,null);assert.equal(h.view.preview.value,null);
 }finally{h.close();}
});

test('cancelar prévia mantém seleção e subguia atual e ignora conclusão tardia',async()=>{
 const h=await harness();try{await ready(h);select(h);h.view.selectSection('accounting');const p=h.view.showPreview(),request=h.requests.at(-1);
 h.view.selectSection('notes');h.view.clearPreview();assert.ok(request.options.signal.aborted);request.resolve(result({preview:true}));await p;
 assert.equal(h.view.preview.value,null);assert.equal(h.view.previewLoading.value,false);assert.equal(h.view.selectedIds.value.length,2);assert.equal(h.view.section.value,'notes');assert.equal(h.updates.length,0);
 }finally{h.close();}
});

test('rateio optativo lê pagamentos, preserva contas nas subguias e captura payload imutável',async()=>{
 const h=await harness();try{
 await ready(h,[doc(1)],'daily');h.view.selectFiltered();assert.equal(h.requests.length,3);
 h.view.debitMode.value='payments';await flush();const read=h.requests.at(-1);assert.ok(read.path.endsWith('/payments'));assert.deepEqual(read.options.body,{entries:[{document_id:1,version:3}]});
 read.resolve({documents:[{document_id:1,version:3,change_cents:0,total_cents:1001,issue:'',payments:[{index:0,method:'01',amount_cents:600},{index:1,method:'03',amount_cents:401}]}]});await flush();
 h.view.paymentAccounts.value={'01':31,'03':31};h.view.creditAccount.value=32;h.view.reason.value='Rateio sintético';assert.equal(h.view.canSubmit.value,true);
 const count=h.requests.length;h.view.section.value='notes';h.view.section.value='settings';h.view.section.value='accounting';await flush();assert.equal(h.requests.length,count);assert.equal(h.view.paymentAccounts.value['01'],31);
 const preview=h.view.showPreview();const request=h.requests.at(-1);assert.ok(request.path.endsWith('/preview'));
 assert.deepEqual(request.options.body.entries,[{document_id:1,version:3,payment_accounts:[{method:'01',account_id:31},{method:'03',account_id:31}],change_allocations:[],credit_account_id:32,cost_center_id:null}]);
 h.view.paymentAccounts.value['01']=32;assert.equal(request.options.body.entries[0].payment_accounts[0].account_id,31);request.resolve(result({preview:true}));await preview;assert.equal(h.view.preview.value,null);
 }finally{h.close();}
});

test('cancelamento e contexto descartam pagamentos atrasados e não transportam mapeamentos',async()=>{
 const h=await harness();try{
 await ready(h,[doc(1)]);h.view.selectFiltered();h.view.debitMode.value='payments';await flush();const old=h.requests.at(-1);h.view.cancelPayments();assert.equal(old.options.signal.aborted,true);old.resolve({documents:[{document_id:1,payments:[],issue:''}]});await flush();assert.equal(h.view.paymentData.value.length,0);assert.equal(h.view.canSubmit.value,false);
 const retry=h.view.loadPayments();const pending=h.requests.at(-1);h.view.paymentAccounts.value={'01':31};h.state.companyId=2;await flush();assert.equal(pending.options.signal.aborted,true);pending.resolve({documents:[{document_id:1,payments:[],issue:''}]});await retry;assert.equal(h.view.paymentData.value.length,0);assert.deepEqual(h.view.paymentAccounts.value,{});assert.equal(h.view.debitMode.value,'single');assert.equal(h.view.selectedIds.value.length,0);
 }finally{h.close();}
});

test('troco exige distribuição exata em centavos e selecionar modelo restaura débito único',async()=>{
 const h=await harness();try{
 await ready(h,[doc(1)]);h.view.selectFiltered();h.view.debitMode.value='payments';await flush();h.requests.at(-1).resolve({documents:[{document_id:1,version:3,issue:'',change_cents:100,payments:[{index:0,method:'01',amount_cents:1101}]}]});await flush();h.view.paymentAccounts.value={'01':31};h.view.creditAccount.value=32;
 assert.match(h.view.paymentIssue.value,/troco/);h.view.paymentChanges.value={'1:0':'1,00'};assert.equal(h.view.canSubmit.value,true);assert.equal(h.view.accountingEntries()[0].change_allocations[0].amount_cents,100);
 h.view.paymentChanges.value={'1:0':'0,999'};assert.equal(h.view.canSubmit.value,false);h.view.commonModel.value=7;h.view.applyModel();assert.equal(h.view.debitMode.value,'single');assert.equal(h.view.modelIds.value[1],7);assert.equal(h.view.canSubmit.value,true);
 }finally{h.close();}
});
