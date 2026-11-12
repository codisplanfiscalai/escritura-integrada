import { reactive, computed, watch, onActivated, onDeactivated, onUnmounted, ref } from 'vue';
import { uid } from './format';
import { normalizeContextPreferences, readContextPreferences, writeContextPreferences } from './context-preferences.js';

export const state = reactive({ session: null, companies: [], companyId: null, module: 'fiscal', navigate: null, period: new Date().toISOString().slice(0,7), refresh: 0, contextBusy: false, contextPreferences: { year: '', month: '' }, loading: true, editor: null, confirm: null, toasts: [], locks: {}, yearLocks: {}, tab: 'dashboard' });
export const company = computed(() => state.companies.find(c => c.id === state.companyId));
export const captureContext=()=>({companyId:state.companyId,year:state.period.slice(0,4),module:state.module});
export const contextMatches=c=>c.companyId===state.companyId&&c.year===state.period.slice(0,4)&&c.module===state.module;
export function notify(message, type = 'success') { const id = uid(); state.toasts.push({ id, message, type }); state.toasts = state.toasts.slice(-3); setTimeout(() => { state.toasts = state.toasts.filter(t => t.id !== id); }, type === 'error' ? 9000 : 5000); }
export async function api(path, options = {}) {
  if(options.context&&(!contextMatches(options.context)||state.contextBusy))throw new Error('O contexto mudou. Confira a empresa, o módulo e o exercício antes de continuar.');
  const {context:requestContext,...fetchOptions}=options;
  const headers = { ...options.headers };
  if(options.method && options.method!=='GET' && state.companyId){headers['X-Company-Id']=String(state.companyId);headers['X-Year']=state.period.slice(0,4);headers['X-Module']=state.module;}
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  if (state.session?.csrf_token) headers['X-CSRF-Token'] = state.session.csrf_token;
  const response = await fetch(`/api${path}`, { credentials: 'same-origin', ...fetchOptions, headers, body: options.body && !(options.body instanceof FormData) ? JSON.stringify(options.body) : options.body });
  if (!response.ok) {
    let data; try { data = await response.json(); } catch { data = {}; }
    const detail = data.detail || data.message || `Não foi possível concluir a operação (${response.status}).`;
    const text = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(e => `${e.loc?.slice(1).join('.') || 'Campo'}: ${e.msg}`).join('\n') : detail.message || JSON.stringify(detail);
    const error = new Error(text); error.status = response.status; error.detail = detail;
    if (response.status === 401 && !path.match(/login|setup|session/)) state.session = { ...state.session, authenticated: false, user: null };
    if (response.status === 401 && !path.match(/login|setup|session/)) notify('A sessão foi encerrada. Entre novamente para continuar.', 'warning');
    throw error;
  }
  if (response.status === 204) return null;
  return response.json();
}
export const scope = (path, id = state.companyId) => `/companies/${id}${path}`;
export const rows = data => Array.isArray(data) ? data : data?.items || data?.rows || data?.entries || [];
export async function refreshSession() {
  state.session = await api('/session');
  if (state.session.authenticated) {
    await loadCompanies(); state.companyId = state.session.active_company_id || null;
    state.period = state.session.period || state.period; state.module=state.session.module||'fiscal';
    state.contextPreferences = readContextPreferences(contextStorage(), state.session.user.id);
    await refreshLocks();
  } else { state.contextPreferences = normalizeContextPreferences(); }
  state.loading = false;
}
export async function loadCompanies() { state.companies = rows(await api('/companies')); }
export async function refreshLocks() {
  if (!state.companyId) { state.locks = {}; state.yearLocks = {}; return; }
  const cid = state.companyId, p = state.period;
  const all={};
  await Promise.all([
    (async()=>{try{const d=await api(scope(`/periods?period=${p}`,cid));if(cid===state.companyId&&p===state.period)state.locks=d;}catch{if(cid===state.companyId&&p===state.period)state.locks={};}})(),
    ...['fiscal','accounting','financial','social'].filter(m=>can(m+'.periods')).map(async m=>{
      try{const d=await api(scope(`/exercises?module=${m}&year=${p.slice(0,4)}`,cid));all[m]=Object.fromEntries(d.months.map(x=>[x.period,x]));}catch{all[m]={};}
    })
  ]);
  if(cid===state.companyId&&p===state.period)state.yearLocks=all;
}
export async function activate(id, period = undefined, module = undefined, { useFixedYear = true, year = undefined } = {}) {
  if (state.contextBusy || state.confirm) return false;
  if (state.editor) { notify('Conclua ou feche a janela em edição antes de trocar a empresa ou competência.', 'warning'); return false; }
  const selectedYear = id && !period ? (year ?? (useFixedYear ? state.contextPreferences.year : '')) : '';
  state.contextBusy = true;
  try {
    const d = await api('/context', { method: 'POST', body: { company_id: id, ...(period?{period}:{}), ...(selectedYear?{year:Number(selectedYear)}:{}), ...(module?{module}:{}) } });
    state.companyId = Object.hasOwn(d, 'active_company_id') ? d.active_company_id : (d.company_id ?? id); state.period = d.period ?? period ?? state.period; state.module=d.module||state.module;
    state.session = { ...state.session, ...d, active_company_id: state.companyId, period: state.period };
    if (!state.companyId) state.tab = 'dashboard';
    state.refresh++; await refreshLocks(); return true;
  } finally { state.contextBusy = false; }
}
function contextStorage() { try { return globalThis.sessionStorage; } catch { return null; } }
export function setContextPreferences(value) {
  state.contextPreferences = normalizeContextPreferences(value);
  if (state.session?.user?.id) writeContextPreferences(contextStorage(), state.session.user.id, state.contextPreferences);
}
export async function applyWorkspaceContext({ companyId, year = '', month = '' }) {
  const preferences = normalizeContextPreferences({ year, month });
  if ((year && preferences.year !== String(year)) || (month && preferences.month !== String(month))) throw new Error('Confira o ano (1900 a 2199) e a competência (01 a 12).');
  const id = companyId === '' || companyId == null ? null : Number(companyId);
  if (!await activate(id, undefined, undefined, { useFixedYear: false, year: preferences.year })) return false;
  setContextPreferences(preferences);
  return true;
}
export function changed() { state.refresh++; refreshLocks(); }
export const ask = options => new Promise(resolve => { state.confirm = { title: 'Confirmar ação', confirmLabel: 'Confirmar', ...options, resolve }; });
export function answer(value) { const c = state.confirm; state.confirm = null; c?.resolve(value); }
export function useResource(load, initial = []) {
  const data = ref(initial), loading = ref(false), error = ref(''); let seq = 0, alive = true, active = true, timer = null;
  async function reload() {
    clearTimeout(timer);timer=null;
    if(!active||state.contextBusy)return;
    const n = ++seq, context = `${state.companyId}:${state.module}:${state.period}`; loading.value = true; error.value = '';
    try { const d = await load(); if (alive && n === seq && context === `${state.companyId}:${state.module}:${state.period}`) data.value = d; }
    catch(e) { if (alive && n === seq && context === `${state.companyId}:${state.module}:${state.period}`) error.value = e.message; }
    finally { if (alive && n === seq) loading.value = false; }
  }
  // Defer automatic loads until the outgoing KeepAlive screen has deactivated.
  function scheduleReload(){clearTimeout(timer);if(!active||!alive)return;loading.value=true;if(state.contextBusy)return;timer=setTimeout(()=>{timer=null;reload();},0);}
  watch(() => [state.companyId, state.period, state.refresh, state.module, state.contextBusy], (next, previous) => {
    seq++;
    if (!previous || next[0] !== previous[0] || next[1] !== previous[1]) data.value = JSON.parse(JSON.stringify(initial));
    scheduleReload();
  }, { immediate: true });
  onActivated(()=>{active=true;scheduleReload();});
  onDeactivated(()=>{active=false;seq++;clearTimeout(timer);});
  onUnmounted(() => { alive = false;seq++;clearTimeout(timer); });
  return { data, loading, error, reload };
}

if (typeof window !== 'undefined') {
  window.escrituraHasUnsavedChanges = () => Boolean(state.editor || state.confirm);
  window.addEventListener('beforeunload', event => { if (state.editor) { event.preventDefault(); event.returnValue = ''; } });
}

export function can(routine,action='read'){return state.session?.user?.role==='admin'||state.session?.permissions?.[routine]?.includes(action)||false;}
export function allowedApi(routine,path,empty=[]){return can(routine)?api(path):Promise.resolve(empty);}
export function writable(routine,action='create',period=null){return can(routine,action)&&(!state.session?.operational_settings?.enforce_period_locks||!period||!state.yearLocks[routine.split('.')[0]]?.[period]?.closed);}
export function navigate(id){return state.navigate?.(id);}
export const moduleNames={fiscal:'Fiscal',accounting:'Contábil',financial:'Financeiro',social:'Social',auditor:'Auditor Fiscal',system:'Sistema'};
