<script setup>
import {useSuggestedCompetence} from '../lib/context-preferences.js';
import { ref, computed, watch, onUnmounted } from 'vue';
import BankAllocation from '../components/BankAllocation.vue';
import Icon from '../components/Icon.vue';
import BaseModal from '../components/BaseModal.vue';
import EmptyState from '../components/EmptyState.vue';
import { state, company, api, scope, useResource, rows, notify, ask, changed } from '../lib/workspace';
import {can,allowedApi,writable} from '../lib/workspace';
import { money, date, dateTime, normalized } from '../lib/format';

const allocationBank=ref(null);
async function undoAllocation(a){const reason=await ask({title:'Desfazer vínculo do rateio',message:'A baixa financeira vinculada será preservada; estorne-a separadamente no Financeiro se necessário.',inputLabel:'Justificativa',required:true,confirmLabel:'Desfazer vínculo'});if(!reason)return;try{await api(scope(`/allocations/${a.id}/reverse`),{method:'POST',body:{reason}});changed();}catch(e){notify(e.message,'error');}}
const query = ref(''), status = ref('pending'), account = ref(''), selectedId = ref(null);
const suggestions = ref([]), suggestionBusy = ref(false), suggestionError = ref('');
const show = ref(false), mode = ref('link'), busy = ref(false), error = ref('');
const context = ref({}), transaction = ref(null), form = ref({title_id:'', reason:''});
const titleOptions = ref([]), titlesBusy = ref(false), titleError = ref('');
let baseline = '', suggestionSequence = 0, modalSequence = 0, alive = true;

const competence=ref(state.period);useSuggestedCompetence(state,competence);
const contextKey = computed(() => `${state.companyId}:${competence.value}`);
const { data, loading, error: loadError, reload } = useResource(async () => {
  const id = state.companyId, period = competence.value, key = `${id}:${period}`;
  if (!id) return {key, banks:[]};
  const response = await api(scope(`/banks?period=${encodeURIComponent(period)}`, id));
  return {key, banks:rows(response)};
}, {key:'', banks:[]});
// A lista da empresa anterior desaparece imediatamente durante a troca de contexto.
const banks = computed(() => data.value.key === contextKey.value ? data.value.banks : []);
const accounts = computed(() => [...new Set(banks.value.map(b => b.bank_account))].filter(Boolean).sort());
const pendingCount = computed(() => banks.value.filter(b => !b.reconciled).length);
const linkedCount = computed(() => banks.value.filter(b => b.reconciled).length);
const filtered = computed(() => banks.value.filter(b =>
  (!account.value || b.bank_account === account.value) &&
  (!status.value || (status.value === 'linked' ? b.reconciled : !b.reconciled)) &&
  normalized(`${b.description} ${b.reference} ${b.external_id} ${b.bank_account}`).includes(normalized(query.value))
));
const selected = computed(() => filtered.value.find(b => b.id === selectedId.value) || null);
const isDirty = computed(() => show.value && baseline !== JSON.stringify(form.value));
const compatibleTitles = computed(() => {
  if (!transaction.value) return [];
  const kind = transaction.value.amount_cents > 0 ? 'receivable' : 'payable';
  return titleOptions.value.filter(t => !t.cancelled && !t.allocations?.length && t.kind === kind && t.amount_cents === Math.abs(transaction.value.amount_cents));
});
const chosenTitle = computed(() => compatibleTitles.value.find(t => t.id === Number(form.value.title_id)));
const periodLabel = p => String(p || '').split('-').reverse().join('/');

watch(competence,()=>reload());
watch(contextKey, () => { account.value = ''; selectedId.value = null; query.value = ''; });
watch(filtered, list => {
  if (!list.some(b => b.id === selectedId.value)) selectedId.value = list[0]?.id ?? null;
}, {immediate:true});

async function loadSuggestions() {
  const sequence = ++suggestionSequence;
  const bank = selected.value, id = state.companyId, key = contextKey.value;
  suggestions.value = []; suggestionError.value = ''; suggestionBusy.value = false;
  if (!bank || bank.reconciled) return;
  suggestionBusy.value = true;
  try {
    const response = await api(scope(`/banks/${bank.id}/suggestions`, id));
    if (alive && sequence === suggestionSequence && key === contextKey.value && selectedId.value === bank.id)
      suggestions.value = rows(response);
  } catch (e) {
    if (alive && sequence === suggestionSequence && key === contextKey.value) suggestionError.value = e.message;
  } finally {
    if (alive && sequence === suggestionSequence) suggestionBusy.value = false;
  }
}
watch(() => [selected.value?.id, selected.value?.reconciled, contextKey.value, state.refresh], loadSuggestions, {immediate:true});

async function openLink(candidate = null) {
  if (loading.value || !selected.value || selected.value.reconciled || state.editor) return;
  const sequence = ++modalSequence;
  mode.value = 'link';
  transaction.value = {...selected.value};
  context.value = {id:state.companyId, name:company.value?.trade_name || company.value?.name, period:competence.value};
  form.value = {title_id:candidate?.title_id ?? '', reason:''};
  baseline = JSON.stringify(form.value);
  error.value = ''; titleError.value = ''; titleOptions.value = []; show.value = true;
  state.editor = {name:'Conciliação bancária', companyId:context.value.id};
  titlesBusy.value = true;
  try {
    const response = await api(scope('/titles', context.value.id));
    if (alive && sequence === modalSequence && show.value) titleOptions.value = rows(response);
  } catch (e) {
    if (alive && sequence === modalSequence && show.value) titleError.value = e.message;
  } finally {
    if (alive && sequence === modalSequence) titlesBusy.value = false;
  }
}

function openUnlink() {
  if (loading.value || !selected.value?.reconciled || state.editor) return;
  ++modalSequence;
  mode.value = 'unlink';
  transaction.value = {...selected.value};
  context.value = {id:state.companyId, name:company.value?.trade_name || company.value?.name, period:competence.value};
  form.value = {title_id:selected.value.reconciliation?.title_id ?? '', reason:''};
  baseline = JSON.stringify(form.value); error.value = ''; show.value = true;
  state.editor = {name:'Desfazer vínculo bancário', companyId:context.value.id};
}

async function close() {
  if (busy.value) return;
  if (isDirty.value && !await ask({title:'Descartar conferência?', message:'O vínculo e a justificativa desta janela ainda não foram salvos.', confirmLabel:'Descartar', danger:true})) return;
  ++modalSequence; show.value = false; state.editor = null;
}

async function save() {
  if (busy.value) return;
  error.value = ''; busy.value = true;
  try {
    if (context.value.id !== state.companyId || context.value.period !== competence.value)
      throw new Error('A empresa ou a competência mudou. Feche esta janela e confira o contexto antes de continuar.');
    if (!form.value.reason.trim()) throw new Error('Registre a justificativa da conferência.');
    if (mode.value === 'link' && !chosenTitle.value) throw new Error('Selecione um título de mesmo valor e sentido.');
    const endpoint = mode.value === 'link' ? 'reconcile' : 'unreconcile';
    const payload = {reason:form.value.reason.trim()};
    if (mode.value === 'link') payload.title_id = Number(form.value.title_id);
    await api(scope(`/banks/${transaction.value.id}/${endpoint}`, context.value.id), {method:'POST', body:payload});
    const wasLink = mode.value === 'link';
    ++modalSequence; show.value = false; state.editor = null;
    changed();
    notify(wasLink ? 'Vínculo registrado. A baixa financeira permanece independente.' : 'Vínculo desfeito. A justificativa foi registrada no histórico.');
  } catch (e) { error.value = e.message; }
  finally { busy.value = false; }
}

function navigate(tab) {
  if (!state.editor) state.navigate(tab);
}
onUnmounted(() => { alive = false; suggestionSequence++; modalSequence++; if (show.value) state.editor = null; });
</script>

<template>
  <div class="view">
    <header class="view-heading">
      <div><div class="eyebrow">CONFERÊNCIA INTEGRADA</div><h1>Conciliação bancária</h1><p>Confira os movimentos do extrato e vincule cada um ao título correspondente.</p></div>
      <button class="button primary" v-allow="['financial.reconciliation','import']" @click="navigate('bank-imports')"><Icon name="import"/>Importar extrato</button>
    </header>
    <div class="finance-top">
      <div class="mini-metric"><span>Movimentos na competência</span><strong>{{banks.length}}</strong></div>
      <div class="mini-metric"><span>A conferir</span><strong>{{pendingCount}}</strong></div>
      <div class="mini-metric"><span>Vínculos registrados</span><strong class="positive">{{linkedCount}}</strong></div>
      <p class="reconcile-note"><Icon name="info" :size="16"/>O vínculo não registra pagamento ou recebimento. As baixas ficam no Financeiro.</p>
    </div>
    <div v-if="loadError" class="message error" role="alert">{{loadError}} <button class="text-button" @click="reload">Tentar novamente</button></div>

    <div class="reconcile-grid">
      <section class="panel reconcile-bank-panel" aria-label="Movimentos do extrato">
        <div class="panel-heading"><div><h2>Extrato bancário</h2><label>Competência do extrato<select v-model="competence" :disabled="!!state.editor"><option v-for="m in 12" :value="`${state.period.slice(0,4)}-${String(m).padStart(2,'0')}`">{{String(m).padStart(2,'0')}} / {{state.period.slice(0,4)}}</option></select></label><p>Empresa ativa · {{periodLabel(competence)}}</p></div><span class="badge neutral">{{filtered.length}} {{filtered.length===1?'movimento':'movimentos'}}</span></div>
        <div class="reconcile-filters">
          <div class="search-field"><Icon name="search"/><input v-model="query" placeholder="Histórico ou documento" aria-label="Pesquisar movimento bancário"/></div>
          <select v-model="account" aria-label="Filtrar conta bancária"><option value="">Todas as contas</option><option v-for="item in accounts" :key="item" :value="item">{{item}}</option></select>
          <div class="segmented" aria-label="Situação dos movimentos"><button :class="{selected:status==='pending'}" @click="status='pending'">Pendentes</button><button :class="{selected:status==='linked'}" @click="status='linked'">Vinculados</button><button :class="{selected:status===''}" @click="status=''">Todos</button></div>
        </div>
        <div v-if="loading" class="loading-line"><Icon name="loading"/>Carregando extrato...</div>
        <ul v-else-if="filtered.length" class="reconcile-bank-list">
          <li v-for="bank in filtered" :key="bank.id">
            <button class="reconcile-bank-row" :class="{selected:selectedId===bank.id}" :aria-pressed="selectedId===bank.id" @click="selectedId=bank.id">
              <span class="reconcile-row-main"><span class="reconcile-transaction-icon" :class="bank.amount_cents>0?'incoming':'outgoing'"><Icon :name="bank.amount_cents>0?'in':'out'" :size="17"/></span><span class="reconcile-row-label"><strong>{{bank.description}}</strong><small>{{date(bank.date)}} · {{bank.reference||'Sem documento'}}</small></span><strong class="money" :class="bank.amount_cents>0?'positive':'negative'">{{money(bank.amount_cents)}}</strong></span>
              <span class="reconcile-row-meta"><span>{{bank.bank_account}}</span><span class="badge" :class="bank.reconciled?'success':'warning'"><Icon :name="bank.reconciled?'link':'clock'" :size="12"/>{{bank.reconciled?'Vinculado':'Pendente'}}</span></span>
            </button>
          </li>
        </ul>
        <EmptyState v-else :title="banks.length?'Nenhum movimento neste filtro':'Nenhum extrato nesta competência'" :text="banks.length?'Altere a situação, conta ou pesquisa para localizar o movimento.':'Importe e confira um extrato para começar a conciliação.'" icon="bank"><button v-if="!banks.length" class="button outline" v-allow="['financial.reconciliation','import']" @click="navigate('bank-imports')">Importar extrato<Icon name="arrow" :size="15"/></button></EmptyState>
        <footer class="table-footer"><span>TXT, CSV, OFX, QIF e OFC passam pela conferência de importação.</span></footer>
      </section>

      <section class="panel reconcile-detail-panel" aria-label="Conferência do movimento selecionado">
        <template v-if="selected">
          <div class="panel-heading"><div><h2>Conferir movimento</h2><p>Seleção manual, com justificativa e histórico.</p></div><span class="badge" :class="selected.reconciled?'success':'warning'">{{selected.reconciled?'Vinculado':'Pendente'}}</span></div>
          <div class="reconcile-detail">
            <div class="reconcile-detail-top"><div><span class="eyebrow">{{selected.amount_cents>0?'ENTRADA NO BANCO':'SAÍDA DO BANCO'}}</span><h3>{{selected.description}}</h3></div><strong class="reconcile-amount money" :class="selected.amount_cents>0?'positive':'negative'">{{money(selected.amount_cents)}}</strong></div>
            <dl class="reconcile-facts"><div><dt>Data do extrato</dt><dd>{{date(selected.date)}}</dd></div><div><dt>Conta bancária</dt><dd>{{selected.bank_account}}</dd></div><div><dt>Documento / referência</dt><dd class="mono">{{selected.reference||'Não informado'}}</dd></div><div><dt>Identificador de origem</dt><dd class="mono">{{selected.external_id||'Sem identificador bancário'}}</dd></div></dl>
            <div v-if="selected.source?.file" class="reconcile-source"><Icon name="file" :size="14"/><span>{{selected.source.file}}<template v-if="selected.source.line"> · linha {{selected.source.line}}</template></span></div>
          </div>

          <div class="reconcile-detail"><p v-if="selected.allocated_cents">Valor conciliado: {{money(selected.allocated_cents)}} · disponível: {{money(selected.remaining_cents)}}</p><p v-for="a in selected.allocations" :key="a.id">#{{a.title_id}} {{a.title_description}} · {{money(a.amount_cents)}} <button class="text-button" v-allow="['financial.reconciliation','reverse']" @click="undoAllocation(a)">Desfazer vínculo</button><small v-if="a.settlement_id"> · baixa #{{a.settlement_id}}</small></p><button v-if="!selected.reconciled" class="button primary" v-allow="['financial.reconciliation','edit']" @click="allocationBank={...selected}">Conciliar por rateio / agrupamento</button></div><template v-if="selected.reconciled&&selected.reconciliation">
            <div class="reconcile-linked">
              <div class="reconcile-linked-heading"><Icon name="checks"/><div><h3>Vínculo registrado</h3><p>{{selected.reconciliation?.title_description||`Título ${selected.reconciliation?.title_id}`}}</p></div></div>
              <dl class="reconcile-facts"><div><dt>Responsável</dt><dd>{{selected.reconciliation?.created_by||'—'}}</dd></div><div><dt>Registrado em</dt><dd>{{dateTime(selected.reconciliation?.created_at)}}</dd></div></dl>
              <p class="reconcile-reason">{{selected.reconciliation?.reason}}</p>
              <div class="actions"><button class="button outline" @click="navigate('finance')">Abrir financeiro<Icon name="arrow" :size="15"/></button><button class="button" v-allow="['financial.reconciliation','reverse']" @click="openUnlink" :disabled="loading"><Icon name="unlink" :size="16"/>Desfazer vínculo</button></div>
            </div>
          </template>
          <template v-else-if="!selected.reconciled">
            <div class="panel-heading reconcile-candidates-heading"><div><h2>Títulos sugeridos</h2><p>Mesmo sentido e vencimento próximo; confira valor e referência.</p></div><span class="count">{{suggestions.length}}</span></div>
            <div v-if="suggestionBusy" class="loading-line"><Icon name="loading"/>Buscando títulos compatíveis...</div>
            <div v-else-if="suggestionError" class="message error" role="alert">{{suggestionError}} <button class="text-button" @click="loadSuggestions">Tentar novamente</button></div>
            <div v-else-if="suggestions.length" class="reconcile-candidates">
              <article v-for="candidate in suggestions" :key="candidate.title_id" class="reconcile-candidate">
                <div class="reconcile-candidate-main"><strong>{{candidate.description}}</strong><span class="money">{{money(candidate.amount_cents)}}</span></div>
                <div class="reconcile-candidate-meta"><span>Vencimento {{date(candidate.date)}} · {{candidate.difference_days===0?'mesma data':`${candidate.difference_days} dia(s) de diferença`}}</span><button class="button small outline" v-allow="['financial.reconciliation','edit']" @click="openLink(candidate)" :disabled="loading"><Icon name="link" :size="14"/>Conferir vínculo</button></div>
              </article>
            </div>
            <EmptyState v-else title="Nenhum título sugerido" text="Você pode procurar outro título de mesmo valor e sentido, ou cadastrá-lo no Financeiro." icon="reconcile"/>
            <div class="reconcile-manual"><button class="button outline" v-allow="['financial.reconciliation','edit']" @click="openLink()" :disabled="loading"><Icon name="search" :size="16"/>Escolher outro título</button><small>Uma sugestão nunca confirma o vínculo automaticamente.</small></div>
          </template>
        </template>
        <EmptyState v-else title="Selecione um movimento" text="Escolha uma linha do extrato para conferir sua origem e os títulos relacionados." icon="reconcile"/>
      </section>
    </div>

    <BankAllocation v-if="allocationBank" :bank="allocationBank" @close="allocationBank=null"/>
    <BaseModal v-if="show" :title="mode==='link'?'Conferir vínculo bancário':'Desfazer vínculo bancário'" :subtitle="`${context.name} · ${periodLabel(context.period)}`" @close="close">
      <div class="context-notice"><Icon name="building"/><span>Empresa: <strong>{{context.name}}</strong> · {{periodLabel(context.period)}}</span></div>
      <div v-if="error" class="message error" role="alert">{{error}}</div>
      <div class="reconcile-modal-summary"><div><strong>{{transaction.description}}</strong><small>{{date(transaction.date)}} · {{transaction.bank_account}}</small></div><strong class="money" :class="transaction.amount_cents>0?'positive':'negative'">{{money(transaction.amount_cents)}}</strong></div>
      <form id="reconcile-form" :data-unsaved="isDirty?'true':'false'" @submit.prevent="save">
        <template v-if="mode==='link'">
          <div v-if="titlesBusy" class="loading-line"><Icon name="loading"/>Carregando títulos da empresa...</div>
          <div v-if="titleError" class="message error" role="alert">{{titleError}}</div>
          <label>Título a vincular *<select v-model.number="form.title_id" required :disabled="titlesBusy||!!titleError"><option value="">Selecione um título</option><option v-for="title in compatibleTitles" :key="title.id" :value="title.id">{{title.document?`${title.document} · `:''}}{{title.description}} · {{date(title.due_date)}} · {{money(title.amount_cents)}}</option></select><small>São exibidos títulos desta empresa com mesmo valor total e sentido do extrato.</small></label>
          <p v-if="!titlesBusy&&!titleError&&!compatibleTitles.length" class="message warning">Não há título compatível. Feche esta janela e confira ou cadastre o título no Financeiro.</p>
          <dl v-if="chosenTitle" class="reconcile-facts"><div><dt>Cliente / fornecedor</dt><dd>{{chosenTitle.partner_name||'Não informado'}}</dd></div><div><dt>Saldo financeiro atual</dt><dd>{{money(chosenTitle.balance_cents)}}</dd></div></dl>
        </template>
        <div v-else class="message warning">O vínculo com <strong>{{transaction.reconciliation?.title_description||`título ${transaction.reconciliation?.title_id}`}}</strong> será removido. Baixas financeiras já registradas permanecem inalteradas.</div>
        <label>{{mode==='link'?'Justificativa da conferência':'Motivo para desfazer'}} *<textarea v-model="form.reason" rows="3" maxlength="1000" required :placeholder="mode==='link'?'Registre o que foi conferido no extrato e no título.':'Explique por que o vínculo precisa ser desfeito.'"/></label>
        <p class="reconcile-note"><Icon name="info" :size="16"/>{{mode==='link'?'Este vínculo não registra baixa nem gera lançamento contábil.':'A justificativa e o vínculo anterior ficam preservados no histórico.'}}</p>
      </form>
      <template #footer><span class="footer-hint"><Icon name="shield" :size="15"/>Conferência registrada por usuário e data.</span><div class="actions"><button class="button" @click="close" :disabled="busy">Cancelar</button><button class="button" :class="mode==='link'?'primary':'danger'" type="submit" form="reconcile-form" :disabled="busy||(mode==='link'&&(titlesBusy||!chosenTitle||!!titleError))"><Icon :name="busy?'loading':mode==='link'?'link':'unlink'"/>{{mode==='link'?'Confirmar vínculo':'Desfazer vínculo'}}</button></div></template>
    </BaseModal>
  </div>
</template>
