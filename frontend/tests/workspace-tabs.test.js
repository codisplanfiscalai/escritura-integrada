import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {createSSRApp} from 'vue';
import {renderToString} from '@vue/server-renderer';
import {parse, compileScript} from '@vue/compiler-sfc';
import {OVERVIEW_TAB_ID, removeWorkspaceTab} from '../src/lib/workspace-tabs.js';

test('Visão geral é permanente mesmo quando o fechamento é chamado diretamente', () => {
  const tabs = [OVERVIEW_TAB_ID, 'documents', 'companies'];
  assert.equal(removeWorkspaceTab(tabs, OVERVIEW_TAB_ID), tabs);
  assert.equal(removeWorkspaceTab(tabs, 'missing'), tabs);
  assert.deepEqual(removeWorkspaceTab(tabs, 'documents'), [OVERVIEW_TAB_ID, 'companies']);
  assert.deepEqual(tabs, [OVERVIEW_TAB_ID, 'documents', 'companies']);
  assert.deepEqual(removeWorkspaceTab([OVERVIEW_TAB_ID], OVERVIEW_TAB_ID), [OVERVIEW_TAB_ID]);
});

test('a faixa apresenta guia fixa sem fechar, outras com fechar e setas acessíveis', async () => {
  const file = new URL('../src/components/WorkspaceTabs.vue', import.meta.url);
  const {descriptor, errors} = parse(await readFile(file, 'utf8'), {filename: file.pathname});
  assert.deepEqual(errors, []);
  const compiled = compileScript(descriptor, {id: 'workspace-tabs-test', inlineTemplate: true});
  const require = createRequire(import.meta.url);
  const vue = pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
  const helper = new URL('../src/lib/workspace-tabs.js', import.meta.url).href;
  const code = compiled.content.replace(/from ['"]vue['"]/g, `from ${JSON.stringify(vue)}`)
    .replace(/import Icon from ['"]\.\/Icon.vue['"];?/, 'const Icon = {render: () => null};')
    .replace(/from ['"]\.\.\/lib\/workspace-tabs.js['"]/g, `from ${JSON.stringify(helper)}`);
  const component = (await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;
  const html = await renderToString(createSSRApp(component, {
    tabs: [{id: OVERVIEW_TAB_ID, label: 'Visão geral'}, {id: 'companies', label: 'Empresas'}],
    activeId: OVERVIEW_TAB_ID,
  }));
  assert.doesNotMatch(html, /Fechar guia Visão geral/);
  assert.match(html, /aria-label="Fechar guia Empresas"/);
  assert.match(html, /aria-label="Mostrar guias anteriores"/);
  assert.match(html, /aria-label="Mostrar próximas guias"/);
  assert.match(html, /aria-keyshortcuts="Shift\+Delete"/);
  assert.equal((html.match(/role="tab"/g) || []).length, 2);
  assert.equal((html.match(/aria-selected="true"/g) || []).length, 1);
});

async function closeOthersHarness({tabs = [OVERVIEW_TAB_ID, 'documents'], answer = true, confirming = false} = {}) {
  const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8');
  const start = source.indexOf('async function closeOtherTabs(){');
  const end = source.indexOf('\nasync function ', start + 1);
  assert.ok(start >= 0 && end > start, 'Test the actual application handler');
  const state = {tab: 'documents', editor: {name: 'Rascunho não salvo'}, confirm: confirming ? {} : null};
  const openTabs = {value: tabs}, workspaceKey = {value: 0}, prompts = [];
  const ask = async options => {prompts.push(options); return answer;};
  const harness = new Function('ask', 'state', 'openTabs', 'workspaceKey', 'OVERVIEW_TAB_ID', `
    let navigationId = 7;
    ${source.slice(start, end)}
    return {closeOtherTabs, navigationId: () => navigationId};
  `)(ask, state, openTabs, workspaceKey, OVERVIEW_TAB_ID);
  return {...harness, state, openTabs, workspaceKey, prompts};
}

test('cancelar fechamento coletivo mantém todas as guias, edição e cache intactos', async () => {
  const h = await closeOthersHarness({answer: false});
  const editor = h.state.editor, tabs = h.openTabs.value;
  await h.closeOtherTabs();
  assert.equal(h.prompts.length, 1);
  assert.match(h.prompts[0].message, /não salvos.*descartados/);
  assert.equal(h.openTabs.value, tabs);
  assert.equal(h.state.tab, 'documents');
  assert.equal(h.state.editor, editor);
  assert.equal(h.workspaceKey.value, 0);
  assert.equal(h.navigationId(), 7);
});

test('confirmar mantém Visão geral, descarta cache e invalida navegação pendente', async () => {
  const h = await closeOthersHarness();
  await h.closeOtherTabs();
  assert.equal(h.prompts.length, 1);
  assert.deepEqual(h.openTabs.value, [OVERVIEW_TAB_ID]);
  assert.equal(h.state.tab, OVERVIEW_TAB_ID);
  assert.equal(h.state.editor, null);
  assert.equal(h.workspaceKey.value, 1);
  assert.equal(h.navigationId(), 8);
  await h.closeOtherTabs();
  assert.equal(h.prompts.length, 1, 'Repeated double clicks on the sole permanent tab do nothing');
});

test('não substitui confirmação já aberta nem pergunta quando não há outras guias', async () => {
  for (const options of [{tabs: [OVERVIEW_TAB_ID]}, {confirming: true}]) {
    const h = await closeOthersHarness(options);
    await h.closeOtherTabs();
    assert.equal(h.prompts.length, 0);
    assert.equal(h.workspaceKey.value, 0);
  }
});

test('navegação assíncrona antiga não reabre uma guia após o fechamento confirmado', async () => {
  const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8');
  const navigateCode = source.slice(source.indexOf('async function navigate(id){'), source.indexOf('\nstate.navigate=navigate;'));
  const start = source.indexOf('async function closeOtherTabs(){');
  const closeCode = source.slice(start, source.indexOf('\nasync function ', start + 1));
  const state = {tab: 'documents', companyId: 1, module: 'fiscal', editor: null, confirm: null, contextBusy: false};
  const openTabs = {value: [OVERVIEW_TAB_ID, 'documents']};
  let finishActivation;
  const activation = new Promise(resolve => {finishActivation = resolve;});
  const h = new Function('state', 'permittedMenus', 'activate', 'ask', 'openTabs', 'workspaceKey', 'searchOpen', 'notify', 'OVERVIEW_TAB_ID', `
    let navigationId = 0;
    ${navigateCode}
    ${closeCode}
    return {navigate, closeOtherTabs};
  `)(state, {value: [{id: 'journal', module: 'accounting'}]}, () => activation, async () => true, openTabs, {value: 0}, {value: false}, () => {}, OVERVIEW_TAB_ID);
  const pending = h.navigate('journal');
  await h.closeOtherTabs();
  finishActivation(true);
  await pending;
  assert.equal(state.tab, OVERVIEW_TAB_ID);
  assert.deepEqual(openTabs.value, [OVERVIEW_TAB_ID]);
});

async function scrollHarness() {
  const source = await readFile(new URL('../src/components/WorkspaceTabs.vue', import.meta.url), 'utf8');
  const {descriptor} = parse(source);
  const props = {tabs: ['dashboard', 'documents', 'companies', 'reports'].map(id => ({id})), activeId: 'dashboard', locked: false};
  const events = [], callbacks = {}, watchers = [];
  const document = {activeElement: null, body: {closest: () => null}};
  const emit = (...args) => events.push(args);
  const api = new Function('defineProps', 'defineEmits', 'ref', 'watch', 'nextTick', 'onMounted', 'onBeforeUnmount', 'ResizeObserver', 'document', 'OVERVIEW_TAB_ID', `
    ${descriptor.scriptSetup.content.replace(/^import .*;\n/gm, '')}
    return {viewport, track, canGoBack, canGoForward, scrollTabs, revealTab, keyboard, closeTab};
  `)(() => props, () => emit, value => ({value}), (...args) => watchers.push(args), () => Promise.resolve(), fn => {callbacks.mount = fn;}, fn => {callbacks.unmount = fn;}, class {
    constructor(fn) {callbacks.resize = fn;}
    observe() {}
    disconnect() {callbacks.disconnected = true;}
  }, document, OVERVIEW_TAB_ID);
  let position = 0, width = 180;
  const viewport = {
    get clientWidth() {return width;},
    get scrollWidth() {return props.tabs.length * 100;},
    get scrollLeft() {return position;},
    set scrollLeft(value) {position = Math.max(0, Math.min(value, this.scrollWidth - width));},
    getBoundingClientRect: () => ({left: 0, right: width}),
    scrollBy({left}) {this.scrollLeft += left;},
  };
  const buttons = props.tabs.map((tab, index) => {
    const button = {dataset: {tabId: tab.id}, focus() {callbacks.focused = tab.id; document.activeElement = button;}};
    button.parentElement = {
      getBoundingClientRect: () => ({left: index * 100 - position, right: (index + 1) * 100 - position}),
      contains: element => element === button || element === button.closeButton,
      querySelector: () => button,
    };
    button.closest = () => button.parentElement;
    button.closeButton = {closest: () => button.parentElement};
    return button;
  });
  api.viewport.value = viewport;
  api.track.value = {querySelectorAll: () => buttons, contains: element => buttons.some(button => button.parentElement.contains(element))};
  callbacks.mount();
  return {...api, props, callbacks, events, viewport, document, buttons, watchers, resize(value) {width = value; viewport.scrollLeft = position; callbacks.resize();}};
}

test('controles estreitos alcançam as duas extremidades em cliques repetidos e atualizam no resize', async () => {
  const h = await scrollHarness();
  assert.equal(h.canGoBack.value, false);
  assert.equal(h.canGoForward.value, true);
  h.scrollTabs(1);
  assert.ok(h.viewport.scrollLeft > 0);
  for (let i = 0; i < 10; i++) h.scrollTabs(1);
  assert.equal(h.viewport.scrollLeft, 220);
  assert.equal(h.canGoForward.value, false);
  for (let i = 0; i < 10; i++) h.scrollTabs(-1);
  assert.equal(h.viewport.scrollLeft, 0);
  assert.equal(h.canGoBack.value, false);
  h.props.activeId = 'reports';
  h.resize(150);
  assert.equal(h.viewport.scrollLeft, 250, 'Resize reveals the active tab');
  h.resize(500);
  assert.equal(h.canGoForward.value, false);
  assert.equal(h.canGoBack.value, false);
  h.callbacks.unmount();
  assert.equal(h.callbacks.disconnected, true);
});

test('Home/End e setas percorrem guias; Delete nunca fecha Visão geral', async () => {
  const h = await scrollHarness();
  const press = async (key, id, shiftKey = false) => {
    let prevented = false;
    h.keyboard({key, shiftKey, preventDefault() {prevented = true;}}, id);
    await Promise.resolve();
    assert.equal(prevented, true);
  };
  await press('End', OVERVIEW_TAB_ID);
  assert.equal(h.callbacks.focused, 'reports');
  assert.equal(h.viewport.scrollLeft, 220);
  await press('Home', 'reports');
  assert.equal(h.callbacks.focused, OVERVIEW_TAB_ID);
  assert.equal(h.viewport.scrollLeft, 0);
  await press('ArrowLeft', OVERVIEW_TAB_ID);
  assert.equal(h.callbacks.focused, 'reports');
  await press('ArrowRight', 'reports');
  assert.equal(h.callbacks.focused, OVERVIEW_TAB_ID);
  await press('Delete', OVERVIEW_TAB_ID);
  assert.deepEqual(h.events, []);
  await press('Delete', OVERVIEW_TAB_ID, true);
  assert.deepEqual(h.events, [['close-others']]);
  await press('Delete', 'documents');
  assert.deepEqual(h.events.at(-1), ['close', 'documents']);
  h.props.locked = true;
  const count = h.events.length;
  await press('Delete', 'companies');
  assert.equal(h.events.length, count);
});

test('fechamento entre módulos restaura foco após o X desabilitado perder foco durante activate', async () => {
  for (const userMovedFocus of [false, true]) {
    const h = await scrollHarness();
    h.props.activeId = 'companies';
    h.document.activeElement = h.buttons[2].closeButton;
    h.closeTab('companies');
    // Simulate the browser blurring a disabled X while asynchronous activation is pending.
    h.document.activeElement = userMovedFocus ? {closest: () => null} : h.document.body;
    h.props.activeId = 'documents';
    h.props.tabs = h.props.tabs.filter(tab => tab.id !== 'companies');
    await h.watchers[1][1](h.props.tabs.map(tab => tab.id));
    assert.equal(h.callbacks.focused, userMovedFocus ? undefined : 'documents');
  }
});
