import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createRenderer,reactive,ref,nextTick} from 'vue';
import {prosoftDefaults} from '../src/lib/prosoft-export.js';
const require=createRequire(import.meta.url),vue=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
const url=s=>`data:text/javascript;base64,${Buffer.from(s).toString('base64')}`;
let mountSequence=0;
async function mount(file){
 const state=reactive({companyId:1,module:'accounting',period:'2026-11',contextPreferences:{month:'09'}}),requests=[];
 globalThis.__periodView={state,company:ref({prosoft_code:'1'}),api:(path,options)=>path.endsWith('/settings')&&options.method==='GET'?Promise.resolve({settings:prosoftDefaults('accounting','1'),version:0}):new Promise(resolve=>requests.push({path,options,resolve})),scope:(p,cid=state.companyId)=>`/companies/${cid}${p}`,useResource:()=>({data:ref({accounts:[],centers:[]})}),notify:()=>{},can:()=>true,allowedApi:async()=>[],writable:()=>true};
 const mock=url('export const {state,company,api,scope,useResource,notify,can,allowedApi,writable}=globalThis.__periodView; // mount '+(++mountSequence));
 const {descriptor}=parse(await readFile(new URL(`../src/views/${file}.vue`,import.meta.url),'utf8'));
 const code=compileScript(descriptor,{id:'period-view'}).content.replace(/import (\w+) from ['"][^'"]+\.vue['"];?/g,'const $1={render:()=>null};').replace(/from ['"]vue['"]/g,`from '${vue}'`).replace(/from ['"]\.\.\/lib\/([^'"]+)['"]/g,(_,name)=>`from '${name==='workspace'?mock:new URL(`../src/lib/${name.replace(/\.js$/,'')}.js`,import.meta.url).href}'`);
 const component={...(await import(url(code))).default};let view;const setup=component.setup;component.setup=(p,c)=>{view=setup(p,c);return()=>null;};
 const app=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null}).createApp(component);app.mount({});
 return {state,view,requests,close:()=>{app.unmount();delete globalThis.__periodView;}};
}
test('Prosoft uses editable suggested month, discards stale responses and preserves mappings across modules',async()=>{
 const h=await mount('ProsoftView'),v=h.view;await new Promise(resolve=>setTimeout(resolve,10));
 try{
  assert.equal(v.competence.value,'2026-09');v.s.config.accounts={7:{code:'700',confirmed:true}};v.s.config.participants={5:{code:'F005',confirmed:true,third_type:'normal'}};
  let pending=v.controller.run();assert.equal(h.requests[0].options.body.period,'2026-09');assert.equal(h.requests[0].options.body.participants[5].code,'F005');
  h.state.contextPreferences.month='10';h.requests.shift().resolve({filename:'old'});await pending;assert.equal(v.s.preview,null);
  v.competence.value='2026-07';h.state.module='fiscal';h.state.period='2026-12';await nextTick();assert.equal(v.competence.value,'2026-07');assert.equal(v.s.config.accounts[7].code,'700');assert.equal(v.s.config.participants[5].code,'F005');
  h.state.module='accounting';await new Promise(resolve=>setTimeout(resolve,10));pending=v.controller.run();assert.equal(h.requests[0].options.body.period,'2026-07');h.requests.shift().resolve({filename:'current'});await pending;assert.equal(v.s.preview.filename,'current');
  h.state.companyId=2;await nextTick();assert.deepEqual(v.s.config.accounts,{});assert.deepEqual(v.s.config.participants,{});assert.equal(v.s.preview,null);
 }finally{h.close();}
});

test('Prosoft retains unsaved company mappings across an exercise change and invalidates its preview',async()=>{
 const h=await mount('ProsoftView'),v=h.view;await new Promise(resolve=>setTimeout(resolve,10));
 try{
  v.s.config.accounts={7:{code:'700',confirmed:true}};v.s.preview={filename:'old'};
  h.state.period='2027-11';await nextTick();await new Promise(resolve=>setTimeout(resolve,10));
  assert.equal(v.competence.value,'2027-09');assert.equal(v.s.config.accounts[7].code,'700');assert.equal(v.s.preview,null);
 }finally{h.close();}
});


test('Prosoft subguides preserve draft, filters, competence and preview; reload cancellation is safe',async()=>{
 const h=await mount('ProsoftView'),v=h.view;await new Promise(resolve=>setTimeout(resolve,10));
 const previousWindow=globalThis.window;
 try{
  v.s.config.plan_code='0052';v.query.value='caixa';v.onlyUsed.value=false;v.competence.value='2026-08';
  await new Promise(resolve=>setTimeout(resolve,10));
  const pending=v.controller.run();h.requests.shift().resolve({filename:'synthetic'});await pending;
  const config=JSON.stringify(v.s.config);
  for(const section of ['settings','coverage','export','export']){v.selectSection(section);await nextTick();}
  assert.equal(v.s.preview.filename,'synthetic');assert.equal(JSON.stringify(v.s.config),config);
  assert.equal(v.query.value,'caixa');assert.equal(v.onlyUsed.value,false);assert.equal(v.competence.value,'2026-08');
  globalThis.window={confirm:()=>false};v.reloadSaved();assert.equal(v.s.config.plan_code,'0052');assert.equal(v.s.preview.filename,'synthetic');
 }finally{globalThis.window=previousWindow;h.close();}
});
