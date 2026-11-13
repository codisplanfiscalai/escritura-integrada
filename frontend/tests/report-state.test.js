import test from 'node:test';
import assert from 'node:assert/strict';
import {latestRequest,reportKindsForArea,reportFileUrl} from '../src/lib/report-state.js';
import {readFile} from 'node:fs/promises';

test('consulta anterior não conclui nem remove carregamento da consulta nova',()=>{
 const requests=latestRequest(),first=requests.begin(),second=requests.begin();
 assert.equal(requests.current(first),false);assert.equal(requests.current(second),true);
 requests.invalidate();assert.equal(requests.current(second),false);
});
test('catálogo é isolado por área, inclusive após trocar área',()=>{
 const kinds={ledger:'Razão','fiscal-entries':'Entradas',financial:'Títulos','cash-flow':'Caixa',partners:'Parceiros'};
 assert.deepEqual(Object.keys(reportKindsForArea(kinds,'accounting')),['ledger']);
 assert.deepEqual(Object.keys(reportKindsForArea(kinds,'fiscal')),['fiscal-entries']);
 assert.deepEqual(Object.keys(reportKindsForArea(kinds,'financial')),['financial','cash-flow','partners']);
});
test('exportação e impressão preservam URL capturada, empresa, filtros e paginação',()=>{
 const captured='/companies/12/business-reports/ledger?start=2026-01-01&end=2026-12-31&first_page=8&model=prosoft-ledger-v1';
 for(const format of ['csv','xlsx','pdf']) assert.equal(reportFileUrl(captured,format),`/api${captured}&format=${format}`);
 assert.equal(reportFileUrl(captured,'pdf',true),`/api${captured}&format=pdf&purpose=print`);
});
test('prévia exige impressão e invalida resultado nas mudanças de contexto e tipo',async()=>{
 const source=await readFile(new URL('../src/views/ReportsView.vue',import.meta.url),'utf8');
 assert.match(source,/preview&&can\(routine,'print'\)/);
 assert.match(source,/watch\(kind,\(\)=>\{invalidate\(\)/);
 assert.match(source,/state.companyId,state.period,props.area/);
 assert.match(source,/finally\{if\(requests.current\(seq\)\)busy.value=false/);
 assert.match(source,/v-allow="\[routine,'export'\]"/);
});
test('prévia revoga objetos, aborta consultas e oferece fallback nativo',async()=>{
 const source=await readFile(new URL('../src/components/ReportPdfPreview.vue',import.meta.url),'utf8');
 for(const pattern of [/supportsEmbeddedPdf\(\)/,/controller\?\.abort\(\)/,/URL.revokeObjectURL/,/onBeforeUnmount\(dispose\)/,/readFileResponse\(response\)/,/token===generation/,/Restaurar prévia/,/target="_blank" rel="noopener"/]) assert.match(source,pattern);
});

test('componente: consultas interrompidas não substituem o contexto novo e exportam os filtros gerados',async()=>{
 const {parse,compileScript}=await import('@vue/compiler-sfc');
 const {createRenderer,reactive,ref,nextTick}=await import('vue');
 const {createRequire}=await import('node:module');
 const {pathToFileURL}=await import('node:url');
 const require=createRequire(import.meta.url);
 const vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
 const state=reactive({companyId:1,period:'2026-01',contextBusy:false});
 const pending=[];
 globalThis.__reportTest={state,api:url=>new Promise((resolve,reject)=>pending.push({url,resolve,reject})),scope:(url,cid=state.companyId)=>`/companies/${cid}${url}`,useResource:(_load,initial=[])=>({data:ref(initial)}),notify:()=>{},can:()=>true,allowedApi:()=>Promise.resolve([])};
 const mock=`data:text/javascript;base64,${Buffer.from('export const {state,api,scope,useResource,notify,can,allowedApi}=globalThis.__reportTest;').toString('base64')}`;
 const source=await readFile(new URL('../src/views/ReportsView.vue',import.meta.url),'utf8');
 const {descriptor}=parse(source);
 let code=compileScript(descriptor,{id:'reports-state-test'}).content
  .replace(/from ['"]vue['"]/g,`from '${vueUrl}'`)
  .replace(/import (\w+) from ['"][^'"]+\.vue['"];?/g,'const $1={};')
  .replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`)
  .replace(/from ['"]\.\.\/lib\/context-preferences\.js['"]/g,`from '${new URL('../src/lib/context-preferences.js',import.meta.url).href}'`)
  .replace(/from ['"]\.\.\/lib\/(format|report-state|report-presentation)['"]/g,(_,name)=>`from '${new URL(`../src/lib/${name}.js`,import.meta.url).href}'`);
 const component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;
 let view;
 const original=component.setup;
 component.setup=(props,context)=>{view=original(props,context);return ()=>null;};
 const renderer=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null});
 const app=renderer.createApp(component,{area:'accounting'});app.mount({});
 try {
  const first=view.run();assert.equal(pending.length,1);assert.equal(view.busy.value,true);
  await view.run();assert.equal(pending.length,1,'repeated submit is ignored');
  state.companyId=2;await nextTick();assert.equal(view.busy.value,false);
  const second=view.run();assert.equal(pending.length,2);
  pending[0].resolve({rows:[],company_id:1,kind:'trial-balance'});await first;
  assert.equal(view.busy.value,true,'old finally must not clear new request');assert.equal(view.result.value,null);
  pending[1].resolve({rows:[],company_id:2,kind:'trial-balance'});await second;
  const captured=view.result.value.url;view.start.value='2026-02-01';await nextTick();
  assert.equal(view.filtersChanged.value,true);assert.equal(view.result.value.url,captured);
  view.kind.value='ledger';await nextTick();assert.equal(view.result.value,null);
  assert.equal(view.model.value,'prosoft-ledger-v1','Razão usa o modelo de referência por padrão');
  view.firstPage.value=19;view.showNumbers.value=true;
  assert.equal(view.parameters().get('first_page'),'19');
  assert.equal(view.parameters().get('show_numbers'),'true');
  view.model.value='internal';
  assert.equal(view.parameters().get('first_page'),'1');
  assert.equal(view.parameters().get('show_numbers'),'false');
  view.model.value='prosoft-ledger-v1';
  assert.equal(view.parameters().get('first_page'),'19');
  assert.equal(view.parameters().get('show_numbers'),'true');
  view.model.value='internal-diary';
  assert.equal(view.parameters().get('first_page'),'19');
  assert.equal(view.parameters().get('show_numbers'),'false');
  view.model.value='internal';
  const third=view.run();view.kind.value='diary';await nextTick();
  pending[2].reject(new Error('old failure'));await third;assert.equal(view.error.value,'');
  assert.equal(view.model.value,'internal-diary');
  view.kind.value='fiscal-entries';await nextTick();assert.equal(view.model.value,'reference-entries-p1a-v1');
  view.kind.value='fiscal-outputs';await nextTick();assert.equal(view.model.value,'reference-outputs-p2a-v1');
  view.kind.value='fiscal-items';await nextTick();assert.equal(view.model.value,'internal-fiscal-items');
 }finally{app.unmount();delete globalThis.__reportTest;}
});


test('CSS compilado da prévia maximizada prevalece sobre wide e limites globais',async()=>{
 const {parse,compileStyle}=await import('@vue/compiler-sfc');
 const source=await readFile(new URL('../src/components/ReportPdfPreview.vue',import.meta.url),'utf8');
 const {descriptor}=parse(source);
 const compiled=compileStyle({source:descriptor.styles[0].content,id:'data-v-report-preview',scoped:true});
 assert.deepEqual(compiled.errors,[]);
 const rule=compiled.code.match(/\.modal-overlay \.modal-dialog:has\(\.report-pdf-maximized\)\s*\{([^}]+)\}/);
 assert.ok(rule,'Seletor com três classes deve prevalecer sobre .modal-dialog.wide (duas classes).');
 assert.match(rule[1],/width:calc\(100vw - 32px\)/);
 assert.match(rule[1],/height:calc\(100dvh - 32px\)/);
 assert.match(rule[1],/max-width:none/);assert.match(rule[1],/max-height:none/);
 assert.match(compiled.code,/\.modal-overlay:has\(\.report-pdf-maximized\)\s*\{padding:16px/);
});

test('relatório operacional explica linhas fiscais e abre críticas do mesmo período gerado',async()=>{
 const {parse,compileScript}=await import('@vue/compiler-sfc');
 const {createRenderer,reactive,ref,nextTick}=await import('vue');
 const {createRequire}=await import('node:module');const {pathToFileURL}=await import('node:url');
 const require=createRequire(import.meta.url),vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
 const state=reactive({companyId:1,period:'2026-09',contextBusy:false,contextPreferences:{year:'2026',month:'09'}}),pending=[];
 globalThis.__reportOperational={state,api:url=>new Promise((resolve,reject)=>pending.push({url,resolve,reject})),scope:(url,cid=1)=>`/companies/${cid}${url}`,useResource:(_load,initial=[])=>({data:ref(initial)}),notify:()=>{},can:()=>true,allowedApi:()=>Promise.resolve([])};
 const mock=`data:text/javascript;base64,${Buffer.from('export const {state,api,scope,useResource,notify,can,allowedApi}=globalThis.__reportOperational;').toString('base64')}`;
 const source=await readFile(new URL('../src/views/ReportsView.vue',import.meta.url),'utf8'),{descriptor}=parse(source);
 let code=compileScript(descriptor,{id:'operational-report-test'}).content.replace(/from ['"]vue['"]/g,`from '${vueUrl}'`)
  .replace(/import (\w+) from ['"][^'"]+\.vue['"];?/g,'const $1={};')
  .replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`)
  .replace(/from ['"]\.\.\/lib\/context-preferences\.js['"]/g,`from '${new URL('../src/lib/context-preferences.js',import.meta.url).href}'`)
  .replace(/from ['"]\.\.\/lib\/(format|report-state|report-presentation)['"]/g,(_,name)=>`from '${new URL(`../src/lib/${name}.js`,import.meta.url).href}'`);
 const component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;let view;
 const original=component.setup;component.setup=(props,context)=>{view=original(props,context);return ()=>null;};
 const renderer=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null}),app=renderer.createApp(component,{area:'fiscal'});app.mount({});
 try{
  view.kind.value='fiscal-outputs';await nextTick();assert.equal(view.model.value,'reference-outputs-p2a-v1');
  assert.equal(view.start.value,'2026-09-01');assert.equal(view.end.value,'2026-09-30');
  state.contextPreferences.month='02';await nextTick();
  assert.equal(view.start.value,'2026-02-01');assert.equal(view.end.value,'2026-02-28');
  assert.equal(view.model.value,'reference-outputs-p2a-v1','competência sugerida preserva o modelo de referência');
  const rows=Array.from({length:5},(_,i)=>({document_id:i<2?1:i,document:String(100+i),total_cents:10000,book_icms_cents:null,pending:['FISCAL_TREATMENT_REQUIRED'],treatment:{},declared_classifications:[{rate:'7'}]}));
  view.result.value={kind:'fiscal-outputs',row_scope:'analytical_posting_lines',company_id:1,start:'2026-09-01',end:'2026-09-30',filters:{cfop:'6202',direction:'outgoing',status:'booked'},rows,totals:{documents:4,lines:5,total_cents:50000,book_icms_cents:null,book_icms_informed_lines:0,lines_with_pending:5}};
  assert.equal(view.reviewSummary.value.documents,4);assert.equal(view.reviewSummary.value.lines,5);
  assert.equal(view.columns.value.includes('treatment'),false);assert.equal(view.columns.value.includes('declared_classifications'),false);
  assert.match(view.display('pending',rows[0].pending),/Tratamento fiscal/);assert.doesNotMatch(view.display('pending',rows[0].pending),/FISCAL_TREATMENT_REQUIRED/);
  view.showRowDetails(rows[0]);assert.ok(view.rowDetails.value.sections.length);
  view.start.value='2026-10-01';view.end.value='2026-10-31';
  const work=view.openReviewReport();await nextTick();await nextTick();
  assert.equal(pending.length,1);assert.match(pending[0].url,/start=2026-09-01&end=2026-09-30/);assert.match(pending[0].url,/cfop=6202/);assert.match(pending[0].url,/direction=outgoing/);assert.match(pending[0].url,/status=booked/);
  pending[0].resolve({kind:'fiscal-inconsistencies',company_id:1,rows:[],totals:{}});await work;
  assert.equal(view.kind.value,'fiscal-inconsistencies');assert.equal(view.rowDetails.value,null);
  assert.doesNotMatch(source,/Modelo Escritura genérico|JSON\.stringify\(origin\.data\.totals/);
 }finally{app.unmount();delete globalThis.__reportOperational;}
});
