import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createRenderer,reactive,ref,nextTick} from 'vue';

test('catálogo global permite uso direto, bloqueia envio duplo e invalida contexto antigo',async()=>{
 const state=reactive({companyId:1,period:'2026-11',module:'fiscal',companies:[{id:1,name:'A'},{id:2,name:'B'}],session:{user:{role:'admin'}},editor:null});
 const requests=[];
 globalThis.__registryTest={state,api:(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject})),scope:(url,cid=state.companyId)=>`/companies/${cid}${url}`,useResource:()=>({data:ref([]),error:ref('')}),notify:()=>{},changed:()=>{},ask:async()=>true,can:()=>true,captureContext:()=>({companyId:state.companyId,year:'2026',module:state.module}),contextMatches:c=>c.companyId===state.companyId};
 const mock=`data:text/javascript;base64,${Buffer.from('export const {state,api,scope,useResource,notify,changed,ask,can,captureContext,contextMatches}=globalThis.__registryTest;').toString('base64')}`;
 const require=createRequire(import.meta.url),vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
 const source=await readFile(new URL('../src/views/SharedRegistrationsView.vue',import.meta.url),'utf8');
 const code=compileScript(parse(source).descriptor,{id:'registry-test'}).content.replace(/from ['"]vue['"]/g,`from '${vueUrl}'`).replace(/import (\w+) from ['"][^'"]+\.vue['"];?/g,'const $1={};').replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`).replace(/import \{normalized\} from ['"][^'"]+['"];?/g,"const normalized=s=>String(s).toLowerCase();");
 const component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;
 let view;const setup=component.setup;component.setup=(p,c)=>{view=setup(p,c);return ()=>null;};
 const renderer=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null});
 const app=renderer.createApp(component,{kind:'accountant'});app.mount({});
 try{
  view.edit();assert.equal(state.editor.companyId,1);view.form.value.name='Synthetic';
  const first=view.save();view.save();assert.equal(requests.length,1);assert.equal(requests[0].url,'/companies/1/registrations/accountant');
  await view.close();assert.ok(view.form.value,'cannot close an in-flight write');
  requests[0].resolve({id:1});await first;assert.equal(view.form.value,null);
  const globalRow={id:1,version:3,links:[]};assert.equal(view.usedHere(globalRow),false);
  const using=view.useHere(globalRow);view.useHere(globalRow);assert.equal(requests.length,2);
  assert.equal(requests[1].url,'/companies/1/registrations/accountant/1/use');assert.deepEqual(requests[1].options.body,{version:3});
  state.companyId=2;await nextTick();assert.equal(view.form.value,null);assert.equal(state.editor,null);
  requests[1].resolve({id:1});await using;assert.equal(view.form.value,null);

 }finally{app.unmount();delete globalThis.__registryTest;}
});

test('Empresas, Terceiros e Contadores estão em Cadastros; produtos continuam no Fiscal',async()=>{
 const app=await readFile(new URL('../src/App.vue',import.meta.url),'utf8');
 assert.match(app,/id:'companies'.*component:CompaniesView,module:'registrations'/);
 assert.equal((app.match(/id:'companies'/g)||[]).length,1);
 assert.match(app,/id:'third-parties'.*module:'registrations'/);
 assert.match(app,/id:'accountants'.*module:'registrations'/);
 assert.match(app,/id:'masters',label:'Produtos e serviços'.*module:'fiscal'/);
 assert.match(app,/registrations:'Cadastros'/);
 assert.match(app,/id:'third-parties'.*routine:'fiscal.shared_parties'/);
 const view=await readFile(new URL('../src/views/SharedRegistrationsView.vue',import.meta.url),'utf8');
 assert.match(view,/sem vínculo prévio para consulta/);
 assert.doesNotMatch(view,/Vincular empresa|Código na empresa ativa/);
 assert.match(view,/Usar nesta empresa/);
});
