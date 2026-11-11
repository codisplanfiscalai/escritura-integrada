<script setup>
import {ref, watch, nextTick, onMounted, onBeforeUnmount} from 'vue';
import Icon from './Icon.vue';
import {OVERVIEW_TAB_ID} from '../lib/workspace-tabs.js';

const props = defineProps({tabs: {type: Array, required: true}, activeId: String, locked: Boolean});
const emit = defineEmits(['navigate', 'close', 'close-others']);
const viewport = ref(null), track = ref(null), focusedId = ref(props.activeId);
const canGoBack = ref(false), canGoForward = ref(false);
let observer, pendingFocusCloseId;

function updateScroll() {
  const el = viewport.value;
  if (!el) return;
  canGoBack.value = el.scrollLeft > 1;
  canGoForward.value = el.scrollWidth - el.clientWidth - el.scrollLeft > 1;
}

function tabButton(id) {
  return [...(track.value?.querySelectorAll('[role="tab"]') || [])].find(el => el.dataset.tabId === id);
}

function revealTab(id) {
  const el = viewport.value, tab = tabButton(id)?.parentElement;
  if (!el || !tab) return;
  const area = el.getBoundingClientRect(), rect = tab.getBoundingClientRect();
  if (rect.left < area.left) el.scrollLeft -= area.left - rect.left;
  else if (rect.right > area.right) el.scrollLeft += rect.right - area.right;
  updateScroll();
}

function scrollTabs(direction) {
  const el = viewport.value;
  if (!el) return;
  // Immediate scrolling also makes repeated clicks reliable and respects reduced motion.
  el.scrollBy({left: direction * Math.max(80, el.clientWidth * .7), behavior: 'instant'});
  updateScroll();
}

function focusTab(id) {
  focusedId.value = id;
  tabButton(id)?.focus({preventScroll: true});
  revealTab(id);
}

function closeTab(id) {
  if (id === OVERVIEW_TAB_ID || props.locked) return;
  // A module switch can temporarily disable the focused close button and blur it.
  if (tabButton(id)?.parentElement.contains(document.activeElement)) pendingFocusCloseId = id;
  emit('close', id);
}

function keyboard(event, id) {
  const index = props.tabs.findIndex(tab => tab.id === id);
  let target;
  if (event.key === 'ArrowLeft') target = (index - 1 + props.tabs.length) % props.tabs.length;
  else if (event.key === 'ArrowRight') target = (index + 1) % props.tabs.length;
  else if (event.key === 'Home') target = 0;
  else if (event.key === 'End') target = props.tabs.length - 1;
  else if (event.key === 'Delete') {
    event.preventDefault();
    if (id === OVERVIEW_TAB_ID && event.shiftKey) emit('close-others');
    else closeTab(id);
    return;
  } else return;
  event.preventDefault();
  focusTab(props.tabs[target].id);
}

watch(() => props.activeId, async id => {
  focusedId.value = id;
  await nextTick();
  revealTab(id);
});
watch(() => props.tabs.map(tab => tab.id), async ids => {
  const activeButton = document.activeElement?.closest('.workspace-tab')?.querySelector('[role="tab"]');
  const pendingRemoved = pendingFocusCloseId && !ids.includes(pendingFocusCloseId);
  const restoreFocus = (activeButton && !ids.includes(activeButton.dataset.tabId)) ||
    (pendingRemoved && (document.activeElement === document.body || track.value?.contains(document.activeElement)));
  if (pendingRemoved) pendingFocusCloseId = null;
  if (!ids.includes(focusedId.value)) focusedId.value = props.activeId;
  await nextTick();
  if (restoreFocus) focusTab(props.activeId);
  revealTab(props.activeId);
  updateScroll();
});
onMounted(() => {
  observer = new ResizeObserver(() => {revealTab(props.activeId); updateScroll();});
  observer.observe(viewport.value);
  observer.observe(track.value);
  revealTab(props.activeId);
});
onBeforeUnmount(() => observer?.disconnect());
</script>

<template>
  <div class="workspace-tabs">
    <button class="tabs-scroll-button" type="button" aria-label="Mostrar guias anteriores" title="Mostrar guias anteriores" :disabled="!canGoBack" @click="scrollTabs(-1)"><Icon name="left" :size="14"/></button>
    <div ref="viewport" class="workspace-tabs-viewport" @scroll.passive="updateScroll">
      <div ref="track" class="workspace-tabs-track" role="tablist" aria-label="Guias abertas">
        <div v-for="tab in tabs" :key="tab.id" class="workspace-tab" role="presentation" :class="{selected: activeId === tab.id, permanent: tab.id === OVERVIEW_TAB_ID}">
          <button :id="`workspace-tab-${tab.id}`" type="button" role="tab" :data-tab-id="tab.id" :aria-selected="activeId === tab.id" aria-controls="workspace-panel" :tabindex="focusedId === tab.id ? 0 : -1" :title="tab.id === OVERVIEW_TAB_ID ? 'Guia fixa. Duplo clique ou Shift+Delete para fechar as outras guias.' : tab.label" :aria-keyshortcuts="tab.id === OVERVIEW_TAB_ID ? 'Shift+Delete' : 'Delete'" @focus="focusedId = tab.id; revealTab(tab.id)" @keydown="keyboard($event, tab.id)" @click="emit('navigate', tab.id)" @dblclick="tab.id === OVERVIEW_TAB_ID && emit('close-others')">
            <Icon :name="tab.icon" :size="15"/><span>{{tab.label}}</span>
          </button>
          <button v-if="tab.id !== OVERVIEW_TAB_ID" type="button" class="tab-close" :disabled="locked" :tabindex="focusedId === tab.id ? 0 : -1" :aria-label="`Fechar guia ${tab.label}`" @focus="revealTab(tab.id)" @click="closeTab(tab.id)"><Icon name="close" :size="12"/></button>
        </div>
      </div>
    </div>
    <button class="tabs-scroll-button" type="button" aria-label="Mostrar próximas guias" title="Mostrar próximas guias" :disabled="!canGoForward" @click="scrollTabs(1)"><Icon name="right" :size="14"/></button>
    <slot/>
  </div>
</template>
