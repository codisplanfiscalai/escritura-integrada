import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {createSSRApp} from 'vue';
import {renderToString} from '@vue/server-renderer';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createDockerUpdates,updateState,updateAvailability} from '../src/lib/docker-updates.js';
const installed={version:'0.9.0-dev.17',container_id:'a',image_id:'b',configuration_hash:'c',configured_channel:'develop',digest:'sha256:fixture',uid_gid:'10001:10001'};
const status=()=>({configured:true,preparation_supported:true,installed:{...installed},jobs:[]});
const plan=()=>({id:'a'.repeat(32),channel:'develop',installed:{...installed},target:{version:'0.9.0-dev.18',image_id:'d',digest:'sha256:fixture-target'}});
const model=()=>({busy:false,confirming:false,error:'',diagnostic:'',statusError:false,status:status(),plan:null,intent:null,job:null});
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const infrastructure=/docker|\bimagem\b|digest|container|develop|latest|\bUID\b|\bGID\b|executor|rollback|\bcanal\b|socket|\bhost\b|cutover/i;
test('consulta nunca escolhe nem transmite canal, inclusive nos dois tipos de instalação',async()=>{
 for(const channel of ['develop','latest']){
  const m=model(),calls=[];m.status.installed.configured_channel=channel;
  const c=createDockerUpdates(m,async(path,options)=>{calls.push([path,options]);return {...plan(),channel};});
  assert.equal(c.channel,undefined);await c.check();
  assert.deepEqual(calls,[['/docker-updates/check',{method:'POST',body:{}}]]);assert.equal(m.plan.channel,channel);
 }
});
test('indisponibilidade e serviço antigo sem contrato não geram seleção implícita ou pedido',async()=>{
 for(const value of [null,{configured:false},{configured:true,installed}, {...status(),preparation_supported:false}]){
  const m=model();m.status=value;let calls=0;const c=createDockerUpdates(m,async()=>{calls++;});await c.check();await c.prepare();assert.equal(calls,0);
  assert.ok(updateAvailability(value));assert.doesNotMatch(updateAvailability(value),infrastructure);
 }
});
test('cliques simultâneos e resposta incerta conservam a intenção sem expor mensagem técnica',async()=>{
 const m=model(),pending=deferred(),calls=[];let attempt=0;
 const c=createDockerUpdates(m,async(path,options)=>{if(path.endsWith('check'))return plan();calls.push(options.body);if(++attempt===1)return pending.promise;return {id:'c'.repeat(32),state:'queued',application_updated:false};},()=> 'b'.repeat(32));
 await c.check();const first=c.prepare();await c.prepare();assert.equal(calls.length,1);pending.reject(new Error('Docker digest executor indisponível'));await first;
 assert.doesNotMatch(m.error,infrastructure);assert.match(m.diagnostic,/Docker/);assert.equal(m.job,null);await c.prepare();assert.deepEqual(calls[0],calls[1]);assert.equal(m.job.application_updated,false);
});
test('confirmação informa efeito real; cancelar e cliques durante diálogo não baixam',async()=>{
 const m=model(),pending=deferred(),calls=[],prompts=[];
 const c=createDockerUpdates(m,async(path,options)=>{calls.push([path,options]);return path.endsWith('check')?plan():status();});await c.check();
 const first=c.confirmDownload(options=>{prompts.push(options);return pending.promise;});await c.confirmDownload(()=>true);
 assert.equal(prompts.length,1);assert.doesNotMatch(JSON.stringify(prompts),infrastructure);assert.match(prompts[0].message,/somente o download/);pending.resolve(false);await first;assert.equal(calls.length,1);
});
test('confirmação aceita cria uma solicitação e progresso após reload nunca anuncia aplicação atualizada',async()=>{
 const m=model(),calls=[],job={id:'c'.repeat(32),state:'queued',target:plan().target,channel:'develop',application_updated:false};
 const c=createDockerUpdates(m,async(path,options)=>{calls.push([path,options]);return path.endsWith('check')?plan():path.endsWith('prepare')?job:{...status(),jobs:[job]};});
 await c.check();await c.confirmDownload(()=>true);assert.equal(calls.filter(([p])=>p.endsWith('prepare')).length,1);
 job.state='prepared';await c.status();assert.match(updateState(m.status.jobs[0].state),/versão em uso ainda não foi alterada/);
 const reload=model();const d=createDockerUpdates(reload,async()=>({...status(),jobs:[job]}));await d.status();assert.equal(reload.status.jobs[0].id,job.id);
 await c.check();assert.equal(calls.filter(([p])=>p.endsWith('check')).length,2,'terminal job does not leave stale queued state blocking next check');
});
test('sair da tela ou mudar configuração durante a confirmação invalida o alvo anterior',async()=>{
 for(const leave of [true,false]){
  const m=model(),pending=deferred(),calls=[];const c=createDockerUpdates(m,async(path)=>{calls.push(path);return path.endsWith('check')?plan():{...status(),installed:{...installed,configured_channel:'latest',configuration_hash:'changed'}};});await c.check();const first=c.confirmDownload(()=>pending.promise);
  if(leave){c.pause();c.resume();}else{m.plan=null;m.intent=null;}pending.resolve(true);await first;assert.equal(calls.length,1);
 }
 const m=model();let changed=false;const c=createDockerUpdates(m,async path=>path.endsWith('check')?plan():{...status(),installed:{...installed,configuration_hash:changed?'changed':'c'}});await c.check();changed=true;await c.status();assert.equal(m.plan,null);assert.equal(m.intent,null);
});
test('consulta nova que falha invalida versão anterior; falha de andamento não autoriza novas ações',async()=>{
 const m=model();let fail=false;const c=createDockerUpdates(m,async path=>{if(fail)throw Error('Docker: erro técnico');return path.endsWith('check')?plan():status();});await c.check();fail=true;await c.check();assert.equal(m.plan,null);assert.equal(m.intent,null);await c.status();assert.equal(m.statusError,true);assert.doesNotMatch(m.error,infrastructure);
});
test('respostas antigas após sair da tela não alteram dados nem ocupação atuais',async()=>{
 const m=model(),pending=deferred();let count=0;const c=createDockerUpdates(m,async()=>++count===1?pending.promise:{configured:false});const first=c.status();c.pause();c.resume();await c.status();pending.resolve(status());await first;assert.equal(m.status.configured,false);assert.equal(m.busy,false);
});
test('geração de chave conserva helper em HTTP sem randomUUID',async()=>{
 const original=Object.getOwnPropertyDescriptor(globalThis,'crypto');try{Object.defineProperty(globalThis,'crypto',{configurable:true,value:{getRandomValues:bytes=>{bytes.fill(5);return bytes;}}});const m=model(),c=createDockerUpdates(m,async()=>plan());await c.check();assert.match(m.intent.idempotency_key,/^[a-f0-9]{32}$/);}finally{if(original)Object.defineProperty(globalThis,'crypto',original);else delete globalThis.crypto;}
});
test('fluxo renderizado tem versões, estados simples, diagnóstico recolhido e nenhum seletor',async()=>{
 const file=new URL('../src/views/DockerUpdatesView.vue',import.meta.url),{descriptor}=parse(await readFile(file,'utf8'));
 const compiled=compileScript(descriptor,{id:'update-ux',inlineTemplate:true}),require=createRequire(import.meta.url),vue=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
 const helper=new URL('../src/lib/docker-updates.js',import.meta.url).href;
 for(const state of ['queued','pulling','validating','prepared','failed','interrupted']){
  const fixture={...model(),status:{...status(),application_version:'0.9.0-dev.99',jobs:[{id:'x',channel:'develop',state,target:plan().target,error:'Docker digest interrompido'}]},plan:plan(),diagnostic:'Executor socket indisponível'};
  const code=compiled.content.replace(/from ['"]vue['"]/g,`from ${JSON.stringify(vue)}`).replace(/import \{api,ask\} from ['"]\.\.\/lib\/workspace['"];?/, 'const api=()=>{},ask=()=>{};').replace(/from ['"]\.\.\/lib\/docker-updates.js['"]/g,`from ${JSON.stringify(helper)}`).replace('const controller=createDockerUpdates(m,api);',`Object.assign(m,${JSON.stringify(fixture)});const controller=createDockerUpdates(m,api);`);
  const component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;
  const html=await renderToString(createSSRApp(component)),common=html.replace(/<details\b[\s\S]*?<\/details>/g,'');
  assert.doesNotMatch(html,/<select\b|<details[^>]*\bopen\b/);assert.match(html,/Diagnóstico administrativo/);assert.doesNotMatch(common,infrastructure);assert.match(common,/Atualização da aplicação/);assert.match(common,/0.9.0-dev.18/);assert.match(common,/0.9.0-dev.17/);assert.doesNotMatch(common,/0.9.0-dev.99/);assert.match(common,/cópia de segurança/);assert.match(common,/Não há retorno automático/);
 }
 const app=await readFile(new URL('../src/App.vue',import.meta.url),'utf8');assert.match(app,/id:'docker-updates',label:'Atualização da aplicação'.*admin:true/);
});
