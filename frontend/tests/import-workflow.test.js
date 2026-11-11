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
const source=await readFile(new URL('../src/views/ImportView.vue',import.meta.url),'utf8');
let serial=0;
async function harness({module='fiscal',render=false,initialize=()=>{},reload=async()=>{}}={}){
 const state=reactive({companyId:1,period:'2026-11',module}),pending=[],questions=[],history=ref([]),answer=ref(true);
 const key=`__importWorkflow${++serial}`;
 globalThis[key]={state,company:ref({name:'Empresa sintética'}),api:(url,options)=>new Promise((resolve,reject)=>pending.push({url,options,resolve,reject})),scope:(url,cid=state.companyId)=>`/companies/${cid}${url}`,useResource:()=>({data:history,reload}),rows:x=>x,notify:()=>{},changed:()=>{},ask:async options=>{questions.push(options);return answer.value;},can:()=>true,allowedApi:()=>{},writable:()=>true,navigate:()=>{},initialize};
 const mock=`data:text/javascript;base64,${Buffer.from(`export const {state,company,api,scope,useResource,rows,notify,changed,ask,can,allowedApi,writable,navigate}=globalThis.${key};`).toString('base64')}`;
 const input=render?source.replace('</script>',`globalThis.${key}.initialize({file,options,showOptions,preview,previewContext,postingPreview,selected,showHistory});\n</script>`):source;
 const {descriptor}=parse(input);
 let code=compileScript(descriptor,{id:key,inlineTemplate:render}).content.replace(/from ['"]vue['"]/g,`from '${vueUrl}'`).replace(/import (\w+) from ['"][^'"]+\.vue['"];?/g,'const $1={render:()=>null};').replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`).replace(/from ['"]\.\.\/lib\/format['"]/g,`from '${new URL('../src/lib/format.js',import.meta.url).href}'`);
 const component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;
 if(render){const app=createSSRApp(component);app.directive('allow',{});const html=await renderToString(app);delete globalThis[key];return html;}
 let view;const setup=component.setup;component.setup=(props,context)=>{view=setup(props,context);return ()=>null;};
 const renderer=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null}),app=renderer.createApp(component);app.mount({});
 return {view,state,pending,history,answer,questions,close:()=>{app.unmount();delete globalThis[key];}};
}
const preview={id:3,filename:'lote.xml',period:'2026-11',status:'preview',documents:[],transactions:[],issues:[]};

test('fiscal começa compacto, sem controles bancários e com ação antes das opções',async()=>{
 const html=await harness({render:true,initialize:v=>{v.file.value={name:'lote.zip',size:120};v.showOptions.value=true;}});
 assert.match(html,/Etapas da importação/);
 assert.doesNotMatch(html,/Conta bancária do extrato|CSV bancário|OFX ·/);
 assert.ok(html.indexOf('Analisar e gerar prévia')<html.indexOf('Opções avançadas de leitura'));
 assert.match(html,/id="import-history"[^>]*style="display:none;"/);
 const xml=await harness({render:true,initialize:v=>{v.file.value={name:'nota.xml',size:120};}});
 assert.doesNotMatch(xml,/Opções avançadas de leitura/);
});

test('extratos mostram conta e opções bancárias, sem data fiscal',async()=>{
 const html=await harness({render:true,module:'financial',initialize:v=>{v.file.value={name:'extrato.csv',size:120};v.showOptions.value=true;}});
 assert.match(html,/Conta bancária do extrato/);assert.match(html,/CSV bancário/);
 assert.doesNotMatch(html,/Data de escrituração do XML|XML · SPED/);
});

test('conferência substitui upload, recolhe opcionais e explica a confirmação',async()=>{
 const html=await harness({render:true,initialize:v=>{v.preview.value={...preview,documents:[{_selection:'documents:0',number:'10',model:'55',_eligibility:{status:'eligible'},source:{file:'nota.xml'}}]};v.previewContext.value={id:1,name:'Empresa sintética'};}});
 assert.doesNotMatch(html,/class="panel upload-panel"|Selecionar arquivo de importação/);
 assert.match(html,/Nova importação/);assert.match(html,/Detalhes do documento 10/);
 assert.match(html,/<details class="import-optional">/);
 assert.match(html,/Valide a revisão para atualizar os documentos aptos/);
});

test('recomeçar preserva edição ao cancelar e limpa opções, seleção e input ao aceitar',async()=>{
 const h=await harness();const {view:v}=h;
 try{
  v.preview.value={...preview};v.previewContext.value={id:1};v.options.value.posting_date='2026-09-10';v.bankAccount.value='Banco antigo';v.documentOverrides.value={'documents:0':{cfop:'1102'}};v.selected.value=['documents:0'];v.input.value={value:'arquivo.xml'};v.showOptions.value=true;
  h.answer.value=false;await v.newImport();assert.equal(v.preview.value.id,3);assert.equal(v.reviewPayload()['documents:0'].cfop,'1102');
  h.answer.value=true;await v.newImport();assert.equal(v.preview.value,null);assert.equal(v.previewContext.value,null);assert.equal(v.options.value.posting_date,'');assert.equal(v.bankAccount.value,'');assert.deepEqual(v.selected.value,[]);assert.deepEqual(v.documentOverrides.value,{});assert.equal(v.input.value.value,'');assert.equal(v.showOptions.value,false);
  v.choose({name:'nota.XML',size:100});assert.equal(v.file.value.name,'nota.XML');assert.deepEqual(v.readingOptions(),{});
  v.choose({name:'grande.xml',size:21*1024*1024});assert.equal(v.file.value,null);assert.match(v.error.value,/20 MB/);
  v.choose({name:'extrato.ofx',size:100});assert.equal(v.file.value,null);assert.match(v.error.value,/Importação de extratos/);
  v.choose({name:'nota.XML',size:100});assert.equal(v.file.value.name,'nota.XML');
 }finally{h.close();}
});

test('mudança de módulo limpa convenções antigas e financeiro nunca envia data fiscal',async()=>{
 const h=await harness();const {view:v}=h;
 try{
  v.options.value.posting_date='2026-09-10';v.options.value.decimal_separator=',';v.showOptions.value=true;v.file.value={name:'lote.csv',size:10};
  h.state.module='financial';await nextTick();assert.equal(v.file.value,null);assert.equal(v.options.value.posting_date,'');assert.equal(v.showOptions.value,false);
  v.choose({name:'extrato.csv',size:10});v.options.value.posting_date='2026-09-10';v.options.value.date_format='DMY';assert.equal('posting_date' in v.readingOptions(),false);assert.equal(v.readingOptions().date_format,'DMY');
  v.choose({name:'extrato.qif',size:10});assert.equal(v.readingOptionsAvailable.value,true);assert.equal(v.readingOptions().date_format,'DMY');v.options.value.decimal_separator=',';assert.equal(v.readingOptions().decimal_separator,',');
  v.choose({name:'extrato.ofx',size:10});v.options.value.encoding='cp1252';assert.equal(v.readingOptions().encoding,'cp1252');assert.equal('posting_date' in v.readingOptions(),false);
 }finally{h.close();}
});

test('resposta atrasada do histórico não libera nem altera processamento do novo contexto',async()=>{
 let finishReload;const h=await harness({reload:()=>new Promise(resolve=>finishReload=resolve)});const {view:v}=h;
 const oldReader=globalThis.FileReader;globalThis.FileReader=class{readAsDataURL(){this.result='data:text/xml;base64,WA==';this.onload();}};
 try{
  v.choose({name:'nota.xml',size:10});const old=v.analyze();await nextTick();assert.equal(h.pending.length,1);
  h.pending[0].resolve({...preview});await nextTick();await nextTick();assert.equal(typeof finishReload,'function');
  h.state.companyId=2;await nextTick();v.busy.value=true;finishReload();await old;
  assert.equal(v.busy.value,true);assert.equal(v.preview.value,null);assert.equal(h.pending.length,1);
 }finally{globalThis.FileReader=oldReader;h.close();}
});

test('retomar histórico respeita cancelamento e filtros preservam nomes completos',async()=>{
 const h=await harness();const {view:v}=h;
 try{
  h.history.value=[{id:1,filename:'Novembro.zip'},{id:2,filename:'Outubro.zip'}];v.historySearch.value='NOVEMBRO';assert.deepEqual(v.filteredHistory.value.map(x=>x.id),[1]);
  v.preview.value={...preview};h.answer.value=false;await v.inspect({id:1});assert.equal(h.pending.length,0);assert.equal(v.preview.value.id,3);
  h.answer.value=true;const action=v.inspect({id:1});await new Promise(resolve=>setImmediate(resolve));assert.equal(h.pending.length,1);h.pending[0].resolve({...preview,id:1,status:'confirmed'});await action;assert.equal(v.preview.value.id,1);assert.equal(v.showHistory.value,false);
 }finally{h.close();}
});

test('lote fiscal misto mantém a conta bancária disponível na conferência',async()=>{
 const html=await harness({render:true,initialize:v=>{v.preview.value={...preview,transactions:[{_selection:'transactions:0',_eligibility:{status:'eligible'},date:'2026-11-10',amount:'10.00'}]};v.previewContext.value={id:1,name:'Empresa sintética'};}});
 assert.match(html,/Conta bancária do extrato/);
});

test('voltar ao arquivo conserva arquivo e convenções para corrigir a leitura',async()=>{
 const h=await harness();const {view:v}=h;
 try{
  v.file.value={name:'lote.zip',size:100};v.options.value.encoding='cp1252';v.options.value.posting_date='2026-11-01';v.preview.value={...preview};
  h.answer.value=false;await v.returnToFile();assert.equal(v.preview.value.id,3);
  h.answer.value=true;await v.returnToFile();assert.equal(v.preview.value,null);assert.equal(v.file.value.name,'lote.zip');assert.equal(v.options.value.encoding,'cp1252');assert.equal(v.options.value.posting_date,'2026-11-01');assert.equal(v.showOptions.value,true);
 }finally{h.close();}
});
