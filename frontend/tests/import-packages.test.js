import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createRenderer,reactive,ref,nextTick} from 'vue';
test('limpeza preserva movimentos e hash, modal é opcional e mudança de contexto invalida confirmação',async()=>{
 const require=createRequire(import.meta.url),vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
 const calls=[],prompts=[];let approve=false;
 globalThis.__packageTest={state:reactive({companyId:1,session:{operational_settings:{require_extra_confirmations:true}}}),api:async(url,options)=>{calls.push({url,options});if(url.endsWith('cleanup-preview'))return {preview_hash:'synthetic-hash',eligible_ids:[1],blocked_ids:[],estimated_bytes:100};if(url.endsWith('cleanup-confirm'))return {cleaned_ids:[1]};if(url.endsWith('/settings'))return options.body;return {packages:[],settings:{enabled:false,retention_days:1825,interval_hours:24,mode:'originals'}};},scope:url=>url,can:()=>true,ask:async options=>{prompts.push(options);return approve;},notify:()=>{}};
 const mock=`data:text/javascript;base64,${Buffer.from('export const {api,scope,state,can,ask,notify}=globalThis.__packageTest;').toString('base64')}`;
 const source=await readFile(new URL('../src/components/ImportPackageControls.vue',import.meta.url),'utf8');
 const {descriptor}=parse(source);
 let code=compileScript(descriptor,{id:'package-test'}).content.replace(/from ['"]vue['"]/g,`from '${vueUrl}'`).replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`).replace(/from ['"]\.\.\/lib\/format['"]/g,`from '${new URL('../src/lib/format.js',import.meta.url).href}'`);
 const component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;
 let view;const setup=component.setup;component.setup=(props,context)=>{view=setup(props,context);return ()=>null;};
 const renderer=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null}),app=renderer.createApp(component);app.mount({});
 try{
  assert.equal(view.settings.value.enabled,false);await view.load();assert.equal(calls.length,1);
  view.settings.value.enabled=true;view.settings.value.mode='originals';await view.saveSettings();assert.equal(calls.length,1,'cancelar autorização não salva');assert.match(prompts[0].message,/nunca serão excluídos/);
  approve=true;await view.saveSettings();assert.equal(calls[1].options.body.acknowledge_irreversible,true);
  view.selected.value=[1];await view.prepareCleanup();assert.equal(view.preview.value.preview_hash,'synthetic-hash');view.mode.value='originals_and_hide_history';assert.equal(view.preview.value,null);
  await view.prepareCleanup();approve=false;const prior=calls.length;await view.confirmCleanup();assert.equal(calls.length,prior);
  approve=true;await view.confirmCleanup();const confirmed=calls.find(call=>call.url.endsWith('cleanup-confirm'));assert.equal(confirmed.options.body.acknowledge_irreversible,true);assert.equal(confirmed.options.body.mode,'originals_and_hide_history');assert.deepEqual(confirmed.options.body.ids,[1]);assert.equal('delete_documents' in confirmed.options.body,false);assert.match(prompts.at(-1).message,/movimentos e vínculos serão preservados/);
  view.mode.value='hide_history';assert.deepEqual(view.blockedReasons({blocked_reasons:['sole_fiscal_source_evidence','retention_period']}),[]);view.selected.value=[1];await view.prepareCleanup();await view.confirmCleanup();const archived=calls.filter(call=>call.url.endsWith('cleanup-confirm')).at(-1);assert.equal(archived.options.body.mode,'hide_history');assert.equal('acknowledge_irreversible' in archived.options.body,false);assert.match(prompts.at(-1).message,/economia de espaço é zero/);
  await view.restoreHistory({id:1,filename:'Sintético'});assert.deepEqual(calls.find(call=>call.url.endsWith('restore-history')).options.body,{ids:[1]});
 view.mode.value='originals';view.selected.value=[1];await view.prepareCleanup();let decide;approve=new Promise(resolve=>decide=resolve);const callCount=calls.length;const interrupted=view.confirmCleanup();await view.confirmCleanup();globalThis.__packageTest.state.companyId=2;await nextTick();decide(true);await interrupted;assert.equal(calls.length,callCount,'troca de empresa durante o modal não confirma limpeza anterior');
  globalThis.__packageTest.state.session.operational_settings.require_extra_confirmations=false;
  const promptsBefore=prompts.length;approve=false;view.mode.value='originals';view.selected.value=[1];await view.prepareCleanup();const beforeDirect=calls.filter(c=>c.url.endsWith('cleanup-confirm')).length;await Promise.all([view.confirmCleanup(),view.confirmCleanup()]);assert.equal(calls.filter(c=>c.url.endsWith('cleanup-confirm')).length,beforeDirect+1);assert.equal(prompts.length,promptsBefore);assert.equal(calls.filter(c=>c.url.endsWith('cleanup-confirm')).at(-1).options.body.acknowledge_irreversible,true);
  await view.confirmCleanup();assert.equal(calls.filter(c=>c.url.endsWith('cleanup-confirm')).length,beforeDirect+1,'sem prévia não repete limpeza');
  await view.restoreHistory({id:1,filename:'Sintético'});assert.equal(prompts.length,promptsBefore);
  view.mode.value='hide_history';view.selected.value=[1];await view.prepareCleanup();await view.confirmCleanup();assert.equal(prompts.length,promptsBefore);
 }finally{app.unmount();delete globalThis.__packageTest;}
});
