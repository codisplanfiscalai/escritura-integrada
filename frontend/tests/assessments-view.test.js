import test from 'node:test';import assert from 'node:assert/strict';import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';import {pathToFileURL} from 'node:url';import {parse,compileScript} from '@vue/compiler-sfc';import {createRenderer,reactive,ref} from 'vue';
const require=createRequire(import.meta.url),vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
let serial=0;
async function mount(){
 const state=reactive({companyId:1,period:'2026-11',module:'fiscal',editor:null,contextBusy:false});const pending=[],calls=[],questions=[];let answer=false;
 const data=ref({documents:[],rules:[],assessments:[],adjustments:[],ledgers:[]});
 globalThis.__assessmentTest={state,company:ref({name:'Sintética'}),api:(url,options)=>{calls.push({url,options});return new Promise((resolve,reject)=>pending.push({resolve,reject}));},scope:(u,c=state.companyId)=>`/companies/${c}${u}`,useResource:()=>({data,error:ref(''),loading:ref(false),reload:()=>{}}),notify:()=>{},changed:()=>{},ask:async q=>{questions.push(q);return answer;},can:()=>true,allowedApi:()=>Promise.resolve([]),writable:()=>true,captureContext:()=>({companyId:state.companyId,module:state.module}),contextMatches:c=>c.companyId===state.companyId&&c.module===state.module};
 const mock=`data:text/javascript;base64,${Buffer.from('export const {state,company,api,scope,useResource,notify,changed,ask,can,allowedApi,writable,captureContext,contextMatches}=globalThis.__assessmentTest; // '+(++serial)).toString('base64')}`;
 const source=await readFile(new URL('../src/views/AssessmentsView.vue',import.meta.url),'utf8');const {descriptor}=parse(source);
 const code=compileScript(descriptor,{id:'assessment-view'}).content.replace(/from ['"]vue['"]/g,`from '${vueUrl}'`).replace(/import (\w+) from ['"][^'"]+\.vue['"];?/g,'const $1={};').replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`).replace(/from ['"]\.\.\/lib\/context-preferences\.js['"]/g,`from 'data:text/javascript,export const useSuggestedCompetence=()=>{};'`).replace(/from ['"]\.\.\/lib\/(format|assessment-preparation)(?:\.js)?['"]/g,(_,n)=>`from '${new URL('../src/lib/'+n+'.js',import.meta.url).href}'`);
 const component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;let view;const setup=component.setup;component.setup=(p,c)=>{view=setup(p,c);return ()=>null;};const app=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null}).createApp(component);app.mount({});
 return {state,pending,calls,questions,view,data,answer:v=>answer=v,dispose:()=>{app.unmount();delete globalThis.__assessmentTest;}};
}
test('prévia/salvar separados, repetição bloqueada, edição invalida e contexto descarta resposta tardia',async()=>{
 const h=await mount(),v=h.view;try{
  let p=v.open();await v.open();assert.equal(h.calls.length,1);h.pending.shift().resolve({carry_credit_cents:0});await p;
  Object.assign(v.form.value,{source:'Fonte',responsible:'Teste',no_movement_confirmed:true});await v.save();assert.equal(h.calls.length,1);
  p=v.confer();await v.confer();assert.equal(h.calls.length,2);h.pending.shift().resolve({snapshot:{},fingerprint:'fp',coverage:{fingerprint:'inv'}});await p;assert.ok(v.preview.value);
  v.form.value.source='Nova fonte';assert.equal(v.preview.value,null);p=v.confer();h.pending.shift().resolve({snapshot:{},fingerprint:'fp2',coverage:{fingerprint:'inv2'}});await p;
  p=v.save();await v.save();assert.equal(h.calls.length,4);assert.equal(h.calls.at(-1).options.body.preview_fingerprint,'fp2');h.pending.shift().reject(new Error('Origem mudou'));await p;assert.equal(v.show.value,true);assert.equal(v.preview.value,null);
  p=v.confer();h.state.companyId=2;assert.equal(v.show.value,false);h.pending.shift().resolve({fingerprint:'old'});await p;assert.equal(v.preview.value,null);assert.equal(h.state.editor,null);
 }finally{h.dispose();}
});
test('só saldo pede confirmação, cancela preservando bases e nunca exclui documentos',async()=>{
 const h=await mount(),v=h.view;try{
  let p=v.open();h.pending.shift().resolve({});await p;v.form.value.entries=[{document_id:1,base:'50,00',selected:true}];
  await v.balanceOnly();assert.equal(v.form.value.entries.length,1);assert.equal(h.questions.length,1);
  h.answer(true);await v.balanceOnly();assert.equal(v.form.value.entries.length,0);assert.equal(v.form.value.no_movement_confirmed,false);assert.equal(h.calls.length,1);
  await v.close();assert.equal(v.show.value,false);assert.equal(h.state.editor,null);
 }finally{h.dispose();}
});
