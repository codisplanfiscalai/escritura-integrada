import test from 'node:test';
import assert from 'node:assert/strict';
import {createDockerUpdates} from '../src/lib/docker-updates.js';
const model=()=>({channel:'develop',busy:false,error:'',status:null,plan:null,intent:null,job:null});
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
test('consulta usa o canal escolhido e nunca envia imagem/comando; troca invalida intenção',async()=>{
 const m=model(),calls=[];
 const c=createDockerUpdates(m,async(path,options)=>{calls.push([path,options]);return {id:'a'.repeat(32),channel:options.body.channel};},()=> 'b'.repeat(32));
 c.channel('latest');await c.check();
 assert.deepEqual(calls[0],['/docker-updates/check',{method:'POST',body:{channel:'latest'}}]);
 assert.equal(m.plan.channel,'latest');assert.equal(m.intent.plan_id,'a'.repeat(32));
 c.channel('develop');assert.equal(m.plan,null);assert.equal(m.intent,null);
});
test('cliques simultâneos enviam uma mutação e falha de transporte repete exatamente a intenção',async()=>{
 const m=model(),pending=deferred(),calls=[];let attempt=0;
 const c=createDockerUpdates(m,async(path,options)=>{if(path.endsWith('check'))return {id:'a'.repeat(32)};calls.push(options.body);if(++attempt===1)return pending.promise;return {id:'c'.repeat(32),state:'queued',application_updated:false};},()=> 'b'.repeat(32));
 await c.check();const first=c.prepare();await c.prepare();
 assert.equal(calls.length,1);pending.reject(new Error('rede indisponível'));await first;
 assert.match(m.error,/rede/);assert.equal(m.job,null);await c.prepare();
 assert.deepEqual(calls[0],calls[1]);assert.equal(m.job.application_updated,false);
});
test('respostas antigas após sair da tela não alteram dados nem ocupação atuais',async()=>{
 const m=model(),pending=deferred();let count=0;
 const c=createDockerUpdates(m,async()=> ++count===1?pending.promise:{configured:false});
 const first=c.status();c.pause();c.resume();await c.status();
 pending.resolve({configured:true,jobs:[{state:'prepared'}]});await first;
 assert.equal(m.status.configured,false);assert.equal(m.busy,false);
});
test('geração de chave conserva o helper existente em HTTP sem randomUUID',async()=>{
 const original=Object.getOwnPropertyDescriptor(globalThis,'crypto');
 try{
  Object.defineProperty(globalThis,'crypto',{configurable:true,value:{getRandomValues:bytes=>{bytes.fill(5);return bytes;}}});
  const m=model(),c=createDockerUpdates(m,async()=>({id:'a'.repeat(32)}));
  await c.check();assert.match(m.intent.idempotency_key,/^[a-f0-9]{32}$/);assert.equal(m.error,'');
 }finally{if(original)Object.defineProperty(globalThis,'crypto',original);else delete globalThis.crypto;}
});
