import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createRenderer,nextTick,reactive} from 'vue';
const require=createRequire(import.meta.url),vue=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
const url=code=>`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`;
const flush=async()=>{await nextTick();await new Promise(r=>setTimeout(r,5));await nextTick();};let counter=0;
async function harness(){
 const key=`__accountingSettings${++counter}`,requests=[],props=reactive({companyId:2});
 globalThis[key]={api:(path,options)=>new Promise((resolve,reject)=>requests.push({path,options,resolve,reject})),changed:()=>{},notify:()=>{},ask:async()=>true};
 const mock=url(`export const {api,changed,notify,ask}=globalThis.${key};`);
 const source=await readFile(new URL('../src/components/CompanyAccountingSettings.vue',import.meta.url),'utf8');
 const code=compileScript(parse(source).descriptor,{id:key}).content.replace(/from ['"]vue['"]/g,`from '${vue}'`).replace("from '../lib/workspace'",`from '${mock}'`).replace("from '../lib/format'",`from '${new URL('../src/lib/format.js',import.meta.url).href}'`);
 const component=(await import(url(code))).default;let view;const setup=component.setup;component.setup=(p,c)=>{view=setup(p,c);return()=>null;};
 const app=createRenderer({createElement:()=>({}),createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null}).createApp(component,props);app.mount({});await flush();
 return {view,requests,props,close:()=>{app.unmount();delete globalThis[key];}};
}
const payload=()=>({version:0,settings:{default_history:'B',default_cost_center_id:null},plans:[{id:7,name:'050',record_count:3}],binding:null,cost_centers:[],capabilities:{edit:true,adopt:true}});
test('parâmetros usam empresa editada e não contexto ativo; salvam defaults reais',async()=>{
 const h=await harness();try{assert.equal(h.requests[0].path,'/companies/2/accounting-settings');h.requests[0].resolve(payload());await flush();h.view.settings.value.default_history='Novo';await flush();assert.equal(h.view.dirty.value,true);const saving=h.view.save();assert.equal(h.requests[1].path,'/companies/2/accounting-settings');assert.equal(h.requests[1].options.body.settings.default_history,'Novo');h.requests[1].resolve({...payload(),version:1,settings:{default_history:'Novo',default_cost_center_id:null}});await saving;assert.equal(h.view.dirty.value,false);}finally{h.close();}
});
test('rascunho não salvo impede aplicar ou duplicar plano sem perder dados',async()=>{
 const h=await harness();try{h.requests[0].resolve({...payload(),binding:{version:1,mode:'shared'}});await flush();h.view.settings.value.default_history='Não salvo';h.view.selected.value=7;await flush();await h.view.prepare();await h.view.detach();assert.equal(h.requests.length,1);assert.equal(h.view.settings.value.default_history,'Não salvo');}finally{h.close();}
});
test('resposta depois do unmount não é aplicada',async()=>{
 const h=await harness();h.close();h.requests[0].resolve(payload());await flush();assert.equal(h.view.data.value,null);
});
