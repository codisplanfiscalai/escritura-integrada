import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createRenderer,reactive,computed,ref,nextTick,h,KeepAlive} from 'vue';
const require=createRequire(import.meta.url),vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
const dataUrl=code=>`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`;
const flush=async()=>{await nextTick();await new Promise(resolve=>setTimeout(resolve,5));await nextTick();};
const source=await readFile(new URL('../src/views/FinanceView.vue',import.meta.url),'utf8');
let serial=0;
const renderer=createRenderer({createElement:()=>({}),createText:()=>({}),createComment:()=>({}),setText:()=>{},setElementText:()=>{},patchProp:()=>{},insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null});
async function workspace(){
 const code=(await readFile(new URL('../src/lib/workspace.js',import.meta.url),'utf8'))
  .replace(/from 'vue'/g,`from '${vueUrl}'`)
  .replace("from './format'",`from '${new URL('../src/lib/format.js',import.meta.url).href}'`)
  .replace("from './context-preferences.js'",`from '${new URL('../src/lib/context-preferences.js',import.meta.url).href}'`);
 return import(dataUrl(code+`\n// instance ${++serial}`));
}
async function harness(){
 const real=await workspace(),state=real.state;Object.assign(state,{companyId:1,period:'2026-09',module:'financial',contextBusy:false,session:{user:{role:'admin'}}});
 const requests=[],key=`__financePerformance${++serial}`;
 const api=(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}));
 const allowedApi=(routine,url)=>api(url);
 globalThis[key]={...real,api,allowedApi,company:ref({name:'Empresa sintética'}),ask:async()=>true,notify:()=>{},changed:()=>{state.refresh++;}};
 const mock=dataUrl(`export const {state,company,api,scope,useResource,notify,ask,changed,can,allowedApi,writable}=globalThis.${key}`);
 const {descriptor}=parse(source);
 const code=compileScript(descriptor,{id:key}).content
  .replace(/from ['"]vue['"]/g,`from '${vueUrl}'`)
  .replace(/import (\w+) from ['"][^'"]+\.vue['"];?/g,'const $1={render:()=>null};')
  .replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`)
  .replace(/from ['"]\.\.\/lib\/format['"]/g,`from '${new URL('../src/lib/format.js',import.meta.url).href}'`);
 const component=(await import(dataUrl(code))).default;let view;
 const setup=component.setup;component.setup=(props,context)=>{view=setup(props,context);return()=>null;};
 const app=renderer.createApp(component);app.mount({});await flush();
 return {view,state,requests,close:()=>{app.unmount();delete globalThis[key];}};
}
const titles=Array.from({length:183},(_,i)=>({id:i+1,kind:'payable',description:`Título sintético ${i}`,partner_name:'Fornecedor sintético',document:String(i),amount_cents:10000,balance_cents:10000,status:'open',settlements:[]}));
test('financeiro carrega só títulos e pagina 183 sem mudar saldo ou seleção',async()=>{
 const x=await harness(),v=x.view;
 try{
  assert.deepEqual(x.requests.map(r=>r.url),['/companies/1/titles']);assert.equal(v.loading.value,true);
  x.requests[0].resolve(titles);await flush();assert.equal(v.loading.value,false);assert.equal(v.visible.value.length,50);assert.equal(v.balance.value,1830000);
  v.selection.value=[1,183];v.page.value=4;assert.equal(v.visible.value.length,33);assert.equal(v.visible.value.at(-1).id,183);assert.equal(v.chosen.value.length,2);
  v.query.value='Título sintético 182';await flush();assert.equal(v.page.value,1);assert.equal(v.filtered.value.length,1);assert.equal(v.visible.value[0].id,183);assert.equal(v.balance.value,1830000);
  assert.equal(x.requests.length,1);
  v.query.value='';v.pageSize.value=5000;await flush();assert.equal(v.visible.value.length,183);
 }finally{x.close();}
});
test('catálogos são sob demanda; falha bloqueia salvar, retry e resposta antiga são seguros',async()=>{
 const x=await harness(),v=x.view;
 try{
  x.requests[0].resolve(titles);await flush();v.open(titles[0],'history');await flush();assert.equal(x.requests.length,1);await v.close();await flush();
  v.open(titles[0]);await flush();assert.equal(x.requests.length,1,'baixa simples não baixa plano inteiro');
  v.form.value.integrate=true;await flush();assert.equal(x.requests.at(-1).url,'/companies/1/accounts');assert.equal(v.auxLoading.value,true);
  await v.close();await flush();x.requests.at(-1).resolve([{id:999}]);await flush();assert.deepEqual(v.auxiliary.value.accounts,[],'closed response discarded');
  v.open();await flush();assert.deepEqual(x.requests.slice(-2).map(r=>r.url),['/companies/1/documents?period=2026-09','/companies/1/masters/participant']);
  const count=x.requests.length;await v.save();assert.equal(x.requests.length,count,'cannot save until options arrive');
  x.requests.at(-2).reject(new Error('Falha sintética'));x.requests.at(-1).resolve([]);await flush();assert.equal(v.auxError.value,'Falha sintética');await v.save();assert.equal(x.requests.length,count);
  const retry=v.loadAuxiliary();x.requests.at(-2).resolve([]);x.requests.at(-1).resolve([{id:2,name:'Pessoa'}]);await retry;assert.equal(v.auxError.value,'');assert.equal(v.auxiliary.value.participants[0].id,2);
  await v.close();await flush();v.open(null,'agreements');await flush();assert.equal(x.requests.at(-1).url,'/companies/1/renegotiations');x.requests.at(-1).resolve([]);await flush();
 }finally{x.close();}
});
test('useResource coalesce mudanças e não recarrega tela desativada durante contexto',async()=>{
 const w=await workspace(),state=w.state;Object.assign(state,{companyId:1,period:'2026-09',module:'fiscal',contextBusy:false});
 const current=ref('a'),reads=[],views={};
 const make=name=>({name,setup(){views[name]=w.useResource(async()=>{reads.push(name);return[name];});return()=>h('div');}});
 const screens={a:make('a'),b:make('b')};const app=renderer.createApp({setup:()=>()=>h(KeepAlive,null,[h(screens[current.value],{key:current.value})])});app.mount({});
 try{
  await flush();assert.deepEqual(reads,['a']);
  state.contextBusy=true;state.module='financial';state.refresh++;current.value='b';await flush();assert.deepEqual(reads,['a']);assert.equal(views.b.loading.value,true);
  state.contextBusy=false;await flush();assert.deepEqual(reads,['a','b']);
  state.refresh++;state.refresh++;await flush();assert.deepEqual(reads,['a','b','b']);
  current.value='a';await flush();assert.deepEqual(reads,['a','b','b','a']);
 }finally{app.unmount();}
});
