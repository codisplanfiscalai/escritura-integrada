<script setup>
import {computed} from 'vue';import Icon from '../components/Icon.vue';import EmptyState from '../components/EmptyState.vue';
import {state,company,api,scope,useResource,rows} from '../lib/workspace';
import {can,allowedApi,writable} from '../lib/workspace';import {money,date,statusLabel} from '../lib/format';
const {data,loading,error}=useResource(async()=>{if(!state.companyId)return null;const[d,j,t]=await Promise.all([api(scope(`/dashboard?period=${state.period}`)),api(scope(`/journals?period=${state.period}`)),api(scope('/titles'))]);return {...d,recent:rows(j).slice(0,5),titles:rows(t).filter(t=>t.balance_cents>0).sort((a,b)=>a.due_date.localeCompare(b.due_date)).slice(0,3)};},null);
const cards=computed(()=>[{label:'Documentos na competência',value:data.value?.documents?.count||0,sub:`${data.value?.documents?.pending||0} aguardando conferência`,icon:'documents',color:'blue'},{label:'Movimento contábil',value:money(data.value?.accounting?.debit_cents),sub:`${data.value?.accounting?.journals||0} lançamentos escriturados`,icon:'journal',color:'teal'},{label:'Contas a pagar',value:money(data.value?.financial?.payable_cents),sub:'Saldo de obrigações em aberto',icon:'out',color:'amber'},{label:'Contas a receber',value:money(data.value?.financial?.receivable_cents),sub:'Saldo de direitos em aberto',icon:'in',color:'green'}]);
const go=tab=>state.tab=tab;
</script>
<template><div class="view"><header class="view-heading"><div><div class="eyebrow">SEU ESCRITÓRIO, EM CONTEXTO</div><h1>Visão geral</h1><p>Acompanhe o trabalho de {{company?.trade_name||company?.name}} nesta competência.</p></div><button class="button primary" @click="go('imports')"><Icon name="import"/>Importar documentos</button></header><div v-if="error" class="message error">{{error}}</div>
<div class="metrics-grid"><article v-for="card in cards" :key="card.label" class="metric-card"><div class="metric-top"><span>{{card.label}}</span><span class="metric-icon" :class="card.color"><Icon :name="card.icon"/></span></div><strong>{{card.value}}</strong><small>{{card.sub}}</small></article></div>
<div class="dashboard-grid"><section class="panel"><div class="panel-heading"><div><h2>Lançamentos recentes</h2><p>Movimentos escriturados na empresa ativa.</p></div><button class="text-button" @click="go('journal')">Ver todos<Icon name="arrow" :size="16"/></button></div><div v-if="loading" class="loading-line"><Icon name="loading"/>Atualizando informações...</div><div v-else-if="data?.recent?.length" class="table-scroll"><table><thead><tr><th>Data</th><th>Documento / histórico</th><th class="right">Valor</th><th>Estado</th></tr></thead><tbody><tr v-for="j in data.recent" :key="j.id"><td class="nowrap">{{date(j.date)}}</td><td><strong>{{j.document||`Lançamento ${j.number||j.id}`}}</strong><small class="cell-secondary">{{j.history}}</small></td><td class="right money">{{money(j.total_cents)}}</td><td><span class="badge" :class="j.status==='reversed'?'neutral':'success'">{{statusLabel(j.status)}}</span></td></tr></tbody></table></div><EmptyState v-else title="Seu livro começa aqui" text="Crie o primeiro lançamento ou confira os documentos importados." icon="book"><button class="button outline" @click="go('journal')">Abrir contabilidade<Icon name="arrow" :size="15"/></button></EmptyState></section>
<section class="panel workflow-panel"><div class="panel-heading"><div><h2>Próximos passos</h2><p>O que merece atenção agora.</p></div><Icon name="layers"/></div><button class="workflow-row" @click="go('documents')"><span class="workflow-icon amber"><Icon name="documents"/></span><span><strong>Conferência fiscal</strong><small>{{data?.documents?.pending||0}} documentos pendentes</small></span><Icon name="right" :size="16"/></button><button class="workflow-row" @click="go('reconcile')"><span class="workflow-icon blue"><Icon name="reconcile"/></span><span><strong>Conciliação</strong><small>{{data?.reconciliation?.pending||0}} movimentos a conciliar</small></span><Icon name="right" :size="16"/></button><button class="workflow-row" @click="go('periods')"><span class="workflow-icon teal"><Icon name="periods"/></span><span><strong>Fechamento da competência</strong><small>Fiscal e contábil independentes</small></span><Icon name="right" :size="16"/></button><div class="workflow-tip"><Icon name="shield" :size="17"/><p>Cada operação mantém sua origem, empresa, competência e histórico de alterações.</p></div></section>
<section class="panel"><div class="panel-heading"><div><h2>Agenda financeira</h2><p>Obrigações e recebimentos ainda em aberto.</p></div><button class="text-button" @click="go('finance')">Abrir financeiro<Icon name="arrow" :size="16"/></button></div><div v-if="data?.titles?.length" class="table-scroll"><table><thead><tr><th>Vencimento</th><th>Título / pessoa</th><th>Tipo</th><th class="right">Saldo</th></tr></thead><tbody><tr v-for="t in data.titles" :key="t.id"><td class="nowrap">{{date(t.due_date)}}</td><td><strong>{{t.description}}</strong><small class="cell-secondary">{{t.partner_name}}</small></td><td><span class="badge" :class="t.kind==='payable'?'warning':'success'">{{statusLabel(t.kind)}}</span></td><td class="right money">{{money(t.balance_cents??t.amount_cents-t.paid_cents)}}</td></tr></tbody></table></div><EmptyState v-else title="Agenda em dia" text="Os títulos cadastrados aparecerão aqui por vencimento." icon="finance"/></section>
<section class="panel context-panel"><div class="panel-heading"><div><h2>Competência em trabalho</h2><p>{{state.period.split('-').reverse().join('/')}}</p></div><Icon name="periods"/></div><div class="period-state"><span>Escrituração fiscal</span><span class="badge" :class="state.locks?.fiscal?.closed?'neutral':'success'"><Icon :name="state.locks?.fiscal?.closed?'lock':'unlock'" :size="13"/>{{state.locks?.fiscal?.closed?'Fechada':'Aberta'}}</span></div><div class="period-state"><span>Escrituração contábil</span><span class="badge" :class="state.locks?.accounting?.closed?'neutral':'success'"><Icon :name="state.locks?.accounting?.closed?'lock':'unlock'" :size="13"/>{{state.locks?.accounting?.closed?'Fechada':'Aberta'}}</span></div><div class="context-summary"><Icon name="building"/><div><strong>{{company?.code}} · {{company?.trade_name||company?.name}}</strong><small>Todos os indicadores pertencem a esta empresa.</small></div></div><button class="button full" @click="go('periods')">Gerenciar competência<Icon name="arrow" :size="15"/></button></section></div>
</div></template>

<style scoped>
/* Preserve leitura e ações; o painel inicial prioriza uma visão compacta. */
@media (min-width: 1021px) {
  .view-heading { margin-bottom: 18px; }
  .metrics-grid { gap: 12px; margin-bottom: 16px; }
  .metric-card { padding: 12px 16px; }
  .metric-card > strong { margin-top: 5px; margin-bottom: 5px; }
  .dashboard-grid { gap: 14px; }
  .dashboard-grid .panel-heading { padding: 11px 15px; }
  .dashboard-grid th { padding-top: 8px; padding-bottom: 8px; }
  .dashboard-grid td { padding-top: 9px; padding-bottom: 9px; }
  .dashboard-grid .cell-secondary {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .dashboard-grid :deep(.empty-state) { padding: 18px 20px; }
  .workflow-row { padding: 7px 15px; }
  .workflow-tip { padding: 8px 15px; }
  .period-state { padding: 7px 15px; }
  .context-summary { margin: 8px 15px; padding: 9px; }
  .context-summary small { margin-top: 3px; }
  .context-panel > .button { width: calc(100% - 30px); margin: 0 15px 12px; }
}
</style>
