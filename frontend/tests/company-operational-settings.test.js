import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createRenderer,reactive,nextTick} from 'vue';
const require=createRequire(import.meta.url),vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
test('parâmetros por empresa salvam versão, padrão e modelos sem perder edições em conflito',async()=>{
 const calls=[],pending=[],questions=[];let answer=true;
 const defaults={block_imports:false,limit_import_size:false,import_size_mb:20};
 const data={settings:{...defaults},defaults,version:0,fields:[{key:'block_imports',type:'boolean',label:'Bloquear importações'},{key:'limit_import_size',type:'boolean',label:'Limitar tamanho'},{key:'import_size_mb',type:'integer',label:'Tamanho',min:1,max:128}],templates:[{id:'unrestricted',name:'Sem restrições operacionais',settings:{...defaults}}]};
 const state=reactive({session:{user:{role:'admin'}}});
 globalThis.__operationalTest={state,can:()=>true,api:(url,options)=>{calls.push({url,options});return new Promise((resolve,reject)=>pending.push({resolve,reject}));},ask:async q=>{questions.push(q);return answer;},notify:()=>{},changed:()=>{}};
 const mock=`data:text/javascript;base64,${Buffer.from('export const {api,ask,notify,changed,can,state}=globalThis.__operationalTest;').toString('base64')}`;
 const source=await readFile(new URL('../src/components/CompanyOperationalSettings.vue',import.meta.url),'utf8');
 const {descriptor}=parse(source);
 let code=compileScript(descriptor,{id:'operational-test'}).content.replace(/from ['"]vue['"]/g,`from '${vueUrl}'`).replace(/import (\w+) from ['"][^'"]+\.vue['"];?/g,'const $1={render:()=>null};').replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`);
 const component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;
 let v;const setup=component.setup;component.setup=(props,context)=>{v=setup(props,context);return ()=>null;};
 const props=reactive({companyId:1});const renderer=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null}),app=renderer.createApp(component,props);app.mount({});
 try{
  pending.shift().resolve(data);await nextTick();await nextTick();assert.equal(v.enabledCount.value,0);assert.equal(v.dirty.value,false);
  v.settings.value.block_imports=true;await nextTick();assert.equal(v.dirty.value,true);assert.equal(v.enabledCount.value,1);
  const saving=v.save();assert.deepEqual(calls.at(-1).options.body,{settings:{...defaults,block_imports:true},version:0});pending.shift().reject(new Error('Versão alterada. Recarregue.'));await saving;assert.equal(v.dirty.value,true);assert.equal(v.settings.value.block_imports,true);
  const retry=v.save();pending.shift().resolve({...data,settings:{...defaults,block_imports:true},version:1});await retry;assert.equal(v.dirty.value,false);assert.equal(v.payload.value.version,1);
  v.restoreDefaults();assert.equal(v.settings.value.block_imports,false);assert.equal(v.dirty.value,true);
  answer=false;const before=calls.length;await v.applyTemplate();assert.equal(calls.length,before);assert.match(questions.at(-1).message,/substitui e salva/);
  answer=true;const applying=v.applyTemplate();await nextTick();assert.deepEqual(calls.at(-1).options.body,{template_id:'unrestricted',version:1});pending.shift().resolve({...data,version:2});await applying;assert.equal(v.dirty.value,false);
  v.templateName.value='Rotina';const creating=v.saveTemplate();assert.deepEqual(calls.at(-1).options.body,{name:'Rotina',description:''});pending.shift().resolve({...data,version:2,templates:[...data.templates,{id:1,name:'Rotina'}]});await creating;assert.equal(v.payload.value.templates.length,2);
  v.settings.value.import_size_mb=0;const count=calls.length;await v.save();assert.equal(calls.length,count);assert.match(v.error.value,/Confira o valor/);
  state.session.user.role='viewer';v.restoreDefaults();assert.equal(v.settings.value.import_size_mb,0);await v.save();assert.equal(calls.length,count);
 }finally{app.unmount();delete globalThis.__operationalTest;}
});
