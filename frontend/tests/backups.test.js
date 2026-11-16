import test from 'node:test';
import assert from 'node:assert/strict';
import {createBackups} from '../src/lib/backups.js';
const model=()=>({busy:false,error:'',config:{},status:null,intent:null});
test('double click and ambiguous failure preserve intent',async()=>{
 const m=model(),calls=[];let reject;
 const pending=new Promise((_,no)=>reject=no);
 const c=createBackups(m,async(p,o)=>{calls.push(o.body);if(calls.length===1)return pending;return {id:'ok'};},()=> 'a'.repeat(32));
 const first=c.run();await c.run();assert.equal(calls.length,1);
 reject(new Error('offline'));await first;assert.ok(m.intent);
 await c.run();assert.deepEqual(calls[0],calls[1]);assert.equal(m.intent,null);
});
test('pause discards late status and restore never sends arbitrary filesystem path',async()=>{
 const m=model();let resolve;const c=createBackups(m,()=>new Promise(yes=>resolve=yes));
 const request=c.status();c.pause();resolve({jobs:[{id:1}]});await request;assert.equal(m.status,null);
 const calls=[];const next=createBackups(m,async(p,o)=>{calls.push([p,o]);return {directory:'isolated'};});
 await next.restore('a'.repeat(32));assert.deepEqual(calls[0],[`/backups/${'a'.repeat(32)}/restore`,{method:'POST',body:{}}]);assert.equal(m.restored,'isolated');
});
test('cancel only addresses one job and save keeps secrets out of payload',async()=>{
 const m=model();m.config={credential_ref:'ESCRITURA_BACKUP_FIXTURE'};const calls=[];
 const c=createBackups(m,async(p,o)=>{calls.push([p,o]);return {jobs:[]};});
 await c.save();await c.cancel('id');assert.deepEqual(calls[0][1].body,m.config);assert.equal(calls[1][0],'/backups/id/cancel');
});
