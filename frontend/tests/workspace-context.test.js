import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { createRenderer, reactive } from 'vue';
import { parse, compileScript } from '@vue/compiler-sfc';
const require = createRequire(import.meta.url);
const vueUrl = pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
const dataUrl = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const libUrl = name => new URL(`../src/lib/${name}.js`, import.meta.url).href;

test('fixar competência não altera mês operacional; ano opcional e limpeza são atômicos', async () => {
  const source=(await readFile(new URL('../src/lib/workspace.js',import.meta.url),'utf8'))
    .replace(/from 'vue'/g,`from '${vueUrl}'`).replace(/from '\.\/format'/g,`from '${libUrl('format')}'`)
    .replace(/from '\.\/context-preferences.js'/g,`from '${libUrl('context-preferences')}'`);
  const {state,applyWorkspaceContext,activate}=await import(dataUrl(source));
  Object.assign(state,{companyId:1,period:'2026-11',module:'fiscal',editor:null,confirm:null,contextBusy:false,contextPreferences:{year:'',month:''},session:{user:{id:1,role:'custom'},permissions:{},csrf_token:'test'}});
  const requests=[],original=globalThis.fetch;let rejected=false;
  globalThis.fetch=async(url,options)=>{
    if(url!=='/api/context')return {ok:true,status:200,json:async()=>({})};
    const payload=JSON.parse(options.body);requests.push(payload);
    return rejected?{ok:false,status:409,json:async()=>({detail:'Exercício não cadastrado.'})}:{ok:true,status:200,json:async()=>({active_company_id:payload.company_id,period:payload.period||(payload.year?`${payload.year}-${state.period.slice(5)}`:state.period),module:payload.module||state.module,permissions:{}})};
  };
  try{
    await applyWorkspaceContext({companyId:1,year:'',month:'02'});
    assert.deepEqual(requests.at(-1),{company_id:1});assert.equal(state.period,'2026-11');assert.equal(state.contextPreferences.month,'02');
    await applyWorkspaceContext({companyId:1,year:'2024',month:'02'});
    assert.deepEqual(requests.at(-1),{company_id:1,year:2024});
    await activate(2,undefined,'accounting');assert.deepEqual(requests.at(-1),{company_id:2,year:2024,module:'accounting'});
    rejected=true;await assert.rejects(applyWorkspaceContext({companyId:3,year:'2025',month:'06'}),/Exercício/);
    assert.equal(state.companyId,2);assert.deepEqual({...state.contextPreferences},{year:'2024',month:'02'});assert.equal(state.contextBusy,false);
    rejected=false;await applyWorkspaceContext({companyId:'',year:'',month:''});
    assert.deepEqual(requests.at(-1),{company_id:null});assert.equal(state.companyId,null);assert.equal(state.tab,'dashboard');assert.deepEqual({...state.contextPreferences},{year:'',month:''});assert.deepEqual({...state.yearLocks},{});
    state.contextBusy=true;const count=requests.length;assert.equal(await applyWorkspaceContext({companyId:1}),false);assert.equal(requests.length,count);
    state.contextBusy=false;await assert.rejects(applyWorkspaceContext({companyId:1,year:'abc'}),/Confira/);
  }finally{globalThis.fetch=original;}
});

test('F8 abre seleção; repetir e cancelar preservam contexto; edição e confirmação bloqueiam troca', async()=>{
  const state=reactive({session:{authenticated:true},companyId:1,period:'2026-11',contextPreferences:{year:'',month:'02'},contextBusy:false,editor:null,confirm:null});
  const operations=[],messages=[];
  globalThis.__contextTest={state,company:{value:null},activate:async()=>true,applyWorkspaceContext:async value=>{operations.push({...value});return true;},setContextPreferences:()=>{},notify:m=>messages.push(m),navigate:()=>{},moduleNames:{fiscal:'Fiscal'}};
  const mock=dataUrl('export const {state,company,activate,applyWorkspaceContext,setContextPreferences,notify,navigate,moduleNames}=globalThis.__contextTest;');
  const {descriptor}=parse(await readFile(new URL('../src/components/WorkspaceContext.vue',import.meta.url),'utf8'));
  const code=compileScript(descriptor,{id:'workspace-context-test'}).content
    .replace(/from ['"]vue['"]/g,`from '${vueUrl}'`).replace(/import (\w+) from ['"][^'"]+\.vue['"];?/g,'const $1={};')
    .replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`)
    .replace(/from ['"]\.\.\/lib\/format['"]/g,`from '${libUrl('format')}'`)
    .replace(/from ['"]\.\.\/lib\/context-preferences.js['"]/g,`from '${libUrl('context-preferences')}'`);
  const component=(await import(dataUrl(code))).default;let view;const setup=component.setup;
  component.setup=(props,context)=>{view=setup(props,context);return()=>null;};
  const listeners=new Map(),originalWindow=globalThis.window,originalDocument=globalThis.document;
  globalThis.window={addEventListener:(key,fn)=>listeners.set(key,fn),removeEventListener:key=>listeners.delete(key)};
  globalThis.document={querySelector:()=>null};
  const renderer=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null});
  const app=renderer.createApp(component);app.mount({});
  const event=(extra={})=>({key:'F8',preventDefault(){this.prevented=true;},...extra});
  try{
    listeners.get('keydown')(event({ctrlKey:true}));assert.equal(view.show.value,false);
    listeners.get('keydown')(event());assert.equal(view.show.value,true);assert.equal(view.draft.value.companyId,1);
    view.draft.value.companyId=2;view.draft.value.month='12';listeners.get('keydown')(event({repeat:true}));assert.equal(view.draft.value.companyId,2);
    view.close();assert.equal(view.show.value,false);assert.equal(state.companyId,1);assert.equal(state.contextPreferences.month,'02');
    view.open();assert.equal(view.draft.value.month,'02');view.draft.value.month='03';await view.save();assert.equal(operations.length,1);assert.equal(operations[0].month,'03');assert.equal(view.show.value,false);
    state.editor={name:'Documento'};view.keyboard(event());assert.equal(view.show.value,false);assert.equal(messages.length,2);
    state.editor=null;state.confirm={};view.keyboard(event());assert.equal(view.show.value,false);
    state.confirm=null;state.contextBusy=true;view.keyboard(event());assert.equal(view.show.value,false);
    state.contextBusy=false;state.session.authenticated=false;view.keyboard(event());assert.equal(view.show.value,false);
  }finally{app.unmount();assert.equal(listeners.size,0);globalThis.window=originalWindow;globalThis.document=originalDocument;delete globalThis.__contextTest;}
});
