import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createRenderer,reactive,ref,nextTick} from 'vue';
const require=createRequire(import.meta.url),vue=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
const url=s=>`data:text/javascript;base64,${Buffer.from(s).toString('base64')}`;
async function mount(file){
 const state=reactive({companyId:1,module:'accounting',period:'2026-11',contextPreferences:{month:'09'}}),requests=[];
 globalThis.__periodView={state,company:ref({prosoft_code:'1'}),api:(path,options)=>new Promise(resolve=>requests.push({path,options,resolve})),scope:(p,cid=state.companyId)=>`/companies/${cid}${p}`,useResource:()=>({data:ref({accounts:[],centers:[]})}),notify:()=>{},can:()=>true,allowedApi:()=>{},writable:()=>true};
 const mock=url('export const {state,company,api,scope,useResource,notify,can,allowedApi,writable}=globalThis.__periodView;');
 const {descriptor}=parse(await readFile(new URL(`../src/views/${file}.vue`,import.meta.url),'utf8'));
 const code=compileScript(descriptor,{id:'period-view'}).content.replace(/from ['"]vue['"]/g,`from '${vue}'`).replace(/from ['"]\.\.\/lib\/([^'"]+)['"]/g,(_,name)=>`from '${name==='workspace'?mock:new URL(`../src/lib/${name.replace(/\.js$/,'')}.js`,import.meta.url).href}'`);
 const component=(await import(url(code))).default;let view;const setup=component.setup;component.setup=(p,c)=>{view=setup(p,c);return()=>null;};
 const app=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null}).createApp(component);app.mount({});
 return {state,view,requests,close:()=>{app.unmount();delete globalThis.__periodView;}};
}
test('Prosoft uses editable suggested month, discards stale responses and preserves mappings across modules',async()=>{
 const h=await mount('ProsoftView'),v=h.view;
 try{
  assert.equal(v.competence.value,'2026-09');v.accounts.value={7:{code:'700',confirmed:true}};v.participants.value={5:{code:'F005',confirmed:true,third_type:'normal'}};
  let pending=v.run();assert.equal(h.requests[0].options.body.period,'2026-09');assert.equal(h.requests[0].options.body.participants[5].code,'F005');
  h.state.contextPreferences.month='10';h.requests.shift().resolve({filename:'old'});await pending;assert.equal(v.preview.value,null);
  v.competence.value='2026-07';h.state.module='fiscal';h.state.period='2026-12';await nextTick();assert.equal(v.competence.value,'2026-07');assert.equal(v.accounts.value[7].code,'700');assert.equal(v.participants.value[5].code,'F005');
  h.state.module='accounting';pending=v.run();assert.equal(h.requests[0].options.body.period,'2026-07');h.requests.shift().resolve({filename:'current'});await pending;assert.equal(v.preview.value.filename,'current');
  h.state.companyId=2;await nextTick();assert.deepEqual(v.accounts.value,{});assert.deepEqual(v.participants.value,{});assert.equal(v.preview.value,null);
 }finally{h.close();}
});
