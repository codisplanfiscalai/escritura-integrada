import { reactive, computed, watch, onActivated, onDeactivated, onUnmounted, ref } from 'vue';
import { uid } from './format';

export const state = reactive({ session: null, companies: [], companyId: null, module: 'fiscal', navigate: null, period: new Date().toISOString().slice(0,7), refresh: 0, contextBusy: false, loading: true, editor: null, confirm: null, toasts: [], locks: {}, tab: 'dashboard' });
export const company = computed(() => state.companies.find(c => c.id === state.companyId));
export function notify(message, type = 'success') { const id = uid(); state.toasts.push({ id, message, type }); state.toasts = state.toasts.slice(-3); setTimeout(() => { state.toasts = state.toasts.filter(t => t.id !== id); }, type === 'error' ? 9000 : 5000); }
export async function api(path, options = {}) {
  const headers = { ...options.headers };
  if(options.method && options.method!=='GET' && state.companyId){headers['X-Company-Id']=String(state.companyId);headers['X-Period']=state.period;headers['X-Module']=state.module;}
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  if (state.session?.csrf_token) headers['X-CSRF-Token'] = state.session.csrf_token;
  const response = await fetch(`/api${path}`, { credentials: 'same-origin', ...options, headers, body: options.body && !(options.body instanceof FormData) ? JSON.stringify(options.body) : options.body });
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
    await refreshLocks();
  }
  state.loading = false;
}
export async function loadCompanies() { state.companies = rows(await api('/companies')); }
export async function refreshLocks() {
  if (!state.companyId) { state.locks = {}; return; }
  const cid = state.companyId, p = state.period;
  try { const d = await api(scope(`/periods?period=${p}`, cid)); if (cid === state.companyId && p === state.period) state.locks = d; } catch { if (cid === state.companyId && p === state.period) state.locks = {}; }
}
export async function activate(id, period = undefined, module = undefined) {
  if (state.editor) { notify('Conclua ou feche a janela em edição antes de trocar a empresa ou competência.', 'warning'); return false; }
  state.contextBusy = true;
  try {
    const d = await api('/context', { method: 'POST', body: { company_id: id, ...(period?{period}:{}), ...(module?{module}:{}) } });
    state.companyId = d.active_company_id ?? d.company_id ?? id; state.period = d.period ?? period; state.module=d.module||state.module;
    state.session = { ...state.session, ...d, active_company_id: state.companyId, period: state.period };
    state.refresh++; await refreshLocks(); return true;
  } finally { state.contextBusy = false; }
}
export function changed() { state.refresh++; refreshLocks(); }
export const ask = options => new Promise(resolve => { state.confirm = { title: 'Confirmar ação', confirmLabel: 'Confirmar', ...options, resolve }; });
export function answer(value) { const c = state.confirm; state.confirm = null; c?.resolve(value); }
export function useResource(load, initial = []) {
  const data = ref(initial), loading = ref(false), error = ref(''); let seq = 0, alive = true, active = true;
  async function reload() {
    if(!active)return;
    const n = ++seq, context = `${state.companyId}:${state.module}:${state.period}`; loading.value = true; error.value = '';
    try { const d = await load(); if (alive && n === seq && context === `${state.companyId}:${state.module}:${state.period}`) data.value = d; }
    catch(e) { if (alive && n === seq && context === `${state.companyId}:${state.module}:${state.period}`) error.value = e.message; }
    finally { if (alive && n === seq) loading.value = false; }
  }
  watch(() => [state.companyId, state.period, state.refresh, state.module], (next, previous) => { if (!previous || next[0] !== previous[0] || next[1] !== previous[1]) data.value = JSON.parse(JSON.stringify(initial)); reload(); }, { immediate: true });
  onActivated(()=>{active=true;reload();}); onDeactivated(()=>{active=false;seq++;}); onUnmounted(() => { alive = false; seq++; });
  return { data, loading, error, reload };
}

if (typeof window !== 'undefined') {
  window.escrituraHasUnsavedChanges = () => Boolean(state.editor || state.confirm);
  window.addEventListener('beforeunload', event => { if (state.editor) { event.preventDefault(); event.returnValue = ''; } });
}

export function can(routine,action='read'){return state.session?.user?.role==='admin'||state.session?.permissions?.[routine]?.includes(action)||false;}
export function allowedApi(routine,path,empty=[]){return can(routine)?api(path):Promise.resolve(empty);}
export function writable(routine,action='create'){return can(routine,action)&&!state.locks[routine.split('.')[0]]?.closed;}
export function navigate(id){return state.navigate?.(id);}
export const moduleNames={fiscal:'Fiscal',accounting:'Contábil',financial:'Financeiro',social:'Social',system:'Sistema'};
