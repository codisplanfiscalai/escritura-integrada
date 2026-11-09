<script setup>
import {ref,useId} from 'vue';
import {api,scope,state,can} from '../lib/workspace';
defineOptions({inheritAttrs:false});
const props=defineProps({modelValue:String,direction:{type:String,default:''},date:{type:String,default:''}});
const emit=defineEmits(['update:modelValue']);const options=ref([]),listId=useId();let sequence=0;
async function search(value){const n=++sequence,cid=state.companyId;if(!cid||!can('fiscal.masters'))return;try{const q=new URLSearchParams({search:value||'',direction:props.direction,date:props.date||state.period+'-01'});const r=await api(scope('/cfop-reference?'+q,cid));if(n===sequence&&cid===state.companyId)options.value=r.rows;}catch{options.value=[];}}
function input(event){emit('update:modelValue',event.target.value);search(event.target.value)}
</script>
<template><span class="cfop-input"><input v-bind="$attrs" :value="modelValue" maxlength="4" inputmode="numeric" :list="listId" @input="input" @focus="search(modelValue)"/><datalist :id="listId"><option v-for="r in options" :key="r.code" :value="r.code">{{r.title}}</option></datalist></span></template>
<style scoped>.cfop-input{display:block;min-width:0}.cfop-input input{width:100%}</style>
