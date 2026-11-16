<script setup>
import {ref} from 'vue';
const props=defineProps({id:{type:String,required:true},label:{type:String,required:true},modelValue:{type:String,required:true},tabs:{type:Array,required:true}});
const emit=defineEmits(['update:modelValue']);
const list=ref(null);
function focusTab(id){list.value?.querySelector(`[data-section="${id}"]`)?.focus();}
function keyboard(event,index){
 const last=props.tabs.length-1;
 const next=({ArrowRight:(index+1)%(last+1),ArrowLeft:(index+last)%(last+1),Home:0,End:last})[event.key];
 if(next===undefined)return;
 event.preventDefault();emit('update:modelValue',props.tabs[next].id);focusTab(props.tabs[next].id);
}
defineExpose({focusTab});
</script>
<template>
 <div ref="list" class="section-tabs" role="tablist" :aria-label="label">
  <button v-for="(tab,index) in tabs" :key="tab.id" :id="`${id}-tab-${tab.id}`" type="button" role="tab" :data-section="tab.id" :aria-selected="modelValue===tab.id" :aria-controls="`${id}-panel-${tab.id}`" :tabindex="modelValue===tab.id?0:-1" :class="{active:modelValue===tab.id}" @click="emit('update:modelValue',tab.id)" @keydown="keyboard($event,index)">{{tab.label}}</button>
 </div>
</template>
<style scoped>
.section-tabs{display:flex;flex-wrap:wrap;gap:.25rem;margin:1rem 0;border-bottom:1px solid var(--line)}
button{font:inherit;font-size:.85rem;padding:.65rem .85rem;border:0;border-bottom:3px solid transparent;background:transparent;color:var(--muted);cursor:pointer;white-space:normal;text-align:left}
button:hover{background:var(--bg)}button.active{color:var(--accent);border-bottom-color:var(--accent);font-weight:600}button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media(max-width:600px){button{flex:1 1 9rem;padding:.6rem}}
</style>
