import test from 'node:test';
import assert from 'node:assert/strict';
import { reactive, ref, nextTick, effectScope } from 'vue';
import { COMPETENCE_MONTHS, normalizeContextPreferences, suggestedDateRange, useSuggestedDateRange, useSuggestedMonth, useSuggestedCompetence, useSuggestedDate, readContextPreferences, writeContextPreferences } from '../src/lib/context-preferences.js';

test('competências de 01 a 12 e ano opcional sem valores inválidos', () => {
  assert.deepEqual(COMPETENCE_MONTHS.map(m => m.value), Array.from({length: 12}, (_, i) => String(i + 1).padStart(2, '0')));
  assert.deepEqual(normalizeContextPreferences(), { year: '', month: '' });
  assert.deepEqual(normalizeContextPreferences({year: '2024', month: '02'}), {year: '2024', month: '02'});
  for (const year of ['abc', '1899', '2200', null]) assert.equal(normalizeContextPreferences({year}).year, '');
  for (const month of ['00', '13', '2', null]) assert.equal(normalizeContextPreferences({month}).month, '');
});

test('intervalo mensal inclui último dia exato, bissextos e virada de ano', () => {
  assert.deepEqual(suggestedDateRange('2024', '02'), { start: '2024-02-01', end: '2024-02-29' });
  assert.deepEqual(suggestedDateRange('2000', '02'), { start: '2000-02-01', end: '2000-02-29' });
  assert.equal(suggestedDateRange('2100', '02').end, '2100-02-28');
  assert.equal(suggestedDateRange('2026', '04').end, '2026-04-30');
  assert.equal(suggestedDateRange('2026', '12').end, '2026-12-31');
  assert.deepEqual(suggestedDateRange('2026'), {start: '2026-01-01', end: '2026-12-31'});
  assert.deepEqual(suggestedDateRange(''), {start: '', end: ''});
});

test('preferência é isolada por usuário e armazenamento indisponível não bloqueia', () => {
  const values = new Map();
  const storage = {getItem: key => values.get(key), setItem: (key, value) => values.set(key, value)};
  writeContextPreferences(storage, 1, {year: '', month: '06'});
  assert.deepEqual(readContextPreferences(storage, 1), {year: '', month: '06'});
  assert.deepEqual(readContextPreferences(storage, 2), {year: '', month: ''});
  const blocked = {getItem() {throw new Error('blocked');}, setItem() {throw new Error('blocked');}};
  assert.doesNotThrow(() => writeContextPreferences(blocked, 1, {year:'2026',month:'12'}));
  assert.deepEqual(readContextPreferences(blocked, 1), {year:'',month:''});
});

test('sugestão preenche período, mantém edição manual e não altera competência operacional', async () => {
  const state = reactive({companyId: 1, period: '2024-11', contextPreferences: {year: '', month: '02'}});
  const start = ref(''), end = ref(''), scope = effectScope();
  scope.run(() => useSuggestedDateRange(state, start, end));
  try {
    assert.deepEqual([start.value, end.value], ['2024-02-01', '2024-02-29']);
    state.contextPreferences.month = '04'; await nextTick();
    assert.deepEqual([start.value, end.value], ['2024-04-01', '2024-04-30']);
    start.value = '2024-01-15'; end.value = '2024-05-20';
    state.contextPreferences.month = '06'; await nextTick();
    assert.deepEqual([start.value, end.value], ['2024-01-15', '2024-05-20']);
    state.refresh = 1; state.tab = 'dashboard'; await nextTick();
    assert.equal(start.value, '2024-01-15');
    state.contextPreferences.month = ''; await nextTick();
    assert.equal(start.value, '2024-01-15', 'limpar a preferência não apaga o intervalo editado');
    assert.equal(state.period, '2024-11');
    state.companyId = 2; await nextTick();
    assert.deepEqual([start.value, end.value], ['2024-01-01', '2024-12-31']);
    state.contextPreferences.month = '02'; state.period = '2025-11'; await nextTick();
    assert.deepEqual([start.value, end.value], ['2025-02-01', '2025-02-28']);
  } finally {scope.stop();}
});

test('monthly defaults honor fixed month, keep edits and clear when company is removed',()=>{
 const state=reactive({companyId:1,period:'2026-11',contextPreferences:{month:'09'}}),month=ref(''),annual=ref(''),competence=ref(''),date=ref(''),scope=effectScope();
 scope.run(()=>{useSuggestedMonth(state,month);useSuggestedMonth(state,annual,false);useSuggestedCompetence(state,competence);useSuggestedDate(state,date);});
 try{
  assert.deepEqual([month.value,annual.value,competence.value,date.value],['09','09','2026-09','2026-09-01']);
  month.value='07';competence.value='2026-07';date.value='2026-07-12';state.contextPreferences.month='10';
  assert.deepEqual([month.value,annual.value,competence.value,date.value],['07','10','2026-07','2026-07-12']);
  month.value='';state.contextPreferences.month='12';assert.equal(month.value,'','manual empty filter stays empty');
  state.companyId=2;assert.equal(month.value,'12');assert.equal(competence.value,'2026-12');
  state.contextPreferences.month='';assert.equal(month.value,'11');assert.equal(annual.value,'');
  state.companyId=null;assert.deepEqual([month.value,annual.value,competence.value,date.value],['','','','']);
  state.companyId=1;state.period='2027-01';assert.equal(competence.value,'2027-01');assert.equal(state.period,'2027-01');
 }finally{scope.stop();}
});
test('manually cleared date range survives new suggestions and navigation',()=>{
 const state=reactive({companyId:1,period:'2026-11',contextPreferences:{month:'09'}}),start=ref(''),end=ref(''),scope=effectScope();
 scope.run(()=>useSuggestedDateRange(state,start,end));
 try{start.value='';end.value='';state.contextPreferences.month='08';state.tab='dashboard';assert.deepEqual([start.value,end.value],['','']);state.period='2027-01';assert.deepEqual([start.value,end.value],['2027-08-01','2027-08-31']);}finally{scope.stop();}
});
