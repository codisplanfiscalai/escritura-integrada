import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createRenderer,reactive,nextTick} from 'vue';
const require=createRequire(import.meta.url),vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
const tick=async()=>{await nextTick();await nextTick();};
let counter=0;
async function setup(provider='nfe_distribution'){
 const calls=[],pending=[],navigations=[],state=reactive({companyId:1,period:'2026-11',module:'fiscal',tab:'dfe',session:{user:{id:7}},editor:null,allowed:true});
 const key='__bookkeepingTest'+(++counter);
 globalThis[key]={state,api:(path,options)=>{calls.push({path,options});return new Promise((resolve,reject)=>pending.push({resolve,reject}));},scope:p=>'/companies/'+state.companyId+p,can:()=>state.allowed,navigate:async p=>navigations.push(p)};
 const mock=`data:text/javascript;base64,${Buffer.from(`export const {state,api,scope,can,navigate}=globalThis.${key};`).toString('base64')}`;
 const source=await readFile(new URL('../src/components/ReceptionBookkeeping.vue',import.meta.url),'utf8');
 const code=compileScript(parse(source).descriptor,{id:key}).content.replace(/from ['"]vue['"]/g,`from '${vueUrl}'`).replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`);
 const component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;
 let view;const original=component.setup;component.setup=(p,c)=>{view=original(p,c);return ()=>null;};
 const props=reactive({provider,environment:'production',filters:{competence:'2026-09',query:'TESTE',direction:'received'},selected:[{receipt_key:'synthetic-source',nsu:'1'}]});
 const renderer=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null}),app=renderer.createApp(component,props);app.mount({});
 return {calls,pending,navigations,state,props,get v(){return view;},close(){app.unmount();delete globalThis[key];}};
}
test('seleção e filtros geram lote para revisão, sem confirmar escrituração implicitamente',async()=>{
 const f=await setup();try{
  const task=f.v.prepare(false);await f.v.prepare(false);assert.equal(f.calls.length,1);assert.match(f.calls[0].path,/bookkeeping-preview$/);
  assert.deepEqual(f.calls[0].options.body.documents,[{receipt_key:'synthetic-source',nsu:'1'}]);assert.equal(f.calls[0].options.body.posting_date,'2026-11-01');
  f.pending.shift().resolve({import_id:12});await task;assert.deepEqual(f.navigations,['imports']);assert.equal(f.state.receptionImport.importId,12);assert.equal(f.state.editor,null);
  const all=f.v.prepare(true);assert.deepEqual(f.calls.at(-1).options.body.filters,{competence:'2026-09',query:'TESTE',direction:'received'});assert.equal(f.calls.at(-1).options.body.documents,undefined);
  f.pending.shift().resolve({import_id:13});await all;assert.ok(f.calls.every(c=>!c.path.includes('/confirm')));
 }finally{f.close();}
});
test('resposta atrasada não abre lote de outra empresa nem mantém editor bloqueado',async()=>{
 const f=await setup();try{const task=f.v.prepare();f.state.companyId=2;await tick();assert.equal(f.state.editor,null);f.pending.shift().resolve({import_id:99});await task;assert.equal(f.state.receptionImport,undefined);assert.deepEqual(f.navigations,[]);assert.equal(f.v.busy.value,false);}finally{f.close();}
});
test('perfil precisa ser salvo; alteração de contexto e perda de permissão impedem preparação',async()=>{
 const f=await setup('nfse_adn');try{
  f.pending.shift().resolve({version:0,base:false,iss:false,iss_withheld:false,source:'TESTE',responsible:'TESTE'});await tick();assert.equal(f.v.dirty.value,false);
  f.v.profile.value.base=true;assert.equal(f.v.dirty.value,true);await f.v.prepare();assert.equal(f.calls.length,1);
  const save=f.v.saveProfile();assert.equal(f.calls.at(-1).options.method,'PUT');f.pending.shift().resolve({...f.v.profile.value,version:1});await save;assert.equal(f.v.dirty.value,false);
  f.state.allowed=false;await tick();await f.v.prepare();assert.equal(f.calls.length,2);
 }finally{f.close();}
});
