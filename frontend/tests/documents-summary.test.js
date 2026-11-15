import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createRenderer,reactive,ref,nextTick,h,KeepAlive} from 'vue';

const require=createRequire(import.meta.url);
const vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
const dataUrl=code=>`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`;
const libUrl=name=>new URL(`../src/lib/${name.replace(/\.js$/,'')}.js`,import.meta.url).href;
const flush=async()=>{await nextTick();await new Promise(resolve=>setTimeout(resolve,5));await nextTick();};
let serial=0;

async function harness(file,props={},options={}){
 const key=`__documentSummary${++serial}`,requests=[];
 const state=reactive({companyId:1,period:'2026-11',module:'fiscal',refresh:0,contextBusy:false,editor:null,contextPreferences:{month:''}});
 const company=ref({id:1,code:'SYN',name:'Empresa sintética'});
 const api=(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}));
 const can=routine=>!options.denied?.includes(routine);
 globalThis[key]={state,company,api,can,scope:(url,id=state.companyId)=>`/companies/${id}${url}`,rows:value=>Array.isArray(value)?value:value?.items||[],changed:()=>state.refresh++,notify:()=>{},ask:async()=>true,writable:()=>true};
 // Use the real composable, rather than a fake that would hide its lifecycle/race behavior.
 const workspace=await readFile(new URL('../src/lib/workspace.js',import.meta.url),'utf8');
 const resource=workspace.slice(workspace.indexOf('export function useResource('),workspace.indexOf("if (typeof window !== 'undefined')"));
 const mock=dataUrl(`import {ref,watch,onActivated,onDeactivated,onUnmounted} from '${vueUrl}';\nexport const {state,company,api,can,scope,rows,changed,notify,ask,writable}=globalThis.${key};\nexport const navigate=()=>{};export const allowedApi=(routine,path,empty=[])=>can(routine)?api(path):Promise.resolve(empty);\n${resource}`);
 let source=await readFile(new URL(`../src/views/${file}.vue`,import.meta.url),'utf8');
 const {descriptor}=parse(source);
 const code=compileScript(descriptor,{id:key,inlineTemplate:false}).content
  .replace(/from ['"]vue['"]/g,`from '${vueUrl}'`)
  .replace(/import (\w+) from ['"][^'"]+\.vue['"];?/g,'const $1={render:()=>null};')
  .replace(/from ['"]\.\.\/lib\/([^'"]+)['"]/g,(_,name)=>`from '${name==='workspace'?mock:libUrl(name)}'`);
 const component=(await import(dataUrl(code))).default;
 let view;const setup=component.setup;component.setup=(props,context)=>{view=setup(props,context);return()=>null;};
 const shown=ref(true),root=options.keepAlive?{setup:()=>()=>h(KeepAlive,null,{default:()=>shown.value?h(component,props):null})}:component;
 const app=createRenderer({createElement:()=>({}),createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null}).createApp(root,options.keepAlive?{}:props);
 app.mount({});await flush();
 let closed=false;
 return {view,state,requests,shown,close:()=>{if(!closed){closed=true;app.unmount();delete globalThis[key];}}};
}

const docs=[
 {id:1,period:'2026-08',number:'AGO',partner_name:'Fornecedor',direction:'incoming',status:'pending',total_cents:1000},
 {id:2,period:'2026-09',number:'SET-A',partner_name:'Cliente Á',direction:'outgoing',status:'booked',total_cents:2000,import_posting:{review_pending:true}},
 {id:3,period:'2026-09',number:'SET-B',partner_name:'Fornecedor',direction:'incoming',status:'reviewed',total_cents:3000},
 {id:4,period:'2026-09',number:'SET-C',partner_name:'Cliente',direction:'outgoing',status:'booked',document_state:'cancelled',total_cents:0},
];
const zero={documents:0,review:0,booked:0,totalCents:0};
function settle(requests,documents){for(const r of requests)r.resolve(r.url.includes('/documents?')?documents:[]);}
function summary(v,expected){assert.deepEqual(v.documentSummary.value,expected);assert.equal(v.documentSummary.value.documents,v.filtered.value.length);}
test('cartões fiscais acompanham competências, filtros combinados e consulta vazia',async()=>{
 const h=await harness('DocumentsView'),v=h.view;
 try{
  h.state.contextPreferences.month='09';await flush();settle(h.requests,docs);await flush();
  summary(v,{documents:3,review:1,booked:2,totalCents:5000});
  v.monthFilter.value='08';await flush();summary(v,{documents:1,review:1,booked:0,totalCents:1000});assert.match(v.exportUrl.value,/month=08/);
  v.monthFilter.value='10';await flush();summary(v,zero);assert.equal(v.visible.value.length,0);
  v.monthFilter.value='09';v.direction.value='outgoing';await flush();summary(v,{documents:2,review:1,booked:2,totalCents:2000});
  v.query.value='cliente a';await flush();summary(v,{documents:1,review:1,booked:1,totalCents:2000});
  v.query.value='';v.status.value='cancelled';await flush();summary(v,{documents:1,review:0,booked:1,totalCents:0});
  v.status.value='pending';await flush();summary(v,zero);
  v.status.value='';v.direction.value='';v.monthFilter.value='';await flush();summary(v,{documents:4,review:2,booked:2,totalCents:6000});
  assert.equal(h.requests.length,7,'local filters do not refetch annual data');
 }finally{h.close();}
});
test('cartões incluem outras páginas e navegação preserva o mês selecionado',async()=>{
 const h=await harness('DocumentsView',{}, {keepAlive:true}),v=h.view;
 try{
  v.monthFilter.value='09';const many=Array.from({length:60},(_,id)=>({...docs[1],id:id+1}));settle(h.requests,many);await flush();
  summary(v,{documents:60,review:60,booked:60,totalCents:120000});assert.equal(v.visible.value.length,50);
  v.page.value=2;await flush();assert.equal(v.visible.value.length,10);summary(v,{documents:60,review:60,booked:60,totalCents:120000});
  h.shown.value=false;await flush();h.shown.value=true;await flush();settle(h.requests,many);await flush();assert.equal(v.monthFilter.value,'09');summary(v,{documents:60,review:60,booked:60,totalCents:120000});
 }finally{h.close();}
});
test('troca de empresa e exercício limpa cartões e ignora respostas antigas',async()=>{
 const h=await harness('DocumentsView'),v=h.view;
 try{
  h.state.contextPreferences.month='09';await flush();const old=h.requests.slice();
  h.state.companyId=2;await flush();summary(v,zero);const next=h.requests.slice(old.length);assert.ok(next.every(r=>r.url.startsWith('/companies/2/')));
  settle(next,[{...docs[1],id:22,total_cents:7000}]);await flush();summary(v,{documents:1,review:1,booked:1,totalCents:7000});
  settle(old,docs);await flush();summary(v,{documents:1,review:1,booked:1,totalCents:7000});
  h.state.refresh++;await flush();const stale=h.requests.slice(old.length+next.length);
  h.state.period='2027-09';await flush();summary(v,zero);const current=h.requests.slice(old.length+next.length+stale.length);
  settle(current,[]);await flush();settle(stale,docs);await flush();summary(v,zero);assert.match(current[0].url,/year=2027/);
 }finally{h.close();}
});
test('template usa os quatro totalizadores da consulta filtrada',async()=>{
 const source=await readFile(new URL('../src/views/DocumentsView.vue',import.meta.url),'utf8');
 const cards=source.split('<div class="summary-strip">')[1].split('<div v-if="loadError"')[0];
 for(const field of ['documents','review','booked','totalCents'])assert.ok(cards.includes(`documentSummary.${field}`));
 assert.ok(!cards.includes('data.documents'));
});
test('mudanças rápidas de filtros durante resposta pendente usam a última seleção sem novas consultas',async()=>{
 const h=await harness('DocumentsView'),v=h.view;
 try{
  v.monthFilter.value='08';v.monthFilter.value='09';v.direction.value='incoming';v.direction.value='outgoing';v.status.value='pending';v.status.value='booked';v.query.value='SET-B';v.query.value='SET-A';
  await flush();summary(v,zero);
  settle(h.requests,docs);await flush();summary(v,{documents:1,review:1,booked:1,totalCents:2000});
  const params=new URL(v.exportUrl.value,'https://fixture.invalid').searchParams;
  assert.equal(params.get('month'),'09');assert.equal(params.get('direction'),'outgoing');assert.equal(params.get('status'),'booked');assert.equal(params.get('query'),'SET-A');
  assert.equal(h.requests.length,7,'rapid filters remain local');
  v.monthFilter.value='08';v.query.value='';v.direction.value='';v.status.value='';v.monthFilter.value='10';await flush();summary(v,zero);assert.equal(v.visible.value.length,0);
 }finally{h.close();}
});
