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

// KeepAlive navigation and preference changes must not erase a user's custom range.
// Changing company or operational year still resets the view to its new context.
export function useSuggestedDateRange(state, start, end) {
  let previousSuggestion = null;
  return watch(
    () => [state.companyId, state.period.slice(0, 4), state.contextPreferences?.month || ''],
    (next, previous) => {
      const suggestion = suggestedDateRange(next[1], next[2]);
      const contextChanged = !previous || next[0] !== previous[0] || next[1] !== previous[1];
      const untouched = !previousSuggestion ||
        (start.value === previousSuggestion.start && end.value === previousSuggestion.end);
      if (contextChanged || untouched || (!start.value && !end.value)) {
        start.value = suggestion.start;
        end.value = suggestion.end;
      }
      previousSuggestion = suggestion;
    },
    { immediate: true },
  );
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
