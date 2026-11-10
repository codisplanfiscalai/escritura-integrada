import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createRenderer,reactive,ref} from 'vue';

test('edição de documento com títulos envia somente alterações normalizadas e versão',async()=>{
 const requests=[],state=reactive({companyId:1,period:'2026-09',module:'fiscal'});
 globalThis.__documentEditTest={state,company:ref({name:'Empresa sintética'}),api:async(url,options)=>{requests.push({url,options});return {};},scope:url=>`/companies/1${url}`,useResource:()=>({data:ref({documents:[]}),loading:ref(false),error:ref('')}),rows:x=>x,notify:()=>{},ask:async()=>true,changed:()=>{},can:()=>true,allowedApi:()=>{},writable:()=>true,navigate:()=>{}};
 const oldDocument=globalThis.document;globalThis.document={getElementById:()=>({checkValidity:()=>true,reportValidity:()=>true})};
 const mock=`data:text/javascript;base64,${Buffer.from('export const {state,company,api,scope,useResource,rows,notify,ask,changed,can,allowedApi,writable,navigate}=globalThis.__documentEditTest;').toString('base64')}`;
 const source=await readFile(new URL('../src/views/DocumentsView.vue',import.meta.url),'utf8');
 const {descriptor}=parse(source),require=createRequire(import.meta.url),vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
 let code=compileScript(descriptor,{id:'document-edit-test'}).content.replace(/from ['"]vue['"]/g,`from '${vueUrl}'`).replace(/import (\w+) from ['"][^'"]+\.vue['"];?/g,'const $1={};').replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`).replace(/from ['"]\.\.\/lib\/(format|entry-focus)['"]/g,(_,name)=>`from '${new URL(`../src/lib/${name}.js`,import.meta.url).href}'`);
 const component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;
 let view;const setup=component.setup;component.setup=(props,ctx)=>{view=setup(props,ctx);return ()=>null;};
 const app=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null}).createApp(component);app.mount({});
 const original={id:51,version:4,status:'booked',period:'2026-09',direction:'incoming',model:'55',number:'SYN-1',series:'1',issue_date:'2026-08-30',posting_date:'2026-09-01',receipt_date:null,partner_name:'Fornecedor sintético',partner_tax_id:'',key:'',cfop:'1102',total_cents:10000,taxes:{icms:'0.00',source_detail:{declared:true}},items:[{number:'1',description:'Item sintético',total:'100.00',cfop:'1102',source:{file:'synthetic.xml'}}],source_hash:'synthetic-hash',import_posting:{eligible:true},financial_posting:{title_ids:[700]},invoices:[{number:'001',amount:'100.00'}],posting_lines:[{document_total:'100.00'}],created_at:'2026-09-01'};
 try{
  view.open(original);view.form.value.receipt_date='2026-09-02';view.form.value.edit_reason='Confirmar chegada';await view.save();assert.equal(requests.at(-1).options.method,'PUT');assert.deepEqual(requests.at(-1).options.body,{receipt_date:'2026-09-02',version:4,reason:'Confirmar chegada'});
  view.open(original);Object.assign(view.form.value,{receipt_date:'2026-09-02',posting_date:'2026-09-02',cfop:'1556',edit_reason:'Revisão da classificação'});await view.save();assert.deepEqual(requests.at(-1).options.body,{receipt_date:'2026-09-02',posting_date:'2026-09-02',cfop:'1556',version:4,reason:'Revisão da classificação'});
  view.open(original);view.form.value.total='100.0';view.form.value.taxes.icms='0,00';view.form.value.receipt_date='';assert.deepEqual(view.documentSavePayload(),{version:4,reason:''},'valores equivalentes não são alterações');
  view.form.value.total='120,00';view.form.value.partner_name='Outro fornecedor sintético';view.form.value.taxes.icms='1,00';view.form.value.items[0].total='120.00';const economic=view.documentSavePayload();assert.equal(economic.total,'120.00');assert.equal(economic.partner_name,'Outro fornecedor sintético');assert.equal(economic.taxes.icms,'1.00');assert.equal(economic.items[0].total,'120.00');assert.equal(economic.source_hash,undefined);assert.equal(original.items[0].total,'100.00');
  view.open({...original,receipt_date:'2026-09-02'});view.form.value.receipt_date='';assert.equal(view.documentSavePayload().receipt_date,null,'limpeza explícita da entrada deve ser transmitida');
  view.open();Object.assign(view.form.value,{number:'SYN-NEW',partner_name:'Fornecedor sintético',total:'10,00'});const creation=view.documentSavePayload();assert.equal(creation.total,'10.00');assert.ok(creation.idempotency_key);assert.equal(creation.version,undefined);assert.equal(creation.edit_reason,undefined);await view.save();assert.equal(requests.at(-1).options.method,'POST');
 }finally{app.unmount();globalThis.document=oldDocument;delete globalThis.__documentEditTest;}
});
