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

import {createPdfOutput} from '../src/lib/document-pdf-output.js';
test('download and print share exact original PDF; disposal revokes and cancels late print',async()=>{
 const blobs=[],revoked=[],frames=[];let prints=0;
 const doc={body:{appendChild:f=>frames.push(f)},createElement:()=>({style:{},setAttribute(){},remove(){this.removed=true;},contentWindow:{focus(){},print(){prints++;},addEventListener(){}}})};
 const output=createPdfOutput({doc,nav:{pdfViewerEnabled:true},urlApi:{createObjectURL:b=>(blobs.push(b),'blob:synthetic-'+blobs.length),revokeObjectURL:u=>revoked.push(u)}});
 const bytes=new TextEncoder().encode('%PDF-original-synthetic');const source=output.set(bytes);bytes.fill(0);
 assert.equal(await blobs[0].text(),'%PDF-original-synthetic');
 const printing=output.print();assert.equal(frames[0].src,source);frames[0].onload();await printing;assert.equal(prints,1);
 const pending=output.print();const late=frames[1].onload;output.dispose();late();await pending;assert.equal(prints,1);assert.deepEqual(revoked,[source]);assert.ok(frames.every(f=>f.removed));
});
test('print failure and unsupported PDF viewer give actionable diagnostics',async()=>{
 const output=createPdfOutput({nav:{pdfViewerEnabled:false},urlApi:{createObjectURL:()=> 'blob:fixture',revokeObjectURL(){}}});
 await assert.rejects(output.print(),/Aguarde/);output.set(new Uint8Array([1]));await assert.rejects(output.print(),/Baixar PDF/);output.dispose();
 const frames=[];const broken=createPdfOutput({nav:{pdfViewerEnabled:true},urlApi:{createObjectURL:()=> 'blob:fixture',revokeObjectURL(){}},doc:{body:{appendChild:f=>frames.push(f)},createElement:()=>({style:{},setAttribute(){},remove(){},contentWindow:{addEventListener(){},focus(){},print(){throw Error('blocked');}}})}});
 broken.set(new Uint8Array([1]));const result=broken.print();frames[0].onload();await assert.rejects(result,/Baixar PDF/);broken.dispose();
});
test('old afterprint cannot cancel a new document and timeout reports failure',async(t)=>{
 t.mock.timers.enable({apis:['setTimeout']});const frames=[];
 const doc={body:{appendChild:f=>frames.push(f)},createElement:()=>({style:{},setAttribute(){},remove(){this.removed=true;},contentWindow:{focus(){},print(){},addEventListener(_,fn){this.afterprint=fn;}}})};
 const out=createPdfOutput({doc,nav:{pdfViewerEnabled:true},urlApi:{createObjectURL:()=> 'blob:fixture',revokeObjectURL(){}}});
 out.set(new Uint8Array([1]));const a=out.print();frames[0].onload();await a;
 out.set(new Uint8Array([2]));const b=out.print();const failed=assert.rejects(b,/não respondeu/);
 frames[0].contentWindow.afterprint();assert.equal(frames[1].removed,undefined);
 t.mock.timers.tick(15000);await failed;assert.equal(frames[1].removed,true);out.dispose();
});

test('native print never focuses a hidden frame and detaches only after afterprint unwinds',async(t)=>{
 t.mock.timers.enable({apis:['setTimeout']});let focus=0,printed=0;const frames=[];
 const trigger={isConnected:true,focus(){focus++;}};
 const out=createPdfOutput({nav:{pdfViewerEnabled:true},urlApi:{createObjectURL:()=> 'blob:fixture',revokeObjectURL(){}},doc:{activeElement:trigger,body:{appendChild:f=>frames.push(f)},createElement:()=>({style:{},setAttribute(){},remove(){this.removed=true;},contentWindow:{focus(){throw Error('hidden frame stole focus');},print(){printed++;},addEventListener(_,fn){this.afterprint=fn;}}})}});
 out.set(new Uint8Array([1]));const result=out.print();frames[0].onload();await result;assert.equal(printed,1);
 t.mock.timers.tick(0);assert.equal(focus,1);
 frames[0].contentWindow.afterprint();assert.equal(frames[0].removed,undefined);
 t.mock.timers.tick(0);assert.equal(frames[0].removed,true);assert.equal(focus,2);out.dispose();
});
