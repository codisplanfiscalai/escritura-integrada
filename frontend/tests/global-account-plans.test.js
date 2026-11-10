import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

async function mountPlan(file,globalKey,initial={}){
 const {parse,compileScript}=await import('@vue/compiler-sfc');
 const {createRenderer,reactive,ref}=await import('vue');
 const {createRequire}=await import('node:module');
 const {pathToFileURL}=await import('node:url');
 const require=createRequire(import.meta.url),vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
 const state=reactive({companyId:1,period:'2026-11',module:'accounting',refresh:0,session:{user:{role:'admin'}}}),pending=[];
 globalThis[globalKey]={state,company:ref({name:'Empresa fictícia'}),api:(url,options)=>new Promise((resolve,reject)=>pending.push({url,options,resolve,reject})),scope:(url,cid=state.companyId)=>`/companies/${cid}${url}`,rows:x=>x,notify:()=>{},changed:()=>{},can:()=>true};
 const mock=`data:text/javascript;base64,${Buffer.from(`export const {state,company,api,scope,rows,notify,changed,can}=globalThis.${globalKey};`).toString('base64')}`;
 const {descriptor}=parse(await readFile(new URL('../src/components/'+file,import.meta.url),'utf8'));
 let code=compileScript(descriptor,{id:globalKey}).content.replace(/from ['"]vue['"]/g,`from '${vueUrl}'`).replace(/import (\w+) from ['"][^'"]+\.vue['"];?/g,'const $1={};').replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`).replace(/from ['"]\.\.\/lib\/files['"]/g,`from '${new URL('../src/lib/files.js',import.meta.url).href}'`);
 const component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;
 let view;const setup=component.setup;component.setup=(props,context)=>{view=setup(props,context);return()=>null;};
 const app=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null}).createApp(component);app.mount({});
 Object.assign(view,initial);return {view,state,pending,app};
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
  pending[0].resolve({plans:[{id:9,name:'Plano fictício'}],binding:null});await nextTick();await nextTick();
  view.selected.value=9;await nextTick();const old=view.prepare();assert.equal(pending[1].options.body.mode,'shared');
  state.companyId=2;await nextTick();pending[1].resolve({id:10,preview_hash:'old',can_confirm:true});await old;assert.equal(view.preview.value,null);
  pending[2].resolve({plans:[{id:9}],binding:null});await nextTick();await nextTick();
  view.selected.value=9;await nextTick();const fresh=view.prepare();pending[3].resolve({id:11,preview_hash:'fresh',can_confirm:true,plan:{id:9},conflicts:[]});await fresh;
  view.reviewed.value=true;view.mode.value='own';await nextTick();assert.equal(view.preview.value,null);assert.equal(view.reviewed.value,false);
  view.cancel();assert.equal(view.selected.value,'');assert.equal(view.detail.value,null);
 }finally{app.unmount();delete globalThis.__globalAccountPlan;}
});
