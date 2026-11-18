import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createRenderer,reactive,nextTick} from 'vue';
const require=createRequire(import.meta.url),vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
let counter=0;
async function setup(){
 const calls=[],pending=[],state=reactive({companyId:1,period:'2026-11',module:'fiscal',session:{user:{id:7}},allowed:true});
 const key='__spedWorkspaceTest'+(++counter);
 globalThis[key]={state,api:(path,options)=>{calls.push({path,options});return new Promise((resolve,reject)=>pending.push({resolve,reject}));},scope:p=>'/companies/'+state.companyId+p,can:()=>state.allowed};
 const mock=`data:text/javascript;base64,${Buffer.from(`export const {state,api,scope,can}=globalThis.${key};`).toString('base64')}`;
 const source=await readFile(new URL('../src/views/SpedWorkspaceView.vue',import.meta.url),'utf8');
 const code=compileScript(parse(source).descriptor,{id:key}).content.replace(/from ['"]vue['"]/g,`from '${vueUrl}'`).replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`).replace(/import SpedGeneratorView from '[^']+';/,'const SpedGeneratorView={};');
 const component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;
 let view;const original=component.setup;component.setup=(p,c)=>{view=original(p,c);return ()=>null;};
 const renderer=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null}),app=renderer.createApp(component,{area:'fiscal'});app.mount({});
 pending.shift().resolve({obligations:[]});await nextTick();await nextTick();pending.shift().resolve([{id:9,filename:'origem.efd',period:'2026-11'}]);await nextTick();await nextTick();
 return {calls,pending,state,get v(){return view;},close(){app.unmount();delete globalThis[key];}};
}
test('exportação da EFD original é explícita, sem consolidar, e não entrega resposta após revogação',async()=>{
 const f=await setup();try{
  assert.equal(f.calls.filter(c=>c.options?.method==='POST').length,0);
  f.v.nativeImport.value='9';const task=f.v.native();await f.v.native();
  assert.deepEqual(f.calls.at(-1).options.body,{period:'2026-11',import_id:9,consolidate_nfce:false,segment_on_gap:true});
  assert.equal(f.calls.filter(c=>c.options?.method==='POST').length,1);
  f.state.allowed=false;f.pending.shift().resolve({content_base64:'',filename:'origem.efd'});await task;
  // No DOM/download implementation: a download after revocation would fail and
  // populate the error. Permission loss must discard the result entirely.
  assert.equal(f.v.error.value,'');assert.equal(f.v.busy.value,false);
 }finally{f.close();}
});
test('troca de empresa descarta exportação antiga e limpa a seleção de arquivo',async()=>{
 const f=await setup();try{
  f.v.nativeImport.value='9';const task=f.v.native(),old=f.pending.shift();f.state.companyId=2;await nextTick();await nextTick();
  old.resolve({content_base64:'',filename:'empresa-anterior.efd'});await task;
  assert.equal(f.v.nativeImport.value,'');assert.equal(f.v.error.value,'');assert.equal(f.v.busy.value,false);
 }finally{f.close();}
});
