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


function settle(requests,period='2026-09',companyId=1){for(const r of requests)r.resolve(r.url.includes('/dashboard?')?{company_id:companyId,period,documents:{count:9,pending:2},accounting:{journals:3,debit_cents:12345},financial:{payable_cents:5000},periods:{fiscal:{closed:true},accounting:{closed:false}}}:r.url.includes('/journals?')?[{id:9,date:period+'-01'}]:[]);}
test('indicadores fiscais e contábeis usam competência sugerida sem alterar período operacional',async()=>{
 const h=await harness('DashboardView'),v=h.view;
 try{
  const previous=h.requests.slice();h.state.contextPreferences.month='09';await flush();
  const current=h.requests.slice(previous.length);assert.ok(current.some(r=>r.url==='/companies/1/dashboard?period=2026-09'));assert.ok(current.some(r=>r.url==='/companies/1/journals?period=2026-09'));
  settle(current);await flush();assert.equal(v.competence.value,'2026-09');assert.equal(v.cards.value[0].value,9);assert.match(v.cards.value[1].value,/123,45/);assert.equal(v.data.value.recent[0].id,9);assert.equal(h.state.period,'2026-11');
  settle(previous,'2026-11');await flush();assert.equal(v.data.value.period,'2026-09');
  const count=h.requests.length;h.state.contextPreferences.month='';await flush();assert.equal(v.data.value,null);assert.equal(v.competence.value,'2026-11');assert.ok(h.requests.slice(count).some(r=>r.url.includes('/dashboard?period=2026-11')));
  assert.match(v.cards.value[2].sub,/todos os períodos/);assert.match(v.cards.value[3].sub,/todos os períodos/);
 }finally{h.close();}
});
test('mudanças rápidas de mês, empresa e exercício não deixam resposta antiga substituir indicadores',async()=>{
 const h=await harness('DashboardView'),v=h.view;
 try{
  const initial=h.requests.slice();h.state.contextPreferences.month='08';await flush();const august=h.requests.slice(initial.length);
  h.state.contextPreferences.month='09';await flush();const september=h.requests.slice(initial.length+august.length);
  settle(september);await flush();settle(august,'2026-08');settle(initial,'2026-11');await flush();assert.equal(v.data.value.period,'2026-09');
  let count=h.requests.length;h.state.companyId=2;await flush();assert.equal(v.data.value,null);const company=h.requests.slice(count);assert.ok(company.every(r=>r.url.startsWith('/companies/2/')));settle(company,'2026-09',2);await flush();assert.equal(v.data.value.company_id,2);
  count=h.requests.length;h.state.period='2027-11';await flush();assert.equal(v.data.value,null);const year=h.requests.slice(count);assert.ok(year.some(r=>r.url==='/companies/2/dashboard?period=2027-09'));settle(year,'2027-09',2);await flush();assert.equal(v.data.value.period,'2027-09');
 }finally{h.close();}
});
test('navegação mantém competência dos indicadores e não consulta enquanto tela está oculta',async()=>{
 const h=await harness('DashboardView',{}, {keepAlive:true}),v=h.view;
 try{
  settle(h.requests,'2026-11');await flush();h.shown.value=false;await flush();const count=h.requests.length;h.state.contextPreferences.month='09';await flush();assert.equal(h.requests.length,count);
  h.shown.value=true;await flush();const latest=h.requests.slice(count);assert.ok(latest.some(r=>r.url.includes('/dashboard?period=2026-09')));settle(latest);await flush();assert.equal(v.data.value.period,'2026-09');
 }finally{h.close();}
});
