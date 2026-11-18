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
 let code=compileScript(parse(source).descriptor,{id:'reception-settings-test'}).content.replace(/import ReceptionAutomationSettings from [^;]+;/,'const ReceptionAutomationSettings={};').replace(/from ['"]vue['"]/g,`from '${vueUrl}'`).replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`).replace(/from ['"]\.\.\/lib\/reception.js['"]/g,`from '${receptionUrl}'`);
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

test('NSU por ambiente acompanha estado salvo, confirma ajuste e preserva rascunhos independentes',async()=>{
 const calls=[],pending=[];globalThis.__manualCursorTest={api:(url,options)=>{calls.push({url,options});return new Promise((resolve,reject)=>pending.push({resolve,reject}));},notify:()=>{},changed:()=>{}};
 const mock=`data:text/javascript;base64,${Buffer.from('export const {api,notify,changed}=globalThis.__manualCursorTest;').toString('base64')}`;
 const receptionUrl=new URL('../src/lib/reception.js',import.meta.url).href;
 const source=await readFile(new URL('../src/components/CompanyReceptionSettings.vue',import.meta.url),'utf8');
 let code=compileScript(parse(source).descriptor,{id:'manual-cursor-test'}).content.replace(/import ReceptionAutomationSettings from [^;]+;/,'const ReceptionAutomationSettings={};').replace(/from ['"]vue['"]/g,`from '${vueUrl}'`).replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`).replace(/from ['"]\.\.\/lib\/reception.js['"]/g,`from '${receptionUrl}'`);
 const component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;
 let v;const setup=component.setup;component.setup=(props,context)=>{v=setup(props,context);return ()=>null;};
 const props=reactive({companyId:1}),renderer=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null}),app=renderer.createApp(component,props);app.mount({});
 const preferences={version:0,nfe_environment:'homologation',nfse_environment:'restricted_production'},credential={configured:false,version:0,environments:{},allow_adn_procuration:false};
 const snap=(cursor='000000000000002')=>({cursor,revision:'revision-'+cursor,busy:false,next_allowed_at:100});
 const cursors={nfe_distribution:{production:snap(),homologation:snap()},nfse_adn:{production:snap('9007199254740993'),restricted_production:snap()}};
 try{
  pending.shift().resolve({preferences,credential,cursors,can_edit:true});await tick();
  assert.equal(v.cursorValues.value['nfse_adn:production'],'9007199254740993');assert.equal(v.dirty.value,false);
  v.cursorValues.value['nfe_distribution:production']='123';assert.equal(v.dirty.value,true);assert.equal(v.settingsDirty.value,false);
  const before=calls.length;await v.saveCursor('nfe_distribution','production');assert.equal(calls.length,before);
  v.cursorConfirmed.value['nfe_distribution:production']=true;const saving=v.saveCursor('nfe_distribution','production');
  assert.deepEqual(calls.at(-1).options.body,{provider:'nfe_distribution',environment:'production',cursor:'123',expected_revision:'revision-000000000000002',confirmed:true});
  pending.shift().resolve(snap('000000000000123'));await saving;assert.equal(v.dirty.value,false);assert.equal(v.cursorConfirmed.value['nfe_distribution:production'],false);
  v.cursorValues.value['nfse_adn:production']='9223372036854775808';v.cursorConfirmed.value['nfse_adn:production']=true;
  const count=calls.length;await v.saveCursor('nfse_adn','production');assert.equal(calls.length,count);assert.match(v.error.value,/NSU inválido/);
  v.cursorValues.value['nfse_adn:production']='12';v.preferences.value.nfe_environment='production';
  const prefs=v.save();pending.shift().resolve({...preferences,nfe_environment:'production',version:1});await prefs;
  assert.equal(v.cursorValues.value['nfse_adn:production'],'12');assert.equal(v.dirty.value,true);
  const stale=v.saveCursor('nfse_adn','production');pending.shift().reject(new Error('NSU atualizado. Recarregue.'));await stale;
  assert.equal(v.cursorValues.value['nfse_adn:production'],'12');assert.match(v.error.value,/Recarregue/);
  const loading=v.load();pending.shift().resolve({preferences,credential,cursors:{...cursors,nfse_adn:{...cursors.nfse_adn,production:snap('9007199254740994')}},can_edit:true});await loading;
  assert.equal(v.cursorValues.value['nfse_adn:production'],'9007199254740994');assert.equal(v.dirty.value,false);
 }finally{app.unmount();delete globalThis.__manualCursorTest;}
});
