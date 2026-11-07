<script setup>
import {ref,computed,watch,onUnmounted} from 'vue';
import Icon from '../components/Icon.vue';
import EmptyState from '../components/EmptyState.vue';
import {state,company,api,scope,useResource,rows,notify} from '../lib/workspace';
import {money,date,taxId} from '../lib/format';

const kind=ref('trial-balance'),accountId=ref(''),centerId=ref(''),report=ref(null),loading=ref(false),error=ref('');
let sequence=0,alive=true;
const names={'diary':'Diário','ledger':'Razão','trial-balance':'Balancete'};
const {data:catalogs,error:catalogError}=useResource(async()=>{
 if(!state.companyId)return {accounts:[],centers:[]};
 const[a,c]=await Promise.all([api(scope('/accounts')),api(scope('/cost-centers'))]);
 return {accounts:rows(a),centers:rows(c)};
},{accounts:[],centers:[]});
const account=computed(()=>catalogs.value.accounts.find(a=>a.id===Number(accountId.value)));
const center=computed(()=>catalogs.value.centers.find(c=>c.id===Number(centerId.value)));
const canUse=computed(()=>report.value&&report.value.company_id===state.companyId&&report.value.period===state.period&&!loading.value);
const rowList=computed(()=>report.value?.rows||[]);
const reportTitle=computed(()=>names[kind.value]);
function balance(value){const n=Number(value||0);return `${money(Math.abs(n))}${n>0?' D':n<0?' C':''}`;}
async function load(){
 const current=++sequence,cid=state.companyId,p=state.period,k=kind.value,a=accountId.value,cc=centerId.value;
 report.value=null;error.value='';
 if(!cid||(k==='ledger'&&!a)){loading.value=false;return;}
 loading.value=true;
 try{
  const query=new URLSearchParams({period:p});
  if(k==='ledger')query.set('account_id',a);
  if(cc)query.set('cost_center_id',cc);
  const value=await api(scope(`/reports/${k}?${query}`,cid));
  if(alive&&current===sequence&&cid===state.companyId&&p===state.period)report.value=value;
 }catch(e){if(alive&&current===sequence)error.value=e.message;}
 finally{if(alive&&current===sequence)loading.value=false;}
}
watch(()=>state.companyId,()=>{accountId.value='';centerId.value='';});
watch(()=>[kind.value,accountId.value,centerId.value,state.companyId,state.period,state.refresh],load,{immediate:true});
watch(()=>catalogs.value,()=>{
 if(accountId.value&&!catalogs.value.accounts.some(a=>a.id===Number(accountId.value)))accountId.value='';
 if(centerId.value&&!catalogs.value.centers.some(c=>c.id===Number(centerId.value)))centerId.value='';
});
onUnmounted(()=>{alive=false;sequence++;});

function exportRows(){
 if(kind.value==='trial-balance')return {headers:['Acesso','Classificador','Conta','Natureza','Saldo anterior (D−C)','Débitos','Créditos','Saldo final (D−C)'],data:rowList.value.map(r=>[r.access_code,r.classifier,r.account_name,r.nature==='debit'?'Devedora':'Credora',decimal(r.opening_cents),decimal(r.debit_cents),decimal(r.credit_cents),decimal(r.closing_cents)])};
 const headers=['Data','Lançamento','Documento','Histórico','Acesso','Conta','Centro de custo','Débito','Crédito'];
 if(kind.value==='ledger')headers.push('Saldo (D−C)');
 const data=rowList.value.map(r=>{const line=[date(r.date),r.number,r.document,r.history,r.access_code,r.account_name,r.cost_center_name||'',decimal(r.debit_cents),decimal(r.credit_cents)];if(kind.value==='ledger')line.push(decimal(r.balance_cents));return line;});
 return {headers,data};
}
function decimal(value){return (Number(value||0)/100).toFixed(2).replace('.',',');}
function csvCell(value){let s=String(value??'');if(typeof value==='string'&&/^[\s]*[=+\-@]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';}
function exportCSV(){
 if(!canUse.value)return;
 const output=exportRows();
 const lines=[['Relatório interno',reportTitle.value],['Empresa',company.value?.name],['CNPJ',company.value?.tax_id],['Competência',state.period],['Centro de custo',center.value?.name||'Todos'],['Conta',kind.value==='ledger'?account.value?.name:'Todas'],[],output.headers,...output.data];
 const blob=new Blob(['\uFEFF'+lines.map(line=>line.map(csvCell).join(';')).join('\r\n')],{type:'text/csv;charset=utf-8'});
 const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=`${kind.value}-empresa-${state.companyId}-${state.period}.csv`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 notify('Relatório exportado em CSV. Campos de texto com prefixos de fórmula foram protegidos.');
}
function escapeHTML(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function printReport(){
 if(!canUse.value)return;
 const win=window.open('','_blank','width=1100,height=800');
 if(!win){notify('Permita a janela de impressão para gerar o PDF pelo navegador.','warning');return;}
 win.opener=null;
 const output=exportRows(),totals=report.value.totals;
 const title=`${reportTitle.value} · ${state.period.split('-').reverse().join('/')}`;
 win.document.open();
 win.document.write(`<!doctype html><html lang="pt-BR"><head><meta charset="UTF-8"><title>${escapeHTML(title)}</title><style>body{font:11px Arial,sans-serif;color:#162b35;margin:22px}h1{font-size:21px;margin:0 0 6px}p{margin:4px 0}.meta{margin-bottom:16px}.note{font-size:10px;margin-top:16px;color:#465864}table{width:100%;border-collapse:collapse}th,td{padding:6px;text-align:left;border-bottom:1px solid #d7dfe4;vertical-align:top}th{background:#eef3f5;font-size:10px}thead{display:table-header-group}tr{break-inside:avoid}tfoot td{font-weight:bold}@page{size:A4 landscape;margin:12mm}@media print{body{margin:0}}</style></head><body><h1>${escapeHTML(title)}</h1><div class="meta"><p><strong>${escapeHTML(company.value?.name)}</strong> · CNPJ ${escapeHTML(taxId(company.value?.tax_id))}</p><p>Centro de custo: ${escapeHTML(center.value?.name||'Todos')} ${kind.value==='ledger'?' · Conta: '+escapeHTML(account.value?.name):''}</p><p>Relatório interno de conferência · dados cadastrados no Escritura Integrada${state.session?.demo?' · DADOS FICTÍCIOS DE DEMONSTRAÇÃO':''}</p></div><table><thead><tr>${output.headers.map(x=>'<th>'+escapeHTML(x)+'</th>').join('')}</tr></thead><tbody>${output.data.map(line=>'<tr>'+line.map(x=>'<td>'+escapeHTML(x)+'</td>').join('')+'</tr>').join('')}</tbody></table><p class="note">Totais do recorte: débitos ${escapeHTML(money(totals.debit_cents))}; créditos ${escapeHTML(money(totals.credit_cents))}. ${escapeHTML(report.value.scope_note)} Saldo assinado = débitos menos créditos. Este relatório não é um livro legal homologado. Utilize a opção Salvar como PDF na janela de impressão.</p></body></html>`);
 win.document.close();win.addEventListener('load',()=>{win.focus();win.print();},{once:true});
}
</script>

<template>
 <div class="view reports-view">
  <header class="view-heading"><div><div class="eyebrow">CONFERÊNCIA CONTÁBIL</div><h1>Livros e relatórios</h1><p>Consulte movimentos, saldos e centros de custo na empresa ativa.</p></div><div class="actions"><button class="button outline" :disabled="!canUse" @click="exportCSV"><Icon name="download"/>Exportar CSV</button><button class="button outline" :disabled="!canUse" @click="printReport"><Icon name="file"/>Imprimir / PDF</button></div></header>
  <div class="segmented"><button v-for="(label,key) in names" :key="key" :class="{selected:kind===key}" @click="kind=key"><Icon :name="key==='trial-balance'?'reports':'book'" :size="16"/>{{label}}</button></div>
  <section class="panel report-filters"><div class="form-grid three"><label>Competência em uso<span class="read-field"><Icon name="periods" :size="16"/>{{state.period.split('-').reverse().join('/')}}</span></label><label v-if="kind==='ledger'">Conta analítica *<select v-model="accountId" aria-label="Conta do Razão"><option value="">Selecione uma conta</option><option v-for="a in catalogs.accounts.filter(a=>a.analytical)" :key="a.id" :value="a.id">{{a.access_code}} · {{a.name}}</option></select></label><label v-else>Contas incluídas<span class="read-field">{{kind==='trial-balance'?'Todas as contas analíticas':'Todas as contas com movimentos'}}</span></label><label>Centro de custo<select v-model="centerId" aria-label="Centro de custo do relatório"><option value="">Todos os centros</option><option v-for="c in catalogs.centers" :key="c.id" :value="c.id">{{c.code}} · {{c.name}}</option></select></label></div></section>
  <div v-if="error||catalogError" class="message error" role="alert">{{error||catalogError}}</div>
  <div v-if="centerId" class="message subtle"><Icon name="info"/><span>O centro de custo filtra cada partida. Contrapartidas sem esse centro não compõem o recorte; seus débitos e créditos podem ser diferentes.</span></div>
  <section class="panel report-content">
   <div class="panel-heading"><div><h2>{{reportTitle}}</h2><p>{{company?.name}}<template v-if="kind==='ledger'&&account"> · {{account.classifier}} · {{account.name}}</template></p></div><span class="badge neutral">{{rowList.length}} {{kind==='trial-balance'?'contas':'partidas'}}</span></div>
   <div v-if="loading" class="loading-line"><Icon name="loading"/>Preparando o relatório...</div>
   <EmptyState v-else-if="kind==='ledger'&&!accountId" title="Selecione a conta do Razão" text="A consulta mostra o saldo anterior e a evolução de uma conta específica." icon="book"/>
   <template v-else-if="report">
    <div v-if="kind==='ledger'" class="summary-strip"><div><span>Saldo anterior</span><strong>{{balance(report.totals.opening_cents)}}</strong></div><div><span>Débitos</span><strong>{{money(report.totals.debit_cents)}}</strong></div><div><span>Créditos</span><strong>{{money(report.totals.credit_cents)}}</strong></div><div class="push-right"><span>Saldo final</span><strong>{{balance(report.totals.closing_cents)}}</strong></div></div>
    <div v-if="rowList.length" class="table-scroll"><table v-if="kind==='trial-balance'"><thead><tr><th>Acesso / classificação</th><th>Conta</th><th class="right">Saldo anterior</th><th class="right">Débitos</th><th class="right">Créditos</th><th class="right">Saldo final</th></tr></thead><tbody><tr v-for="r in rowList" :key="r.account_id"><td class="mono">{{r.access_code}}<small class="cell-secondary">{{r.classifier}}</small></td><td><strong>{{r.account_name}}</strong><small class="cell-secondary">Natureza {{r.nature==='debit'?'devedora':'credora'}}</small></td><td class="right money">{{balance(r.opening_cents)}}</td><td class="right money">{{money(r.debit_cents)}}</td><td class="right money">{{money(r.credit_cents)}}</td><td class="right money"><strong>{{balance(r.closing_cents)}}</strong></td></tr></tbody><tfoot><tr><th colspan="2">Total do recorte</th><th class="right money">{{balance(report.totals.opening_cents)}}</th><th class="right money">{{money(report.totals.debit_cents)}}</th><th class="right money">{{money(report.totals.credit_cents)}}</th><th class="right money">{{balance(report.totals.closing_cents)}}</th></tr></tfoot></table>
    <table v-else><thead><tr><th>Data / nº</th><th>{{kind==='ledger'?'Documento / histórico':'Conta / histórico'}}</th><th>Centro de custo</th><th class="right">Débito</th><th class="right">Crédito</th><th v-if="kind==='ledger'" class="right">Saldo</th></tr></thead><tbody><tr v-for="(r,i) in rowList" :key="`${r.journal_id}:${i}`"><td class="nowrap">{{date(r.date)}}<small class="cell-secondary mono">{{r.number}}</small></td><td class="report-history"><strong>{{kind==='ledger'?(r.document||'Sem documento'):`${r.access_code} · ${r.account_name}`}}</strong><small class="cell-secondary">{{r.history}}<template v-if="kind==='diary'&&r.document"> · {{r.document}}</template></small></td><td>{{r.cost_center_name||'—'}}</td><td class="right money">{{r.debit_cents?money(r.debit_cents):'—'}}</td><td class="right money">{{r.credit_cents?money(r.credit_cents):'—'}}</td><td v-if="kind==='ledger'" class="right money">{{balance(r.balance_cents)}}</td></tr></tbody><tfoot><tr><th colspan="3">Total do recorte</th><th class="right money">{{money(report.totals.debit_cents)}}</th><th class="right money">{{money(report.totals.credit_cents)}}</th><th v-if="kind==='ledger'" class="right money">{{balance(report.totals.closing_cents)}}</th></tr></tfoot></table></div>
    <EmptyState v-else title="Sem movimentos neste recorte" text="Os filtros não encontraram partidas. Saldos anteriores, quando existentes, permanecem no resumo do Razão." icon="reports"/>
    <footer class="table-footer"><span>Saldos: D = devedor · C = credor. Estornos permanecem como novas partidas.</span><span>Relatório interno</span></footer>
   </template>
  </section>
  <div class="message subtle"><Icon name="shield"/><span>Os relatórios refletem os lançamentos cadastrados e os filtros selecionados. Não substituem livros legais homologados ou validação em obrigação acessória.</span></div>
 </div>
</template>

<style scoped>
.report-filters{padding:16px 20px}.report-filters .form-grid{margin:0}.report-history{min-width:230px;max-width:490px}.report-content tfoot th{border-top:1px solid #dce4e8;background:#f6f9fa;padding:13px 14px;font-size:12px}.report-filters .read-field{display:flex;align-items:center;gap:8px}.reports-view .summary-strip{flex-wrap:wrap}
@media(min-width:761px){
 .reports-view>.view-heading{margin-bottom:12px}
 .reports-view>.view-heading .eyebrow{margin-bottom:4px}
 .reports-view>.view-heading p{margin-top:3px}
 .reports-view>.segmented{margin-bottom:8px;padding:3px}
 .reports-view>.segmented button{padding-top:6px;padding-bottom:6px}
 .report-filters{padding-top:8px;padding-bottom:8px}
 .report-filters label{gap:4px}
 .report-content>.panel-heading{padding-top:10px;padding-bottom:10px}
 .report-content>.panel-heading p{margin-top:3px}
 .report-content thead th{padding-top:8px;padding-bottom:8px}
 .report-content tbody td{padding-top:7px;padding-bottom:7px}
 .report-content .cell-secondary{margin-top:1px}
 .report-content tfoot th{padding-top:8px;padding-bottom:8px}
 .report-content>.table-footer{padding-top:7px;padding-bottom:7px}
 .reports-view>.message{margin-top:8px;margin-bottom:0;padding-top:8px;padding-bottom:8px}
}
@media(max-width:700px){.report-filters{padding:14px}.report-filters .form-grid{grid-template-columns:1fr}.reports-view .view-heading .actions{flex-wrap:wrap}}
</style>
