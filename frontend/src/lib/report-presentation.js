// Apresentação da consulta. Não altera valores, grupos ou decisões tributárias.
import {money,date,statusLabel,taxId} from './format.js';

const labels={document_id:'Origem',journal_id:'Lançamento',title_id:'Título',ledger_id:'Memória',
 document:'Documento',number:'Número',date:'Escrituração',issue_date:'Emissão',series:'Série',model:'Espécie',
 partner_name:'Participante',partner_tax_id:'CPF/CNPJ',partner_state:'UF',partner_ie:'Inscrição estadual',
 cfop:'CFOP',ncm:'NCM',ncms:'NCMs da linha',line:'Linha',cst_icms:'CST ICMS',csosn:'CSOSN',origin:'Origem da mercadoria',
 rate:'Alíquota declarada (%)',total_cents:'Valor contábil da linha',document_total_cents:'Total dos documentos',
 book_base_cents:'Base de ICMS do livro',book_icms_cents:'ICMS do livro',book_other_cents:'Outras do livro',book_ipi_cents:'IPI do livro',
 ipi_allocated_cents:'IPI distribuído na linha',declared_icms_cents:'ICMS declarado',declared_icms_base_cents:'Base de ICMS declarada',
 declared_ipi_cents:'IPI declarado',declared_ipi_base_cents:'Base de IPI declarada',documents:'Documentos',lines:'Linhas do livro',
 lines_with_pending:'Linhas a revisar',documents_with_findings:'Documentos a revisar',occurrences:'Ocorrências',
 item:'Item',item_numbers:'Itens da linha',item_indices:'Itens selecionados',description:'Descrição',quantity:'Quantidade',unit:'Unidade',
 item_total_cents:'Valor dos itens',items:'Itens',items_without_value:'Itens sem valor informado',
 status:'Situação',document_state:'Estado documental',direction:'Operação',kind:'Tipo',pending:'Conferência fiscal',
 treatment:'Tratamento fiscal',book_mode:'Tratamento do livro',source:'Fonte',source_kind:'Origem da linha',
 responsible:'Responsável',reason:'Motivo',code:'Código',message:'Conferência necessária',next_step:'Próximo passo',line_numbers:'Linhas afetadas',
 valid_from:'Vigência inicial',valid_to:'Vigência final',posting_group:'Grupo da escrituração',posting_group_review:'Revisão dos grupos',
 grouping_mode:'Agrupamento',declared_classifications:'Classificações declaradas',declared_taxes:'Tributos declarados',
 declared_tax_coverage:'Cobertura das informações declaradas',declared_tax_partial_totals:'Somas declaradas parciais',
 icms:'ICMS declarado',icms_base:'Base de ICMS declarada',ipi:'IPI declarado',ipi_base:'Base de IPI declarada',
 known:'Itens com informação',expected:'Itens esperados',complete:'Informação completa',sources:'Fontes',
 item_groups:'Relação item e grupo',mode:'Modo',cancellation_source:'Fonte do cancelamento',cancellation_responsible:'Responsável pelo cancelamento',
 cancellation_reason:'Motivo do cancelamento',access_code:'Acesso',classifier:'Classificador',account_name:'Conta',account_id:'Conta',
 history:'Histórico',counterpart:'Contrapartida',cost_center_name:'Centro de custo',cost_center_code:'Código do centro',
 debit_cents:'Débitos',credit_cents:'Créditos',opening_cents:'Saldo anterior',closing_cents:'Saldo final',balance_cents:'Saldo',
 result_cents:'Resultado',report_group:'Grupo contábil',nature:'Natureza',journal_ids:'Lançamentos de origem',
 amount_cents:'Valor original',paid_cents:'Principal baixado',cash_cents:'Valor realizado',due_date:'Vencimento',settlement_id:'Baixa',
 event:'Movimento',consistent:'Conciliação consistente',settlement_ids:'Baixas de origem',bank_ids:'Movimentos bancários',
 assets_cents:'Ativo',liabilities_cents:'Passivo',equity_cents:'Patrimônio líquido',unclosed_result_cents:'Resultado não encerrado',
 difference_cents:'Diferença',document_ids:'Documentos de origem',period:'Competência',tax:'Tributo',assessment_id:'Apuração de origem',
 opening_credit_cents:'Crédito anterior',payable_cents:'A recolher',carry_credit_cents:'Crédito a transportar',finalized_assessments:'Memórias finalizadas'};
const reviewMessages={
 FISCAL_TREATMENT_REQUIRED:['Tratamento fiscal do livro não definido.','Revise o perfil de escrituração do documento antes de concluir os valores fiscais do livro.'],
 INVALID_FISCAL_TREATMENT:['Tratamento fiscal inválido ou fora da vigência.','Confira o perfil, a vigência e a data de escrituração.'],
 DECLARED_ICMS_MISSING:['Base ou ICMS declarado sem informação completa.','Confira o documento de origem. Valor ausente não representa imposto zero.'],
 OTHER_IPI_TREATMENT_REQUIRED:['Tratamento de Outras ou do IPI ainda não definido.','Revise essas parcelas separadamente; a decisão sobre ICMS não define o IPI.'],
 CFOP_REQUIRED:['CFOP da linha não definido.','Confira a natureza da operação e a classificação da linha.'],
 INVALID_POSTING_GROUP_REVIEW:['Agrupamento revisado precisa de nova conferência.','Confira todos os itens e a evidência da divisão ou consolidação, sem forçar valores.'],
 C190_TOTAL_MISMATCH:['Total dos registros analíticos difere do cabeçalho.','Confira a composição dos registros C190 e as parcelas do documento.'],
 HEADER_COMPONENT_ALLOCATED:['Parcela do cabeçalho foi distribuída entre as linhas.','Confira o rateio de frete, desconto e demais componentes na origem.'],
 TOTAL_ALLOCATION_REVIEW:['Composição do valor contábil precisa de conferência.','Confira itens, frete, desconto e demais componentes.'],
 NO_CONTRIBUTING_ITEMS:['Não há itens contribuintes para distribuir o valor.','Confira itens e composição do documento antes de definir o rateio.'],
 NEGATIVE_ALLOCATION_REVIEW:['Uma parcela distribuída ficou negativa.','Confira descontos, componentes e grupos da escrituração.']};
const treatments={other_excluding_ipi:'Outras, sem crédito de ICMS/IPI',declared_icms:'ICMS declarado, conforme decisão revisada'};
const values={automatic:'Agrupamento automático',explicit_review:'Agrupamento revisado',split:'Divisão revisada',consolidate:'Consolidação revisada',
 items:'Itens do documento',header:'Cabeçalho do documento',header_allocated:'Cabeçalho distribuído',analytics:'Registros analíticos',
 debit:'Devedora',credit:'Credora',asset:'Ativo',liability:'Passivo',equity:'Patrimônio líquido',revenue:'Receita',expense:'Despesa'};

export function reportLabel(key,context=null){
 if(key==='total_cents'&&context&&context.row_scope!=='analytical_posting_lines')return 'Valor total';
 if(key==='book_icms_cents'&&context?.kind==='fiscal-entries')return 'ICMS creditado no livro';
 if(key==='book_icms_cents'&&context?.kind==='fiscal-outputs')return 'ICMS debitado no livro';
 if(labels[key])return labels[key];
 const coverage=key.match(/^(.*)_informed_(lines|documents)$/);
 if(coverage)return `${reportLabel(coverage[1]+'_cents')} · ${coverage[2]==='lines'?'linhas':'documentos'} informados`;
 const tax=key.match(/^(icms|ipi|iss|pis|cofins|ibs|cbs)(_base)?_cents$/);
 if(tax)return `${tax[2]?'Base de ':''}${tax[1].toUpperCase()} declarado`;
 return String(key).replaceAll('_',' ').replace(/([a-z])([A-Z])/g,'$1 $2').replace(/^./,x=>x.toUpperCase());
}
export function reviewMessage(code){
 const match=String(code).match(/^DECLARED_(ICMS|ICMS_BASE|IPI|IPI_BASE)_INCOMPLETE$/);
 if(match){const name={ICMS:'ICMS',ICMS_BASE:'base do ICMS',IPI:'IPI',IPI_BASE:'base do IPI'}[match[1]];return {code,message:`Informação declarada de ${name} incompleta.`,next_step:'Confira a cobertura dos itens na origem; a soma conhecida é parcial.'};}
 const [message,next_step]=reviewMessages[code]||['Pendência fiscal não reconhecida; revise o registro.','Abra a origem para conferir a evidência e o código da ocorrência.'];
 return {code,message,next_step};
}
export function formatReportValue(key,value){
 if(key==='document_state'&&(value===null||value===undefined||value===''))return 'Sem cancelamento registrado';
 if(value===null||value===undefined||value==='')return 'Não informado';
 if(key==='pending')return Array.isArray(value)&&value.length?[...new Set(value)].map(c=>reviewMessage(c).message).join(' '):'Sem pendências identificadas';
 if(key==='treatment')return typeof value==='object'&&!Array.isArray(value)?treatments[value.book_mode]||'Tratamento não definido':String(value);
 if(typeof value==='object'&&!Array.isArray(value))return 'Ver detalhes';
 if(key.endsWith('_cents'))return money(value);
 if(['date','valid_from','valid_to'].includes(key)||key.endsWith('_date'))return date(value);
 if(Array.isArray(value))return value.every(v=>v===null||typeof v!=='object')?value.filter(v=>v!==null).join(', ')||'Não informado':`${value.length} registros · ver detalhes`;
 if(typeof value==='object')return 'Ver detalhes';
 if(typeof value==='boolean')return value?'Sim':'Não';
 if(key==='document_state'&&value==='cancelled')return 'Cancelado conforme livro validado';
 if(['status','document_state','kind','direction'].includes(key))return statusLabel(value);
 if(key==='book_mode')return treatments[value]||String(value);
 if(key==='partner_tax_id')return taxId(value);
 if(key==='model')return ({'55':'NF-e','65':'NFC-e','57':'CT-e','NFSE':'NFS-e'})[value]||String(value);
 if(key==='rate')return new Intl.NumberFormat('pt-BR',{maximumFractionDigits:4}).format(Number(value));
 return values[value]||String(value);
}
const schemas={
 diary:['journal_id','date','number','document','account_name','history','debit_cents','credit_cents','cost_center_name'],
 ledger:['journal_id','date','account_name','number','document','counterpart','history','debit_cents','credit_cents','balance_cents'],
 'consolidated-diary':['date','access_code','account_name','cost_center_name','debit_cents','credit_cents','journal_ids'],
 'trial-balance':['access_code','classifier','account_name','opening_cents','debit_cents','credit_cents','closing_cents'],
 'balance-sheet':['classifier','account_name','report_group','opening_cents','closing_cents'],
 'income-statement':['classifier','account_name','report_group','debit_cents','credit_cents','result_cents'],
 'cost-centers':['access_code','account_name','cost_center_name','debit_cents','credit_cents','balance_cents'],
 'fiscal-entries':['document_id','date','issue_date','model','series','document','document_state','partner_name','partner_tax_id','partner_state','cfop','total_cents','book_base_cents','book_icms_cents','book_other_cents','book_ipi_cents','pending'],
 'fiscal-outputs':['document_id','date','model','series','document','document_state','partner_name','partner_state','cfop','total_cents','book_base_cents','book_icms_cents','book_other_cents','book_ipi_cents','pending'],
 'fiscal-documents':['document_id','date','issue_date','document','model','series','partner_name','direction','cfop','total_cents','status','document_state'],
 'fiscal-items':['document_id','date','document','item','description','cfop','ncm','quantity','unit','item_total_cents'],
 'fiscal-operations':['direction','cfop','documents','items','item_total_cents'],
 'fiscal-participants':['partner_name','partner_tax_id','direction','documents','total_cents'],
 'fiscal-classifications':['direction','cfop','ncm','items','item_total_cents'],
 'fiscal-inconsistencies':['document_id','date','document','partner_name','status','message','line_numbers','next_step'],
 'fiscal-assessments':['ledger_id','period','tax','opening_credit_cents','debit_cents','credit_cents','payable_cents','carry_credit_cents'],
 financial:['title_id','kind','partner_name','document','description','issue_date','due_date','amount_cents','paid_cents','balance_cents','status'],
 'cash-flow':['title_id','settlement_id','date','kind','event','partner_name','description','document','debit_cents','credit_cents','cash_cents','balance_cents'],
 partners:['title_id','partner_name','kind','document','due_date','amount_cents','paid_cents','balance_cents','status','consistent']};
export function reportColumns(result){
 const rows=result?.rows||[],present=new Set(rows.flatMap(Object.keys));
 const fields=schemas[result?.kind]||[...present].filter(k=>rows.every(r=>r[k]===null||typeof r[k]!=='object')&&!k.endsWith('_id'));
 return fields.filter(k=>present.has(k)&&(k!=='document_state'||rows.some(r=>r.document_state)));
}
function summaryItem(result,key,{label=reportLabel(key,result),coverage=true}={}){
 const totals=result.totals||{},value=totals[key];let detail='';
 if(coverage&&key.endsWith('_cents')){
  const known=totals[key.slice(0,-6)+'_informed_lines'];const expected=totals.lines;
  if(Number.isInteger(known)&&Number.isInteger(expected))detail=`${known} de ${expected} linhas informadas`;
  const docs=totals[key.slice(0,-6)+'_informed_documents'];
  if(Number.isInteger(docs)&&Number.isInteger(totals.documents))detail=`${docs} de ${totals.documents} documentos informados`;
  if(value!==null&&value!==undefined&&((Number.isInteger(known)&&known<expected)||(Number.isInteger(docs)&&docs<totals.documents)))detail+=' · soma parcial';
 }
 return {key,label,value:formatReportValue(key,value),detail};
}
export function reportSummarySections(result){
 if(!result)return [];
 const totals=result.totals||{};
 if(result.row_scope==='analytical_posting_lines'){
  const movement=['documents','lines','total_cents','lines_with_pending'];
  if(totals.document_total_cents!==totals.total_cents)movement.splice(2,0,'document_total_cents');
  const sections=[{title:'Movimento selecionado',items:movement.filter(k=>k in totals).map(k=>summaryItem(result,k,{label:k==='total_cents'?'Valor contábil selecionado':reportLabel(k,result)}))},
   {title:'Valores fiscais do livro',items:['book_base_cents','book_icms_cents','book_other_cents','book_ipi_cents'].filter(k=>k in totals).map(k=>summaryItem(result,k))}];
  const declared=['declared_icms_base_cents','declared_icms_cents','declared_ipi_cents'].filter(k=>k in totals);
  if(declared.length)sections.push({title:'Valores declarados na origem, para conferência',secondary:true,items:declared.map(k=>summaryItem(result,k))});
  return sections.filter(s=>s.items.length);
 }
 const keys=Object.keys(totals).filter(k=>!k.includes('_informed_')&&!k.endsWith('_ids'));
 return [{title:'Resumo da seleção',items:keys.map(k=>summaryItem(result,k))}];
}
export function reportReviewSummary(result){
 const rows=result?.rows||[],pending=rows.filter(r=>Array.isArray(r.pending)&&r.pending.length),groups=new Map();
 for(const row of pending)for(const code of new Set(row.pending)){
  if(!groups.has(code))groups.set(code,{...reviewMessage(code),lines:0,documents:new Set()});
  const group=groups.get(code);group.lines++;group.documents.add(row.document_id);
 }
 return {lines:pending.length,documents:new Set(pending.map(r=>r.document_id)).size,
  issues:[...groups.values()].map(g=>({...g,documents:g.documents.size}))};
}
export function reportDetailSections(row){
 const identity=['document_id','journal_id','title_id','ledger_id','date','issue_date','document','number','model','series','partner_name','partner_tax_id','partner_state','partner_ie','status','document_state'];
 const book=['line','cfop','total_cents','book_base_cents','book_icms_cents','book_other_cents','book_ipi_cents','treatment','pending'];
 const sections=[],used=new Set();
 function flatten(value,key,prefix=''){
  const label=prefix?`${prefix} · ${reportLabel(key)}`:reportLabel(key);
  if(Array.isArray(value)&&value.some(x=>x&&typeof x==='object'))return value.flatMap((v,i)=>flatten(v,String(i+1),label));
  if(value&&typeof value==='object'&&!Array.isArray(value))return Object.entries(value).flatMap(([k,v])=>flatten(v,k,label));
  const rendered=['icms','icms_base','ipi','ipi_base'].includes(key)&&value!==null&&value!==''&&Number.isFinite(Number(value))?new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(Number(value)):formatReportValue(key,value);
  return [{label,value:rendered}];
 }
 for(const [title,keys] of [['Identificação',identity],['Escrituração e revisão',book],['Valores e classificações declarados',['declared_taxes','declared_classifications','declared_tax_coverage','declared_tax_partial_totals','declared_icms_cents','declared_icms_base_cents','declared_ipi_cents','declared_ipi_base_cents']],['Rastreabilidade',[...Object.keys(row).filter(k=>!identity.includes(k)&&!book.includes(k)&&!k.startsWith('declared_'))]]]){
  const items=keys.filter(k=>k in row&&!used.has(k)).flatMap(k=>{used.add(k);return flatten(row[k],k);});if(items.length)sections.push({title,items});
 }
 const remaining=Object.keys(row).filter(k=>!used.has(k));if(remaining.length)sections.push({title:'Informações complementares',items:remaining.flatMap(k=>flatten(row[k],k))});
 return sections;
}

export function reportOrigins(row){
 const links=[];
 for(const [key,type] of [['journal_ids','Lançamento'],['document_ids','Documento']])
  for(const id of Array.isArray(row[key])?row[key]:[])
   links.push({key:key==='journal_ids'?'journal_id':'document_id',id,label:`${type} #${id}`});
 return links;
}
