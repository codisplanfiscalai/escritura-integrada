import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createRenderer,createSSRApp,reactive,ref,nextTick} from 'vue';
import {renderToString} from '@vue/server-renderer';

const require=createRequire(import.meta.url);
const vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
const source=await readFile(new URL('../src/views/PeriodsView.vue',import.meta.url),'utf8');
const dataUrl=code=>`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`;
const january={period:'2028-01',enabled:true,closed:true,version:3};
const calendar={years:[{year:2028}],months:[january]};
const flush=async()=>{await nextTick();await new Promise(resolve=>setImmediate(resolve));await nextTick();};
let serial=0;
async function harness({render=false,initialize=()=>{}}={}){
 const state=reactive({companyId:1,period:'2028-01',module:'fiscal',refresh:0,contextBusy:false,editor:null,confirm:null});
 const requests=[],activations=[],messages=[],key=`__periodsConcurrency${++serial}`;
 const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
 globalThis[key]={state,company:ref({code:'SYN',name:'Empresa sintética'}),scope:(url,id=state.companyId)=>`/companies/${id}${url}`,
  api:(url,options)=>{const pending=deferred();requests.push({url,options,...pending});return pending.promise;},
  // Preserve activate's two distinct phases: POST context, then asynchronous refreshLocks.
  activate:async(id,period,module)=>{
   if(state.contextBusy||state.editor||state.confirm)return false;
   state.contextBusy=true;const context=deferred(),locks=deferred();activations.push({id,period,module,context,locks});
   try{await context.promise;state.companyId=id;state.period=period;state.module=module;state.refresh++;await locks.promise;return true;}
   finally{state.contextBusy=false;}
  },
  changed:()=>state.refresh++,notify:(...args)=>messages.push(args),can:()=>true,moduleNames:{fiscal:'Fiscal'},initialize};
 const mock=dataUrl(`export const {state,company,api,scope,notify,changed,activate,can,moduleNames}=globalThis.${key};`);
 const input=render?source.replace('</script>',`globalThis.${key}.initialize({state,loading,busy,data,history,show,selected,reason,context});\n</script>`):source;
 const {descriptor}=parse(input);
 const code=compileScript(descriptor,{id:key,inlineTemplate:render}).content
  .replace(/from ['"]vue['"]/g,`from '${vueUrl}'`)
  .replace(/import (\w+) from ['"][^'"]+\.vue['"];?/g,'const $1={render:()=>null};')
  .replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`)
  .replace(/from ['"]\.\.\/lib\/format['"]/g,`from '${new URL('../src/lib/format.js',import.meta.url).href}'`);
 const component=(await import(dataUrl(code))).default;
 if(render){try{return await renderToString(createSSRApp(component,{module:'fiscal'}));}finally{delete globalThis[key];}}
 let view;const setup=component.setup;component.setup=(props,context)=>{view=setup(props,context);return()=>null;};
 const renderer=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null});
 const app=renderer.createApp(component,{module:'fiscal'});app.mount({});
 const resolveReads=async()=>{
  for(let i=0;i<4;i++){
   const reads=requests.filter(r=>!r.options?.method&&!r.resolved);
   if(!reads.length)break;
   for(const r of reads){r.resolved=true;r.resolve(r.url.includes('/history?')?[]:calendar);}
   await flush();
  }
 };
 let closed=false;
 return {view,state,requests,activations,messages,resolveReads,close:()=>{if(!closed){closed=true;app.unmount();delete globalThis[key];}}};
}

// Render the actual template with each blocking state, not a source-string assertion.
async function assertControlsDisabled(overrides={},disabled=true){
 const html=await harness({render:true,initialize:v=>{
  v.data.value=calendar;v.loading.value=false;
  for(const [key,value] of Object.entries(overrides))v[key].value=value;
 }});
 for(const label of ['Selecionada','Reabrir','Cadastrar exercício']){
  const button=html.match(new RegExp(`<button([^>]*)>\\s*${label}\\s*</button>`));
  assert.ok(button,`button ${label} rendered`);assert.equal(/\bdisabled(?:[\s=>]|$)/.test(button[1]),disabled,label);
 }
 for(const label of ['Exercício do módulo','Ano do novo exercício']){
  const input=html.match(new RegExp(`<(?:select|input)([^>]*aria-label="${label}"[^>]*)>`));
  assert.ok(input,`input ${label} rendered`);assert.equal(/\bdisabled(?:[\s=>]|$)/.test(input[1]),disabled,label);
 }
}

test('seleção bloqueia reabertura desde o POST de contexto até a conclusão dos bloqueios e da recarga',async()=>{
 const h=await harness(),v=h.view;
 try{
  await h.resolveReads();assert.equal(v.loading.value,false);
  const selecting=v.select(january);assert.equal(h.activations.length,1);assert.equal(h.state.contextBusy,true);
  const count=h.requests.length;
  v.open(january);await v.select(january);await v.create();
  assert.equal(v.show.value,false);assert.equal(h.activations.length,1);assert.equal(h.requests.length,count);
  h.activations[0].context.resolve();await flush();assert.equal(v.loading.value,true);
  await h.resolveReads();assert.equal(v.loading.value,false);assert.equal(h.state.contextBusy,true);
  v.open(january);assert.equal(v.show.value,false,'calendar may finish before refreshLocks, but cannot open during activation');
  h.activations[0].locks.resolve();await selecting;await flush();assert.equal(v.interactionBlocked.value,false);
  v.open(january);assert.equal(v.show.value,true);assert.equal(v.selected.value.version,3);
  v.reason.value='Revisão sintética autorizada';const editor=h.state.editor;
  h.state.refresh++;await flush();await h.resolveReads();
  assert.equal(v.show.value,true);assert.equal(v.reason.value,'Revisão sintética autorizada');assert.equal(h.state.editor,editor,'background reload preserves editor ownership');
  await v.select({...january,period:'2028-02'});await v.create();v.open({...january,period:'2028-02'});
  assert.equal(h.activations.length,1);assert.equal(v.selected.value.period,'2028-01');assert.equal(v.reason.value,'Revisão sintética autorizada');
  v.close();assert.equal(h.state.editor,null);assert.equal(v.show.value,false);
 }finally{h.close();}
});

test('persistência é única, mantém contexto protegido durante recarga e preserva justificativa em falha',async()=>{
 const h=await harness(),v=h.view;
 try{
  await h.resolveReads();v.open(january);v.reason.value='Revisão sintética autorizada';
  const saving=v.save(),request=h.requests.at(-1);assert.equal(request.url,'/companies/1/periods/reopen');
  assert.deepEqual(request.options.body,{module:'fiscal',period:'2028-01',version:3,reason:'Revisão sintética autorizada'});
  const count=h.requests.length,editor=h.state.editor;
  await v.save();await v.create();await v.select(january);v.open({...january,period:'2028-02'});v.close();
  assert.equal(h.requests.length,count);assert.equal(h.activations.length,0);assert.equal(v.show.value,true);assert.equal(h.state.editor,editor);
  request.reject(new Error('Versão alterada. Recarregue.'));await saving;
  assert.equal(v.busy.value,false);assert.equal(v.show.value,true);assert.equal(v.reason.value,'Revisão sintética autorizada');assert.match(v.error.value,/Versão alterada/);
  const retry=v.save();h.requests.at(-1).resolve({});await flush();
  assert.equal(v.show.value,false);assert.equal(v.busy.value,true);assert.equal(h.state.editor,editor,'context stays protected until fresh calendar is ready');
  v.open(january);await v.create();await v.select(january);assert.equal(h.activations.length,0);
  await h.resolveReads();await retry;assert.equal(v.busy.value,false);assert.equal(h.state.editor,null);assert.equal(v.interactionBlocked.value,false);
 }finally{h.close();}
});

test('cadastro de exercício impede duplicação e protege contexto; editor de outra tela nunca é apagado',async()=>{
 const h=await harness(),v=h.view;
 try{
  await h.resolveReads();v.newYear.value=2028;
  const creating=v.create(),request=h.requests.at(-1);assert.deepEqual(request.options.body,{year:2028,module:'fiscal'});
  const count=h.requests.length;assert.equal(h.state.editor.companyId,1);
  await v.create();await v.select(january);v.open(january);assert.equal(h.requests.length,count);assert.equal(h.activations.length,0);assert.equal(v.show.value,false);
  request.resolve({});await flush();assert.notEqual(h.state.editor,null);await h.resolveReads();await creating;
  assert.equal(h.state.editor,null);assert.equal(v.busy.value,false);
  h.state.editor={name:'Outra janela',companyId:1};const other=h.state.editor;
  v.open(january);await v.create();await v.select(january);v.close();
  assert.equal(h.state.editor,other);assert.equal(v.show.value,false);assert.equal(h.activations.length,0);
  h.close();assert.equal(h.state.editor,other,'unmount cannot clear another editor');
 }finally{h.close();}
});

test('template desabilita ações e campos durante leitura, persistência, contexto, editor ou confirmação',async()=>{
 await assertControlsDisabled({},false);
 await assertControlsDisabled({loading:true});await assertControlsDisabled({busy:true});
 for(const flag of ['contextBusy','editor','confirm']){
  const html=await harness({render:true,initialize:v=>{
   v.loading.value=false;v.data.value=calendar;
   v.state[flag]=flag==='contextBusy'?true:{name:'Outra janela'};
  }});
  for(const label of ['Selecionada','Reabrir','Cadastrar exercício'])assert.match(html,new RegExp(`<button[^>]*disabled[^>]*>\\s*${label}\\s*</button>`),flag);
  for(const label of ['Exercício do módulo','Ano do novo exercício'])assert.match(html,new RegExp(`<(?:select|input)[^>]*disabled[^>]*aria-label="${label}"`),flag);
 }
});
