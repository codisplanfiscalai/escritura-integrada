import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const flush=async()=>{const {nextTick}=await import('vue');await nextTick();await new Promise(resolve=>setTimeout(resolve,5));await nextTick();};

async function mountPlan(file,globalKey,initial={},options={}){
 const {parse,compileScript}=await import('@vue/compiler-sfc');
 const {createRenderer,reactive,ref,h,KeepAlive}=await import('vue');
 const {createRequire}=await import('node:module');
 const {pathToFileURL}=await import('node:url');
 const require=createRequire(import.meta.url),vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
 const state=reactive({companyId:1,period:'2026-11',module:'accounting',refresh:0,contextBusy:Boolean(options.contextBusy),session:{user:{role:'admin'}}}),pending=[];
 globalThis[globalKey]={state,company:ref({name:'Empresa fictícia'}),api:(url,options)=>new Promise((resolve,reject)=>pending.push({url,options,resolve,reject})),scope:(url,cid=state.companyId)=>`/companies/${cid}${url}`,rows:x=>x,notify:()=>{},changed:()=>state.refresh++,can:()=>true};
 const mock=`data:text/javascript;base64,${Buffer.from(`export const {state,company,api,scope,rows,notify,changed,can}=globalThis.${globalKey};`).toString('base64')}`;
 const {descriptor}=parse(await readFile(new URL('../src/components/'+file,import.meta.url),'utf8'));
 let code=compileScript(descriptor,{id:globalKey}).content.replace(/from ['"]vue['"]/g,`from '${vueUrl}'`).replace(/import (\w+) from ['"][^'"]+\.vue['"];?/g,'const $1={};').replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`).replace(/from ['"]\.\.\/lib\/files['"]/g,`from '${new URL('../src/lib/files.js',import.meta.url).href}'`);
 const component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;
 let view;const setup=component.setup;component.setup=(props,context)=>{view=setup(props,context);return()=>null;};
 const shown=ref(true),root=options.keepAlive?{setup:()=>()=>h(KeepAlive,null,{default:()=>shown.value?h(component):null})}:component;
 const app=createRenderer({createElement:()=>({}),createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null}).createApp(root);app.mount({});
 Object.assign(view,initial);return {view,state,pending,app,shown};
}

test('publicar global exige consentimento próprio mesmo quando a ativação local seria permitida',async()=>{
 const {view,state,app}=await mountPlan('AccountPlanPanel.vue','__accountPlanPublication');
 try{
  view.preview.value={id:7,preview_hash:'fixture',can_confirm:true,conflict_count:0};view.reason.value='Publicação sintética';view.reviewed.value=true;view.globalName.value='Plano fictício';
  view.activationMode.value='global';view.reviewed.value=true;
  assert.equal(view.canConfirm.value,false,'permissão local não deve substituir autorização de visibilidade global');
  view.globalReviewed.value=true;assert.equal(view.canConfirm.value,true);
  state.session.user.role='operator';assert.equal(view.canConfirm.value,false);
  state.session.user.role='admin';view.invalidate();assert.equal(view.globalReviewed.value,false);assert.equal(view.canConfirm.value,false);
 }finally{app.unmount();delete globalThis.__accountPlanPublication;}
});

test('uso de plano global invalida prévia ao trocar contexto/modo e ignora resposta anterior',async()=>{
 const {nextTick}=await import('vue');
 const {view,state,pending,app}=await mountPlan('GlobalAccountPlanPanel.vue','__globalAccountPlan');
 try{
  await flush();pending[0].resolve({plans:[{id:9,name:'Plano fictício'}],binding:null});await nextTick();await nextTick();
  view.selected.value=9;await nextTick();const old=view.prepare();assert.equal(pending[1].options.body.mode,'shared');
  state.companyId=2;await flush();pending[1].resolve({id:10,preview_hash:'old',can_confirm:true});await old;assert.equal(view.preview.value,null);
  pending[2].resolve({plans:[{id:9}],binding:null});await nextTick();await nextTick();
  view.selected.value=9;await nextTick();const fresh=view.prepare();pending[3].resolve({id:11,preview_hash:'fresh',can_confirm:true,plan:{id:9},conflicts:[]});await fresh;
  view.reviewed.value=true;view.mode.value='own';await nextTick();assert.equal(view.preview.value,null);assert.equal(view.reviewed.value,false);
  view.cancel();assert.equal(view.selected.value,'');assert.equal(view.detail.value,null);
 }finally{app.unmount();delete globalThis.__globalAccountPlan;}
});


test('biblioteca coalesce montagem, ativação e mudanças de contexto; não consulta durante contextBusy',async()=>{
 const {view,state,pending,app}=await mountPlan('GlobalAccountPlanPanel.vue','__globalCoalesced',{}, {keepAlive:true,contextBusy:true});
 try{
  await flush();assert.equal(pending.length,0);
  state.companyId=2;state.period='2027-01';state.module='fiscal';state.refresh++;await flush();assert.equal(pending.length,0);
  state.contextBusy=false;state.refresh++;state.refresh++;await flush();
  assert.equal(pending.length,1);assert.equal(pending[0].url,'/companies/2/global-account-plans');
  pending[0].resolve({plans:[{id:1}],binding:null});await flush();assert.equal(view.busy.value,false);
  state.refresh++;state.refresh++;await flush();assert.equal(pending.length,2);
  state.refresh++;await flush();assert.equal(pending.length,2,'refresh during a read waits for it to finish');
  pending[1].resolve({plans:[{id:2}],binding:null});await flush();assert.equal(pending.length,3);
  pending[2].resolve({plans:[{id:3}],binding:null});await flush();assert.equal(pending.length,3);assert.equal(view.plans.value[0].id,3);
 }finally{app.unmount();delete globalThis.__globalCoalesced;}
});

test('biblioteca não lê oculta, cancela timer e rejeita resposta anterior ao retornar do KeepAlive',async()=>{
 const {nextTick}=await import('vue');
 const {view,state,pending,app,shown}=await mountPlan('GlobalAccountPlanPanel.vue','__globalKeepAlive',{}, {keepAlive:true});
 try{
  shown.value=false;await flush();assert.equal(pending.length,0,'deactivation cancels initial deferred load');
  state.refresh++;state.companyId=2;await flush();await view.load();await view.prepare();await view.inspect();assert.equal(pending.length,0);
  shown.value=true;await flush();assert.equal(pending.length,1);
  shown.value=false;await nextTick();pending[0].resolve({plans:[{id:99}],binding:{version:99}});await flush();
  assert.deepEqual(view.plans.value,[]);assert.equal(view.binding.value,null);assert.equal(view.busy.value,false);
  state.refresh++;state.period='2027-01';await flush();assert.equal(pending.length,1);
  shown.value=true;await flush();assert.equal(pending.length,2);
  pending[1].resolve({plans:[{id:3}],binding:null});await flush();assert.equal(view.plans.value[0].id,3);
  state.refresh++;await nextTick();app.unmount();await flush();assert.equal(pending.length,2,'unmount also cancels scheduled work');
 }finally{app.unmount();delete globalThis.__globalKeepAlive;}
});

test('confirmação global recarrega biblioteca uma vez e bloqueia ações durante transição',async()=>{
 const {view,state,pending,app}=await mountPlan('GlobalAccountPlanPanel.vue','__globalConfirm');
 try{
  await flush();pending[0].resolve({plans:[{id:9}],binding:null});await flush();
  view.selected.value=9;view.preview.value={id:20,can_confirm:true,preview_hash:'synthetic'};view.reviewed.value=true;view.reason.value='Teste sintético';
  const confirming=view.confirm();assert.equal(pending[1].url,'/companies/1/global-account-plans/previews/20/confirm');
  await view.confirm();assert.equal(pending.length,2);
  pending[1].resolve({mode:'shared',available:100});await confirming;await flush();assert.equal(pending.length,3);
  pending[2].resolve({plans:[{id:9}],binding:{version:1}});await flush();assert.match(view.result.value,/100 contas/);assert.equal(pending.length,3);
  state.contextBusy=true;await view.inspect();await view.prepare();await view.confirm();await view.detach();await view.load();await flush();assert.equal(pending.length,3);
 }finally{app.unmount();delete globalThis.__globalConfirm;}
});
