<script setup>
import {computed,ref} from 'vue';
import {accountOptions} from '../lib/account-options';
defineOptions({inheritAttrs:false});
const props=defineProps({modelValue:{type:[String,Number],default:''},accounts:{type:Array,default:()=>[]},emptyLabel:{type:String,default:'Selecione a conta'}});
const emit=defineEmits(['update:modelValue']);
const query=ref('');
const options=computed(()=>accountOptions(props.accounts,query.value,props.modelValue));
function choose(event){emit('update:modelValue',event.target.value===''?'':Number(event.target.value));}
</script>
<template>
<span class="account-select">
 <select v-bind="$attrs" :value="modelValue" @change="choose"><option value="">{{emptyLabel}}</option><option v-for="a in options.rows" :key="a.id" :value="a.id">{{a.access_code}} · {{a.name}}</option></select>
 <input v-if="accounts.length>200" v-model="query" type="search" @keydown.enter.exact.prevent :aria-label="`Pesquisar ${$attrs['aria-label']||'conta contábil'}`" placeholder="Buscar acesso, classificador ou nome" :disabled="$attrs.disabled"/>
 <small v-if="accounts.length>200">{{options.total}} correspondências. Até 200 opções e a seleção atual exibidas; refine a busca.</small>
</span>
</template>
<style scoped>
.account-select{display:grid;gap:5px;min-width:0}.account-select small{font-size:11px;font-weight:400;line-height:1.4;color:var(--muted,#68758b)}.account-select select,.account-select input{min-width:0;width:100%}
</style>
