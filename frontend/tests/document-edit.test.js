import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createRenderer,reactive,ref} from 'vue';

test('edição de documento com títulos envia somente alterações normalizadas e versão',async()=>{
 const requests=[],questions=[];let answer=true,afterAsk=()=>{};const state=reactive({companyId:1,period:'2026-09',module:'fiscal'});
 globalThis.__documentEditTest={state,company:ref({name:'Empresa sintética'}),api:async(url,options)=>{requests.push({url,options});return {};},scope:url=>`/companies/1${url}`,useResource:()=>({data:ref({documents:[]}),loading:ref(false),error:ref('')}),rows:x=>x,notify:()=>{},ask:async options=>{questions.push(options);afterAsk();return answer;},changed:()=>{},can:()=>true,allowedApi:()=>{},writable:()=>true,navigate:()=>{}};
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
  view.open();view.chooseCancellation(true);Object.assign(view.form.value,{number:'SYN-CANCEL',partner_name:'Participante sintético',total:'900,00',items:[{total:'900.00'}],taxes:{icms:'90.00'}});Object.assign(view.form.value.book_cancellation,{source:'Livro sintético, página 1',responsible:'Revisor sintético',reason:'Cancelada no período validado'});
  const cancelledPayload=view.documentSavePayload();assert.equal(cancelledPayload.total,'0.00');assert.deepEqual(cancelledPayload.items,[]);assert.deepEqual(cancelledPayload.taxes,{});assert.equal(cancelledPayload.book_cancellation.source,'Livro sintético, página 1');
  view.chooseCancellation(false);assert.equal(view.documentSavePayload().book_cancellation,undefined);view.chooseCancellation(true);await view.close();view.open();assert.equal(view.form.value.book_cancellation,undefined,'nova inclusão não herda cancelamento');
  const cancelled={...original,document_state:'cancelled',total_cents:0,book_cancellation:cancelledPayload.book_cancellation};view.open(cancelled);assert.equal(view.locked.value,true);const beforeSave=requests.length;await view.save();assert.equal(requests.length,beforeSave,'registro cancelado não pode ser editado');view.chooseCancellation(false);assert.ok(view.form.value.book_cancellation,'não converte registro existente');
  view.openBook(cancelled);Object.assign(view.booking.value,{generate_titles:true,integrate:true,model_id:1,reason:'Registro da linha cancelada'});await view.confirmBook();const cancelledBooking=requests.at(-1).options.body;assert.equal(cancelledBooking.generate_titles,false);assert.equal(cancelledBooking.lines,undefined);assert.equal(cancelledBooking.model_id,undefined);assert.equal(cancelledBooking.installments,undefined);
  assert.equal(view.monthFilter.value,'09','consulta começa na competência ativa');
  const pending={...original,id:52,status:'pending',version:1};
  assert.equal(view.canBook(pending),true);
  const promptsBefore=questions.length;await view.review(pending);assert.equal(questions.length,promptsBefore,'conferência simples não repete confirmação');assert.equal(requests.at(-1).options.body.reason,'Conferência registrada pelo operador.');
  view.openBook(pending);assert.equal(view.booking.value.reason,'');await view.confirmBook();assert.equal(requests.at(-1).url,'/companies/1/documents/52/book');assert.equal(requests.at(-1).options.body.reason,'');const afterBook=requests.length;await view.confirmBook();assert.equal(requests.length,afterBook,'segundo envio após concluir é ignorado');
  state.session={operational_settings:{require_extra_confirmations:true,require_separate_document_review:true}};assert.equal(view.canBook(pending),false);assert.equal(view.canBook({...pending,status:'reviewed'}),true);
  answer=false;const beforeCancelled=requests.length;await view.review(pending);assert.equal(requests.length,beforeCancelled);assert.equal(questions.length,promptsBefore+1);
  answer='Revisão detalhada';await view.review(pending);assert.equal(requests.at(-1).options.body.reason,'Revisão detalhada');
  const beforeContext=requests.length;afterAsk=()=>{state.companyId=2};await view.review(pending);assert.equal(requests.length,beforeContext,'mudança de empresa durante pergunta impede gravação');afterAsk=()=>{};state.companyId=1;
  state.session.operational_settings={};view.data.value.documents=[pending,{...original,import_posting:{review_pending:true}}];assert.equal(view.reviewCount.value,2,'distingue revisão pendente de escrituração concluída');
  view.data.value.documents=[original,cancelled];view.status.value='cancelled';assert.equal(view.filtered.value.length,1);assert.equal(view.filtered.value[0].document_state,'cancelled');assert.match(view.exportUrl.value,/status=cancelled/);
 }finally{app.unmount();globalThis.document=oldDocument;delete globalThis.__documentEditTest;}
});
