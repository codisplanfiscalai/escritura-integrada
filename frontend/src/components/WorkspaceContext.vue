<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue';
import BaseModal from './BaseModal.vue';
import Icon from './Icon.vue';
import { state, company, activate, applyWorkspaceContext, setContextPreferences, notify, navigate, moduleNames } from '../lib/workspace';
import { matchingCompanies, locateCompany } from '../lib/company-selection.js';
import { taxId } from '../lib/format';
import { COMPETENCE_MONTHS, validContextYear } from '../lib/context-preferences.js';

const search = ref(''), clearing = ref(false);
const activeYear = computed(() => state.companyId ? state.period.slice(0, 4) : '');
const matches = computed(() => matchingCompanies(state.companies || [], search.value));
const show = ref(false), draft = ref({ companyId: '', year: '', month: '' }), error = ref('');
const locked = computed(() => clearing.value || state.contextBusy || !!state.editor || !!state.confirm);
const fixed = computed(() => Boolean(state.contextPreferences.year || state.contextPreferences.month));
function open() {
  if (locked.value) {
    if (state.editor) notify('Conclua ou feche a janela em edição antes de trocar o contexto.', 'warning');
    return;
  }
  if (show.value) return;
  draft.value = { companyId: state.companyId || '', ...state.contextPreferences };
  error.value = '';
  search.value = '';
  show.value = true;
}
function close() { if (!state.contextBusy) show.value = false; }
function keyboard(event) {
  if (!['F8', 'F9'].includes(event.key) || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.repeat || !state.session?.authenticated) return;
  event.preventDefault();
  if (typeof document !== 'undefined' && document.querySelector('.modal-dialog') && !show.value) return;
  if (event.key === 'F9') { if (!show.value) void clearContext(); } else open();
}
function locate() {
  const found = locateCompany(state.companies || [], search.value);
  if (found) { draft.value.companyId = found.id; error.value = ''; }
  else error.value = matches.value.length ? 'Selecione uma das empresas encontradas.' : 'Nenhuma empresa encontrada.';
}
async function clearContext() {
  if (locked.value || show.value) return;
  clearing.value = true;
  try {
    if (await applyWorkspaceContext({companyId:'',year:'',month:''})) notify('Empresa, ano e competência removidos do contexto. Os dados foram preservados.');
  } catch (e) { notify(e.message, 'error'); }
  finally { clearing.value = false; }
}
onMounted(() => window.addEventListener('keydown', keyboard));
onUnmounted(() => window.removeEventListener('keydown', keyboard));
async function save() {
  if (locked.value) return;
  error.value = '';
  try {
    if (await applyWorkspaceContext(draft.value)) {
      show.value = false;
      notify(draft.value.companyId ? 'Contexto atualizado. Os períodos continuam editáveis.' : 'Empresa removida do contexto. Os dados foram preservados.');
    }
  } catch (e) { error.value = e.message; }
}
async function changeCompany(event) {
  try { await activate(event.target.value ? Number(event.target.value) : null); }
  catch (e) { notify(e.message, 'error'); }
  finally { event.target.value = state.companyId || ''; }
}
async function changeYear(event) {
  const year = event.target.value.trim();
  if (!validContextYear(year)) {
    notify('Informe um exercício entre 1900 e 2199. Para deixar o ano sem fixação, use Fixar contexto.', 'warning');
  } else {
    try {
      if (await activate(state.companyId, `${year}-${state.period.slice(5)}`) && state.contextPreferences.year) {
        setContextPreferences({ ...state.contextPreferences, year });
      }
    } catch (e) { notify(e.message, 'error'); }
  }
  event.target.value = activeYear.value;
}
</script>

<template>
  <div class="company-switch">
    <span class="company-switch-icon"><Icon name="building" :size="21"/></span>
    <div>
      <label for="active-company">EMPRESA ATIVA</label>
      <select id="active-company" :value="state.companyId || ''" :disabled="locked" @change="changeCompany">
        <option value="">Sem empresa selecionada</option>
        <option v-for="c in state.companies" :key="c.id" :value="c.id">{{c.code}} · {{c.trade_name || c.name}}</option>
      </select>
      <small>{{company ? taxId(company.tax_id) : 'Selecione uma empresa ou pressione F8'}}</small>
    </div>
  </div>
  <div class="period-picker">
    <label for="active-period">{{moduleNames[state.module]}} · EXERCÍCIO</label>
    <input id="active-period" type="text" inputmode="numeric" maxlength="4" placeholder="AAAA" :value="activeYear" :disabled="!state.companyId || locked" @change="changeYear"/>
    <button v-if="state.module !== 'auditor'" class="text-button" :disabled="locked || !state.companyId" @click="navigate(state.module === 'fiscal' ? 'periods' : state.module + '-periods')">Exercícios / meses</button>
  </div>
  <button class="button outline small context-button" :class="{ 'context-fixed': fixed }" :disabled="locked" aria-keyshortcuts="F8" aria-label="Fixar empresa, ano e competência (F8)" title="Fixar ou limpar empresa, ano e competência (F8)" @click="open">
    <Icon name="calendar" :size="15"/><span>Fixar contexto</span><kbd>F8</kbd>
  </button>
  <button class="button outline small context-button" :disabled="locked || show || (!state.companyId && !fixed)" aria-keyshortcuts="F9" aria-label="Limpar empresa, ano e competência (F9)" title="Limpar empresa, ano e competência (F9)" @click="clearContext"><span>Limpar contexto</span><kbd>F9</kbd></button>
  <BaseModal v-if="show" title="Empresa, ano e competência" subtitle="Escolha o contexto de trabalho. A competência apenas sugere o intervalo nas telas de período." narrow @close="close">
    <p v-if="error" class="message error" role="alert">{{error}}</p>
    <form id="workspace-context-form" class="context-form" @submit.prevent="save">
      <label>Buscar empresa por código, nome ou CNPJ<input v-model="search" type="search" :disabled="state.contextBusy" autofocus @keydown.enter.prevent="locate"/></label>
      <button type="button" class="text-button" :disabled="!search || state.contextBusy" @click="locate">Localizar empresa</button>
      <label>Empresa
        <select v-model="draft.companyId" :disabled="state.contextBusy">
          <option value="">Sem empresa selecionada</option>
          <option v-if="draft.companyId && !matches.some(c => c.id === Number(draft.companyId))" :value="draft.companyId">Empresa selecionada · {{draft.companyId}}</option>
          <option v-for="c in matches" :key="c.id" :value="c.id">{{c.code}} · {{c.trade_name || c.name}}</option>
        </select>
      </label>
      <button type="button" class="text-button" :disabled="!draft.companyId || state.contextBusy" @click="draft.companyId = ''">Limpar empresa</button>
      <label>Ano a fixar (opcional)
        <input v-model="draft.year" type="text" inputmode="numeric" maxlength="4" :placeholder="`Sem fixação · exercício atual ${state.period.slice(0, 4)}`" :disabled="state.contextBusy"/>
      </label>
      <button type="button" class="text-button" :disabled="!draft.year || state.contextBusy" @click="draft.year = ''">Deixar ano sem fixação</button>
      <small>Sem fixação, permanece o exercício escolhido para cada empresa e módulo. Os exercícios cadastrados e seus bloqueios continuam valendo.</small>
      <label>Competência a fixar (opcional)
        <select v-model="draft.month" :disabled="state.contextBusy">
          <option value="">Competência livre</option>
          <option v-for="month in COMPETENCE_MONTHS" :key="month.value" :value="month.value">{{month.value}} · {{month.label}}</option>
        </select>
      </label>
      <button type="button" class="text-button" :disabled="!draft.month || state.contextBusy" @click="draft.month = ''">Limpar competência</button>
      <small>O mês usa o ano do exercício ativo para preencher início e fim. Você pode editar as datas na operação, sem alterar esta preferência.</small>
    </form>
    <template #footer>
      <button class="button" :disabled="state.contextBusy" @click="close">Cancelar</button>
      <button class="button primary" form="workspace-context-form" :disabled="state.contextBusy">{{state.contextBusy ? 'Aplicando…' : 'Aplicar contexto'}}</button>
    </template>
  </BaseModal>
</template>

<style scoped>
.context-button { flex: none; white-space: nowrap; gap: 6px; }
.context-button kbd { font: inherit; font-size: 10px; padding: 1px 3px; border: 1px solid #d4e3e8; border-radius: 3px; }
.context-fixed { background: #edf6f5; border-color: #91beb9; }
.context-form { display: flex; flex-direction: column; gap: 10px; }
.context-form > .text-button { align-self: flex-start; }
.context-form > small { color: var(--muted); line-height: 1.6; margin-bottom: 9px; }
@media (max-width: 1200px) { .context-button span { display: none; } }
</style>
