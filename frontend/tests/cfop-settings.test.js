import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createRenderer,reactive,ref} from 'vue';
test('catálogo contextual é importado explicitamente, preserva edição e registra a versão',async()=>{
 const require=createRequire(import.meta.url),vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
 const calls=[];
 globalThis.__cfopTest={state:reactive({companyId:1,period:'2026-09',session:{user:{username:'Revisor'}}}),company:ref({name:'Empresa sintética'}),api:async(url,options)=>{calls.push({url,options});return {}},scope:url=>url,useResource:()=>({data:ref([]),reload:async()=>{}}),can:()=>true,allowedApi:()=>{},ask:async()=>true,notify:()=>{},changed:()=>{}};
 const mock=`data:text/javascript;base64,${Buffer.from('export const {api,scope,state,company,useResource,can,allowedApi,ask,notify,changed}=globalThis.__cfopTest;').toString('base64')}`;
 const source=await readFile(new URL('../src/views/CfopView.vue',import.meta.url),'utf8');
 const {descriptor}=parse(source);
 let code=compileScript(descriptor,{id:'cfop-settings-test'}).content.replace(/from ['"]vue['"]/g,`from '${vueUrl}'`).replace(/import (\w+) from ['"][^'"]+\.vue['"];?/g,'const $1={};').replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`).replace(/from ['"]\.\.\/lib\/format['"]/g,`from '${new URL('../src/lib/format.js',import.meta.url).href}'`);
 code=code.replace("from '../lib/context-preferences.js'",`from '${new URL('../src/lib/context-preferences.js',import.meta.url).href}'`);
 const component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;
 let view;const setup=component.setup;component.setup=(props,context)=>{view=setup(props,context);return ()=>null;};
 const renderer=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null}),app=renderer.createApp(component);app.mount({});
 try{
  view.settings.value={version:2,purchase_destination:'resale',reason:'Revisão sintética',responsible:'Revisor',fallback_mappings:[{source_cfop:'5102',target_cfop:'1556',purchase_destination:'resale'}]};
  view.fallbackCatalog.value=[{source_cfop:'5102',target_cfop:'1102',purchase_destination:'resale'},{source_cfop:'6102',target_cfop:'2102',purchase_destination:'resale'}];view.catalogVersion.value='synthetic-v1';
  assert.equal(calls.length,0);
  view.importFallbackCatalog();view.importFallbackCatalog();
  assert.equal(view.settings.value.fallback_mappings.length,2);assert.equal(view.settings.value.fallback_mappings[0].target_cfop,'1556');assert.equal(view.settings.value.source_catalog_version,'synthetic-v1');assert.equal(calls.length,0,'importar prepara sem ativar antes de salvar');
  await view.saveSettings();assert.equal(calls.length,1);assert.equal(calls[0].options.method,'PUT');assert.equal(calls[0].options.body.source_catalog_version,'synthetic-v1');assert.equal(view.settings.value,null);
 }finally{app.unmount();delete globalThis.__cfopTest;}
});
