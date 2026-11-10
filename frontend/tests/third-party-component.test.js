import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

// Actual setup logic mounted with Vue, without a browser or third-party test dependency.
test('painel de terceiros bloqueia duplo envio, cancela prévia e rejeita contexto antigo',async()=>{
 const {parse,compileScript}=await import('@vue/compiler-sfc');
 const {createRenderer,reactive,ref,nextTick}=await import('vue');
 const {createRequire}=await import('node:module');
 const {pathToFileURL}=await import('node:url');
 const require=createRequire(import.meta.url),vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
 const state=reactive({companyId:1,period:'2026-11',module:'fiscal',companies:[{id:1,name:'Destino'},{id:2,name:'Origem'}],editor:null}),pending=[],closed=[];
 let discard=false;
 globalThis.__thirdPartyTest={state,company:ref({name:'Destino'}),api:(url,options)=>new Promise((resolve,reject)=>pending.push({url,options,resolve,reject})),scope:(url,cid=state.companyId)=>`/companies/${cid}${url}`,rows:x=>x,notify:()=>{},changed:()=>{},ask:async()=>discard,can:()=>true};
 const mock=`data:text/javascript;base64,${Buffer.from('export const {state,company,api,scope,rows,notify,changed,ask,can}=globalThis.__thirdPartyTest;').toString('base64')}`;
 const source=await readFile(new URL('../src/components/ThirdPartyPanel.vue',import.meta.url),'utf8');
 const {descriptor}=parse(source);
 const code=compileScript(descriptor,{id:'third-party-component-test'}).content
  .replace(/from ['"]vue['"]/g,`from '${vueUrl}'`)
  .replace(/import (\w+) from ['"][^'"]+\.vue['"];?/g,'const $1={};')
  .replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`)
  .replace(/from ['"]\.\.\/lib\/third-party-state['"]/g,`from '${new URL('../src/lib/third-party-state.js',import.meta.url).href}'`);
 const component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;
 let view;const original=component.setup;component.setup=(props,context)=>{view=original(props,context);return ()=>null;};
 const renderer=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null});
 const master={id:7,code:'LOCAL',kind:'participant',name:'Destino privado',version:1,tax_id:'SYNTH0010001XX',active:true,identity:{entity_type:'organization',identity_key:'SYNTH001'},data:{address:'Anterior',roles:['supplier'],email:'private-destination@example.invalid',profile:{state_registrations:[]}}};
 const app=renderer.createApp(component,{master,onClose:()=>closed.push(true)});app.mount({});
 const settle=async()=>{await nextTick();await new Promise(resolve=>setImmediate(resolve));await nextTick();};
 try{
  assert.equal(pending.length,2);pending[0].resolve(master);pending[1].resolve([]);await settle();
  assert.equal(view.detail.value.id,7);assert.equal(view.loading.value,false);assert.equal(state.editor.companyId,1);
  view.registrations.value.push({state:'SP',number:'SYNTHETIC',status:'',active:null});
  await view.close();assert.equal(closed.length,0,'unsaved changes require discard confirmation');
  assert.equal(view.registrationsDirty.value,true);await view.createPreview();assert.equal(pending.length,2);
  view.discardRegistrations();assert.equal(view.registrationsDirty.value,false);
  view.sourceCompany.value=2;await settle();assert.equal(pending.length,3);assert.equal(pending[2].url,'/companies/2/third-parties');
  pending[2].resolve([{...master,id:9,name:'Origem revisada'}]);await settle();
  view.sourceMaster.value=9;view.fields.value=['address'];await settle();
  const preview={source_company_id:2,source_master_id:9,source_version:1,master_id:7,version:1,fields:['address'],values:{address:'Revisado'},preview_hash:'synthetic'};
  const first=view.createPreview();assert.equal(pending.length,4);await view.createPreview();assert.equal(pending.length,4,'duplicate preview ignored');
  pending[3].resolve(preview);await first;assert.equal(view.preview.value.preview_hash,'synthetic');
  view.invalidatePreview();assert.equal(view.preview.value,null);assert.equal(pending.length,4,'cancel does not mutate');
  const second=view.createPreview();pending[4].resolve(preview);await second;
  view.reuseReason.value='Revisão cadastral sintética';view.confirmReuse();view.confirmReuse();
  assert.equal(pending.length,6,'double confirmation sends one request');assert.equal(pending[5].url,'/companies/1/third-parties/7/reuse-confirm');
  assert.equal(pending[5].options.context.companyId,1);assert.deepEqual(pending[5].options.body.fields,['address']);
  await view.close();assert.equal(closed.length,0,'closing while a mutation runs is blocked');
  pending[5].resolve({...master,version:2,data:{...master.data,address:'Revisado'}});await settle();
  assert.equal(pending.length,7);pending[6].resolve([]);await settle();assert.equal(view.busy.value,false);
  assert.equal(view.detail.value.data.email,'private-destination@example.invalid');assert.equal(view.preview.value,null);
  const late=view.createPreview();assert.equal(pending.length,8);state.companyId=2;await settle();
  assert.equal(closed.length,1);assert.equal(state.editor,null);pending[7].resolve({...preview,values:{address:'STALE'}});await late;
  assert.equal(view.preview.value,null);assert.equal(view.detail.value.data.address,'Revisado','late response never writes new context');
 }finally{app.unmount();delete globalThis.__thirdPartyTest;}
});
