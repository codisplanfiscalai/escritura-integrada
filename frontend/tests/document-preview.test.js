import test from 'node:test';
import assert from 'node:assert/strict';
import {createPdfRequest,auxiliaryLabel} from '../src/lib/document-preview.js';
const pdf = () => new Response('%PDF-synthetic',{headers:{'Content-Type':'application/pdf'}});
test('late response cannot replace another document/company',async()=>{
 const pending=[];const loader=createPdfRequest((url,options)=>new Promise(resolve=>pending.push({url,options,resolve})));
 const a=loader.load('/companies/1/documents/1');const b=loader.load('/companies/2/documents/2');
 assert.equal(pending[0].options.signal.aborted,true);
 pending[1].resolve(pdf());assert.ok(await b instanceof Uint8Array);
 pending[0].resolve(pdf());assert.equal(await a,null);
});
test('close cancels pending data and ignores stale errors',async()=>{
 let reject;const loader=createPdfRequest(()=>new Promise((_,r)=>reject=r));const result=loader.load('/source');loader.cancel();reject(new Error('late'));assert.equal(await result,null);
});
test('server diagnostic and non-PDF response are visible failures',async()=>{
 const loader=createPdfRequest(async()=>new Response(JSON.stringify({detail:'XML indisponível'}),{status:422}));
 await assert.rejects(loader.load('/source'),/XML indisponível/);
 await assert.rejects(createPdfRequest(async()=>new Response('<html>login</html>',{headers:{'content-type':'text/html'}})).load('/source'),/PDF válido/);
});
test('labels never present an unsupported model as an official auxiliary',()=>{
 assert.equal(auxiliaryLabel('55'),'DANFE');assert.equal(auxiliaryLabel('65'),'DANFC-e');assert.equal(auxiliaryLabel('57'),'DACTE');assert.equal(auxiliaryLabel('67'),'Documento auxiliar');
});
