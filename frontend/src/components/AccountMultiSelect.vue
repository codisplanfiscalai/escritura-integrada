<script setup>
import {computed,ref,watch} from 'vue';
import {accountOptions} from '../lib/account-options';
const props=defineProps({modelValue:{type:Array,default:()=>[]},accounts:{type:Array,default:()=>[]},disabled:Boolean});
const emit=defineEmits(['update:modelValue']);
const query=ref(''),panel=ref(null);
watch(()=>props.accounts,()=>{query.value='';if(panel.value)panel.value.open=false;});
const selected=computed(()=>new Set(props.modelValue));
const options=computed(()=>accountOptions(props.accounts,query.value));
const chosen=computed(()=>props.modelValue.map(id=>props.accounts.find(a=>a.id===id)||{id,access_code:id,name:'Conta selecionada'}));
function toggle(id){const ids=new Set(props.modelValue);if(ids.has(id))ids.delete(id);else if(ids.size<500)ids.add(id);emit('update:modelValue',[...ids]);}
function clear(){query.value='';emit('update:modelValue',[]);}
function close(event){if(panel.value)panel.value.open=false;event?.preventDefault();event?.stopPropagation();panel.value?.querySelector('summary')?.focus();}
</script>
<template>
<div class="account-multi">
 <details ref="panel" @keydown.esc="close">
  <summary :aria-disabled="disabled" @click="disabled&&$event.preventDefault()">{{modelValue.length?`${modelValue.length} contas selecionadas`:'Todas as contas'}}<span aria-hidden="true"> ▾</span></summary>
  <div class="account-multi-panel">
   <input v-model="query" type="search" aria-label="Pesquisar contas do relatório" placeholder="Buscar acesso, classificador ou nome" :disabled="disabled" @keydown.enter.prevent/>
   <div class="account-multi-actions"><button type="button" class="text-button" :disabled="disabled||!modelValue.length" @click="clear">Usar todas as contas</button><button type="button" class="text-button" @click="close">Concluir seleção</button></div>
   <p class="account-multi-hint">Selecione uma ou mais contas. Grupos sintéticos incluem suas contas analíticas. Sem seleção, consulta todas.</p>
   <div class="account-multi-list" role="group" aria-label="Contas do relatório">
    <label v-for="a in options.rows" :key="a.id"><input type="checkbox" :checked="selected.has(a.id)" :disabled="disabled||(!selected.has(a.id)&&modelValue.length>=500)" @change="toggle(a.id)"/><span><strong>{{a.access_code}}</strong> · {{a.name}}<small>{{a.classifier}}</small></span></label>
    <p v-if="!options.rows.length">Nenhuma conta encontrada.</p>
   </div>
   <small v-if="options.limited">{{options.total}} correspondências. Exibindo até 200; refine a busca. As seleções anteriores são mantidas.</small>
   <small v-if="modelValue.length>=500">Limite de 500 contas selecionadas. Para o plano inteiro, use Todas as contas.</small>
   <div v-if="chosen.length" class="account-chips" aria-label="Contas selecionadas"><button v-for="a in chosen" :key="a.id" type="button" :disabled="disabled" @click="toggle(a.id)" :aria-label="`Remover ${a.access_code} ${a.name}`">{{a.access_code}} · {{a.name}} ×</button></div>
  </div>
 </details>
 <small v-if="modelValue.length">Seleção independente do filtro de movimento.</small>
</div>
</template>
<style scoped>
.account-multi{min-width:0}.account-multi summary{border:1px solid var(--border,#dce2df);border-radius:6px;padding:9px 10px;cursor:pointer;background:var(--surface,#fff);font-weight:400}.account-multi-panel{border:1px solid var(--border,#dce2df);padding:10px;border-radius:6px;margin-top:5px;display:grid;gap:8px}.account-multi input[type=search]{width:100%;min-width:0}.account-multi-actions{display:flex;flex-wrap:wrap;gap:8px;justify-content:space-between}.account-multi-list{max-height:220px;overflow:auto;display:grid;gap:4px}.account-multi-list label{display:flex;gap:8px;align-items:flex-start;padding:5px;font-weight:400;cursor:pointer}.account-multi-list input{width:auto;margin-top:3px;flex:none}.account-multi-list span{min-width:0;overflow-wrap:anywhere}.account-multi small{display:block;font-size:11px;color:var(--muted,#64748b)}.account-multi-hint{font-size:12px;margin:0;font-weight:400}.account-chips{display:flex;gap:5px;flex-wrap:wrap;max-height:120px;overflow:auto}.account-chips button{font-size:11px;max-width:100%;overflow-wrap:anywhere;background:#eef1f2;border:1px solid #dce2df;border-radius:5px;padding:4px 6px;text-align:left}
</style>
