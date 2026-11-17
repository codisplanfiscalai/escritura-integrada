import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createRenderer,reactive,nextTick} from 'vue';
const require=createRequire(import.meta.url),vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
const tick=async()=>{await nextTick();await nextTick();};
test('A1 salvo mantém versão após conflito de preferências, limpa segredo e não repete o upload',async()=>{
 const calls=[],pending=[];globalThis.__receptionSettingsTest={api:(url,options)=>{calls.push({url,options});return new Promise((resolve,reject)=>pending.push({resolve,reject}));},notify:()=>{},changed:()=>{}};
 const mock=`data:text/javascript;base64,${Buffer.from('export const {api,notify,changed}=globalThis.__receptionSettingsTest;').toString('base64')}`;
 const receptionUrl=new URL('../src/lib/reception.js',import.meta.url).href;
 const source=await readFile(new URL('../src/components/CompanyReceptionSettings.vue',import.meta.url),'utf8');
 let code=compileScript(parse(source).descriptor,{id:'reception-settings-test'}).content.replace(/from ['"]vue['"]/g,`from '${vueUrl}'`).replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`).replace(/from ['"]\.\.\/lib\/reception.js['"]/g,`from '${receptionUrl}'`);
 const component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;
 let v;const setup=component.setup;component.setup=(props,context)=>{v=setup(props,context);return ()=>null;};
 const props=reactive({companyId:1}),renderer=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null}),app=renderer.createApp(component,props);app.mount({});
 const preferences={version:0,nfe_environment:'homologation',nfse_environment:'restricted_production'},credential={configured:false,version:0,environments:{},allow_adn_procuration:false};
 try{
  pending.shift().resolve({preferences,credential,can_edit:true});await tick();assert.equal(v.dirty.value,false);assert.deepEqual(v.enabled.value,{nfe_distribution:[],nfse_adn:[]});
  v.preferences.value.nfse_environment='production';v.enabled.value.nfse_adn=['restricted_production'];v.file.value=new File(['SYNTHETIC-NOT-A-CERTIFICATE'],'SYNTHETIC.P12');v.password.value='SYNTHETIC-PASSWORD';
  const first=v.save(),form=calls.at(-1).options.body;assert.equal(calls.at(-1).options.method,'POST');assert.equal(v.password.value,'');assert.equal(v.file.value,null);assert.equal(JSON.parse(form.get('options')).version,0);
  const stored={...credential,configured:true,version:1,environments:{nfse_adn:['restricted_production']},holder_cnpj:'SYNTHETIC'};
  pending.shift().resolve(stored);await tick();assert.match(calls.at(-1).url,/reception-settings$/);pending.shift().reject(new Error('Versão alterada. Recarregue.'));await first;
  assert.equal(v.data.value.credential.version,1);assert.equal(v.dirty.value,true);assert.equal(form.get('password'),null);assert.equal(form.get('certificate'),null);assert.match(v.error.value,/Versão/);
  const count=calls.length,retry=v.save();assert.equal(calls.length,count+1);assert.match(calls.at(-1).url,/reception-settings$/);pending.shift().resolve({...preferences,nfse_environment:'production',version:1});await retry;assert.equal(v.dirty.value,false);
  v.enabled.value.nfse_adn.push('production');const update=v.save();assert.equal(calls.at(-1).options.method,'PUT');assert.equal(calls.at(-1).options.body.version,1);assert.match(calls.at(-1).url,/reception-credential$/);
  pending.shift().resolve({...stored,version:2,environments:{nfse_adn:['restricted_production','production']}});await tick();pending.shift().resolve({...v.preferences.value,version:2});await update;assert.equal(v.data.value.credential.version,2);assert.equal(v.dirty.value,false);
  const loading=v.load();pending.shift().resolve({preferences,credential,can_edit:false});await loading;v.preferences.value.nfse_environment='production';const deniedCount=calls.length;await v.save();assert.equal(calls.length,deniedCount);
 }finally{app.unmount();delete globalThis.__receptionSettingsTest;}
});
