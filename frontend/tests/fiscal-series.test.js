import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createRenderer,reactive,ref} from 'vue';
const require=createRequire(import.meta.url),vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
test('série separa salvar/prever/confirmar, cancela sem gravar e descarta resposta de contexto antigo',async()=>{
 const calls=[],pending=[],questions=[],messages=[];let answer=false;
 const state=reactive({companyId:1,period:'2026-11',module:'fiscal',editor:null});
 globalThis.__seriesTest={state,company:ref({name:'Sintética'}),can:()=>true,api:(url,options)=>{calls.push({url,options});return new Promise((resolve,reject)=>pending.push({resolve,reject}));},scope:(url,cid)=>`/companies/${cid}${url}`,captureContext:()=>({companyId:state.companyId,period:state.period,module:state.module}),ask:async q=>{questions.push(q);return answer;},notify:m=>messages.push(m),changed:()=>{}};
 const mock=`data:text/javascript;base64,${Buffer.from('export const {state,company,can,api,scope,captureContext,ask,notify,changed}=globalThis.__seriesTest;').toString('base64')}`;
 const source=await readFile(new URL('../src/components/FiscalSeriesSettings.vue',import.meta.url),'utf8');
 const {descriptor}=parse(source);const code=compileScript(descriptor,{id:'series-test'}).content.replace(/from ['"]vue['"]/g,`from '${vueUrl}'`).replace(/import (\w+) from ['"][^'"]+\.vue['"];?/g,'const $1={render:()=>null};').replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`);
 const component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;
 let v;const setup=component.setup;component.setup=(props,context)=>{v=setup(props,context);return ()=>null;};
 const app=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null}).createApp(component);app.mount({});
 try{
  let p=v.open();await v.open();assert.equal(calls.length,1);pending.shift().resolve({digits:3,version:0});await p;assert.equal(state.editor.owner,'series-settings');
  v.config.value.digits=4;await v.close();assert.equal(v.show.value,true);assert.equal(questions.length,1);
  p=v.save();await v.save();assert.equal(calls.length,2);assert.deepEqual(calls.at(-1).options.body,{digits:4,version:0});pending.shift().resolve({digits:4,version:1});await p;assert.equal(v.preview.value,null);
  p=v.prepare();pending.shift().resolve({id:'p1',preview_hash:'h1',can_confirm:true,selected_count:1});await p;await v.close();assert.equal(v.show.value,false);assert.equal(calls.filter(c=>c.url.endsWith('/confirm')).length,0);
  p=v.open();pending.shift().resolve({digits:4,version:1});await p;p=v.prepare();pending.shift().resolve({id:'p2',preview_hash:'h2',can_confirm:true,selected_count:1});await p;
  v.config.value.digits=5;assert.equal(v.preview.value,null);await v.confirm();assert.equal(calls.filter(c=>c.url.endsWith('/confirm')).length,0);
  v.config.value.digits=4;p=v.prepare();pending.shift().resolve({id:'p3',preview_hash:'h3',can_confirm:true,selected_count:1});await p;
  v.reason.value='Revisado';p=v.confirm();await v.confirm();assert.equal(calls.filter(c=>c.url.endsWith('/confirm')).length,1);assert.deepEqual(calls.at(-1).options.body,{preview_id:'p3',preview_hash:'h3',reason:'Revisado'});pending.shift().resolve({selected_count:1,preserved_count:2});await p;assert.match(messages.at(-1),/corrigidas: 1/);
  p=v.prepare();state.companyId=2;assert.equal(v.show.value,false);pending.shift().resolve({id:'old',can_confirm:true});await p;assert.equal(v.preview.value,null);assert.equal(state.editor,null);
  p=v.open();state.period='2027-01';pending.shift().resolve({digits:3,version:0});await p;assert.equal(v.show.value,false);
  p=v.open();pending.shift().resolve({digits:3,version:0});await p;v.config.value.digits=6;answer=true;await v.close();assert.equal(v.show.value,false);
 }finally{app.unmount();delete globalThis.__seriesTest;}
});
