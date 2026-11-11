import test from 'node:test';
import assert from 'node:assert/strict';
import {reportLabel,formatReportValue,reportColumns,reportSummarySections,reportReviewSummary,reportDetailSections,reviewMessage,reportOrigins} from '../src/lib/report-presentation.js';
const sample=()=>({kind:'fiscal-outputs',row_scope:'analytical_posting_lines',totals:{documents:4,lines:5,total_cents:706900,document_total_cents:706900,total_informed_lines:5,book_base_cents:null,book_base_informed_lines:0,book_icms_cents:null,book_icms_informed_lines:0,book_other_cents:null,book_other_informed_lines:0,book_ipi_cents:null,book_ipi_informed_lines:0,declared_icms_cents:47573,declared_icms_informed_lines:5,lines_with_pending:5},rows:Array.from({length:5},(_,i)=>({document_id:i<2?1:i,document:String(100+i),date:'2026-09-01',series:'3',partner_name:'Participante sintético',cfop:'6202',total_cents:i===0?100000:151725,book_icms_cents:null,treatment:{},pending:['FISCAL_TREATMENT_REQUIRED'],declared_taxes:{icms:'95.14'},declared_classifications:[{cfop:'6202',rate:'7'}]}))});
test('quatro documentos e cinco linhas distinguem escrituração de revisão tributária',()=>{
 const result=sample(),before=structuredClone(result),review=reportReviewSummary(result);
 assert.equal(review.lines,5);assert.equal(review.documents,4);assert.equal(review.issues.length,1);
 assert.match(review.issues[0].message,/Tratamento fiscal do livro não definido/);
 assert.match(review.issues[0].next_step,/perfil de escrituração/);
 const sections=reportSummarySections(result);assert.equal(sections.length,3);
 assert.equal(sections[0].items.find(x=>x.key==='documents').value,'4');
 assert.equal(sections[0].items.find(x=>x.key==='lines').value,'5');
 assert.equal(sections[0].items.find(x=>x.key==='total_cents').label,'Valor contábil selecionado');
 assert.equal(sections[1].items.find(x=>x.key==='book_icms_cents').label,'ICMS debitado no livro');
 assert.equal(sections[1].items.find(x=>x.key==='book_icms_cents').value,'Não informado');
 assert.equal(sections[1].items.find(x=>x.key==='book_icms_cents').detail,'0 de 5 linhas informadas');
 assert.deepEqual(result,before);
});
test('colunas operacionais omitem chaves e objetos técnicos sem perder a origem',()=>{
 const result=sample(),columns=reportColumns(result);
 assert.ok(columns.includes('document_id'));assert.ok(columns.includes('pending'));
 for(const key of ['treatment','declared_classifications','declared_taxes','source_kind','declared_tax_coverage'])assert.equal(columns.includes(key),false);
 for(const key of columns)assert.notEqual(reportLabel(key),key);
});
test('ausente não vira zero e cobertura parcial fica identificada',()=>{
 const result=sample();result.totals.book_icms_cents=0;result.totals.book_icms_informed_lines=3;
 const item=reportSummarySections(result)[1].items.find(i=>i.key==='book_icms_cents');
 assert.match(item.value,/0,00/);assert.match(item.detail,/3 de 5.*parcial/);
 assert.equal(formatReportValue('book_icms_cents',null),'Não informado');
 assert.equal(formatReportValue('rate',null),'Não informado');
 assert.equal(formatReportValue('rate','0'),'0');
});
test('objetos e arrays não são convertidos em Object nem expostos como JSON',()=>{
 for(const key of ['declared_taxes','unknown','book_base_cents'])assert.equal(formatReportValue(key,{a:1}),'Ver detalhes');
 assert.equal(formatReportValue('declared_classifications',[{cfop:'1102'}]),'1 registros · ver detalhes');
 assert.equal(formatReportValue('item_numbers',['1','2']),'1, 2');
 const text=reportDetailSections(sample().rows[0]).flatMap(s=>s.items.map(i=>i.value)).join(' ');
 assert.doesNotMatch(text,/\[object Object\]|\{"/);assert.match(text,/ICMS|95,14/);
 assert.ok(reportDetailSections(sample().rows[0]).some(s=>s.title==='Valores e classificações declarados'));
});
test('tratamento explícito e cancelamento textual são legíveis sem inventar dados',()=>{
 assert.match(formatReportValue('treatment',{book_mode:'other_excluding_ipi'}),/Outras.*sem crédito/);
 assert.equal(formatReportValue('document_state','cancelled'),'Cancelado conforme livro validado');
 assert.match(formatReportValue('treatment','Cancelada conforme livro validado'),/Cancelada/);
 assert.equal(formatReportValue('model','55'),'NF-e');
 assert.equal(reportReviewSummary({rows:[{document_id:1,pending:[]}]}).lines,0);
});
test('críticas conhecidas e desconhecidas têm instrução operacional',()=>{
 assert.match(reviewMessage('DECLARED_ICMS_BASE_INCOMPLETE').message,/base do ICMS.*incompleta/);
 assert.match(reviewMessage('UNKNOWN_FUTURE_CODE').message,/não reconhecida/);
 assert.doesNotMatch(formatReportValue('pending',['UNKNOWN_FUTURE_CODE']),/UNKNOWN_FUTURE_CODE/);
});
test('demais consultas permanecem com valores e dados acessíveis',()=>{
 const financial={kind:'financial',rows:[{title_id:1,amount_cents:10000,balance_cents:5000,due_date:'2026-10-01',status:'partial'}],totals:{total_cents:10000}};
 assert.ok(reportColumns(financial).includes('due_date'));
 assert.equal(reportSummarySections(financial)[0].items[0].label,'Valor total');
 assert.equal(formatReportValue('amount_cents',10000).includes('100,00'),true);
 assert.match(formatReportValue('status','partial'),/Parcial/);
});

test('espécie, cancelamento e vínculos de origem não se perdem na grade operacional',()=>{
 const result=sample();result.rows[0].model='55';result.rows[0].document_state='cancelled';
 const columns=reportColumns(result);assert.ok(columns.includes('model'));assert.ok(columns.includes('document_state'));
 assert.match(formatReportValue('document_state','cancelled'),/Cancelado conforme livro/);
 assert.equal(formatReportValue('document_state',''),'Sem cancelamento registrado');
 assert.deepEqual(reportOrigins({journal_ids:[4,7],document_ids:[8]}),[{key:'journal_id',id:4,label:'Lançamento #4'},{key:'journal_id',id:7,label:'Lançamento #7'},{key:'document_id',id:8,label:'Documento #8'}]);
 assert.ok(reportColumns({kind:'partners',rows:[{title_id:1,due_date:'2026-10-01',status:'partial'}]}).includes('due_date'));
 assert.ok(reportColumns({kind:'cash-flow',rows:[{title_id:1,settlement_id:4,cash_cents:-100}]}).includes('title_id'));
});
