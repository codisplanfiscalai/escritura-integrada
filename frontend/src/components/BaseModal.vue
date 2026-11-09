<script setup>
import {ref,onMounted,onUnmounted,nextTick} from 'vue';
import Icon from './Icon.vue';
import { uid } from '../lib/format';
const props=defineProps({title:String,subtitle:String,wide:Boolean,narrow:Boolean});
const emit=defineEmits(['close']);const el=ref(null);const titleId=`modal-${uid()}`;let before;
function focusable(node){return node.getClientRects().length>0&&node.tabIndex>=0&&!node.matches(':disabled,[hidden],[aria-hidden="true"]')&&!node.closest('[hidden],[aria-hidden="true"]');}
function firstVisible(selector){return [...el.value.querySelectorAll(selector)].find(focusable);}
function keyboard(e){
 if([...document.querySelectorAll('.modal-dialog')].at(-1)!==el.value)return;
 if(e.key==='Escape'){e.preventDefault();e.stopPropagation();emit('close');}
 if(e.key==='Tab'){
  const nodes=[...el.value.querySelectorAll('button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),a[href],[tabindex="0"]')].filter(focusable);
  if(!nodes.length)return;const first=nodes[0],last=nodes.at(-1);
  if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
  else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
 }
 if(e.altKey&&e.key.toLowerCase()==='n'){e.preventDefault();el.value.querySelector('[data-save-new]')?.click();}
 if(e.ctrlKey&&e.key==='Enter'){e.preventDefault();el.value.querySelector('[data-add-line]')?.click();}
 if(e.altKey&&e.key.toLowerCase()==='s'){e.preventDefault();el.value.querySelector('form')?.requestSubmit();}
}
onMounted(async()=>{before=document.activeElement;document.addEventListener('keydown',keyboard,true);await nextTick();(firstVisible('[autofocus]')||firstVisible('input,textarea')||firstVisible('select')||firstVisible('.modal-footer button')||firstVisible('.modal-body button')||firstVisible('button'))?.focus();});
onUnmounted(()=>{document.removeEventListener('keydown',keyboard,true);if(before?.isConnected)before.focus();});
</script>
<template><Teleport to="body"><div class="modal-overlay" @mousedown.self="emit('close')"><section ref="el" class="modal-dialog" :class="{wide,narrow}" role="dialog" aria-modal="true" :aria-labelledby="titleId"><header class="modal-header"><div><h2 :id="titleId">{{title}}</h2><p v-if="subtitle">{{subtitle}}</p></div><button class="icon-button" @click="emit('close')" aria-label="Fechar janela"><Icon name="close"/></button></header><div class="modal-body"><slot/></div><footer v-if="$slots.footer" class="modal-footer"><slot name="footer"/></footer></section></div></Teleport></template>
