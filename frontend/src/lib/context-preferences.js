import { watch } from 'vue';

export const COMPETENCE_MONTHS = [
  'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
].map((label, index) => ({ value: String(index + 1).padStart(2, '0'), label }));

export function validContextYear(value) {
  return /^\d{4}$/.test(String(value)) && Number(value) >= 1900 && Number(value) <= 2199;
}
export function normalizeContextPreferences(value = {}) {
  return {
    year: validContextYear(value?.year) ? String(value.year) : '',
    month: /^(0[1-9]|1[0-2])$/.test(String(value?.month)) ? String(value.month) : '',
  };
}

// Only a UI default. Never replace the operational month or change posting rules.
export function suggestedDateRange(year, month = '') {
  if (!validContextYear(year)) return { start: '', end: '' };
  const normalized = normalizeContextPreferences({ month }).month;
  if (!normalized) return { start: `${year}-01-01`, end: `${year}-12-31` };
  const lastDay = new Date(Date.UTC(Number(year), Number(normalized), 0)).getUTCDate();
  return { start: `${year}-${normalized}-01`, end: `${year}-${normalized}-${lastDay}` };
}

// Suggestions never overwrite a manually changed or cleared filter. Context changes
// reset it; KeepAlive navigation and refreshes do not. The operational period is read-only.
export function useSuggestedValues(state, fields, suggest) {
  let previousSuggestion = null;
  return watch(
    () => [state.companyId, state.period?.slice(0, 4) || '', state.contextPreferences?.month || '', state.period?.slice(5) || ''],
    (next, previous) => {
      const suggestion = next[0] ? suggest(next[1], next[2], next[3]) : Object.fromEntries(Object.keys(fields).map(key => [key, '']));
      const contextChanged = !previous || next[0] !== previous[0] || next[1] !== previous[1];
      const untouched = !previousSuggestion || Object.keys(fields).every(key => fields[key].value === previousSuggestion[key]);
      if (contextChanged || untouched) for (const key of Object.keys(fields)) fields[key].value = suggestion[key];
      previousSuggestion = suggestion;
    },
    { immediate: true, flush: 'sync' },
  );
}
export function useSuggestedDateRange(state, start, end) {
  return useSuggestedValues(state, {start, end}, (year, month) => suggestedDateRange(year, month));
}
export function useSuggestedMonth(state, month, operationalFallback = true) {
  return useSuggestedValues(state, {month}, (_, fixed, operational) => ({month: fixed || (operationalFallback ? operational : '')}));
}
export function useSuggestedCompetence(state, competence) {
  return useSuggestedValues(state, {competence}, (year, fixed, operational) => ({competence: `${year}-${fixed || operational}`}));
}
export function useSuggestedDate(state, date) {
  return useSuggestedValues(state, {date}, (year, fixed, operational) => ({date: `${year}-${fixed || operational}-01`}));
}

export function contextPreferenceKey(userId) {
  return `escritura-context-preferences:${userId}`;
}
export function readContextPreferences(storage, userId) {
  try { return normalizeContextPreferences(JSON.parse(storage?.getItem(contextPreferenceKey(userId)) || '{}')); }
  catch { return normalizeContextPreferences(); }
}
export function writeContextPreferences(storage, userId, value) {
  try { storage?.setItem(contextPreferenceKey(userId), JSON.stringify(normalizeContextPreferences(value))); }
  catch { /* Private browsing/storage restrictions must not prevent working. */ }
}
