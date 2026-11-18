<script setup>
import {ref,computed,watch,onUnmounted} from 'vue';
import {api,notify,changed} from '../lib/workspace';
import {services} from '../lib/reception.js';
const props=defineProps({companyId:{type:Number,required:true},disabled:Boolean});
const emit=defineEmits(['dirty','busy']);
const units=ref({nfe_distribution:60,nfse_adn:60});
const data=ref(null),forms=ref({}),busy=ref(false),error=ref('');
let generation=0;
const statuses={disabled:'Desabilitada',pending:'Busca agendada',running:'Consultando lote',waiting:'Aguardando intervalo',idle:'Coleta concluída; próxima busca agendada',blocked:'Bloqueada — conferir cadastro/recibo'};
const value=row=>({version:row.version,enabled:row.enabled,interval_minutes:row.interval_minutes});
const different=p=>!!data.value&&JSON.stringify(forms.value[p])!==JSON.stringify(value(data.value.services[p]));
const dirty=computed(()=>Object.keys(forms.value).some(different));
watch(dirty,v=>emit('dirty',v));watch(busy,v=>emit('busy',v));
const stamp=v=>v?new Date(v*1000).toLocaleString('pt-BR'):'—';
async function load(){const g=++generation,cid=props.companyId;busy.value=true;error.value='';data.value=null;forms.value={};try{const r=await api('/companies/'+cid+'/reception-automation');if(g===generation){data.value=r;forms.value=Object.fromEntries(Object.entries(r.services).map(([p,row])=>[p,value(row)]));}}catch(e){if(g===generation)error.value=e.message;}finally{if(g===generation)busy.value=false;}}
async function save(p,reschedule=false){if(busy.value||props.disabled||!data.value?.can_edit||!different(p)&&!reschedule)return;if(!Number.isInteger(forms.value[p].interval_minutes)||forms.value[p].interval_minutes<1||forms.value[p].interval_minutes>525600){error.value='Informe um intervalo equivalente a um número inteiro de minutos, entre 1 e 525600.';return;}const g=generation,cid=props.companyId;busy.value=true;error.value='';try{const r=await api('/companies/'+cid+'/reception-automation/'+p,{method:'PUT',body:{...forms.value[p]}});if(g===generation){data.value.services[p]=r;forms.value[p]=value(r);changed();notify(r.enabled?'Automação salva. A coleta inicia em segundo plano e respeita as pausas do serviço.':'Automação desabilitada. O lote já enviado poderá terminar; novos lotes não serão iniciados.');}}catch(e){if(g===generation)error.value=e.message;}finally{if(g===generation)busy.value=false;}}
watch(()=>props.companyId,load,{immediate:true});onUnmounted(()=>{generation++;emit('dirty',false);emit('busy',false);});
</script>
<template><section aria-label="Automação de busca de XMLs">
<h4>Busca e download automático de XMLs</h4>
<p>Configure cada serviço de forma independente. O padrão é <strong>1440 minutos (24 horas)</strong> entre coletas concluídas. Ao habilitar e salvar, a primeira busca é agendada imediatamente.</p>
<p v-if="error" class="message error" role="alert">{{error}}</p>
<p v-if="data&&!data.can_edit" class="field-help">Alterar exige edição desta empresa e permissões de consultar/importar documentos fiscais.</p>
<p v-if="busy" role="status">Atualizando agendamento…</p>
<form v-for="(row,p) in data?.services||{}" :key="p" @submit.prevent="save(p)">
<fieldset :disabled="busy||disabled||!data.can_edit"><legend>{{services[p].label}}</legend>
<label class="inline-choice"><input type="checkbox" v-model="forms[p].enabled"/>Habilitar busca e download automático</label>
<div class="interval-fields"><label>Intervalo entre buscas<input type="number" :min="1/units[p]" :max="525600/units[p]" step="any" required :value="forms[p].interval_minutes/units[p]" @input="forms[p].interval_minutes=Number($event.target.value)*units[p]" :aria-label="'Intervalo automático '+services[p].label"/></label>
<label>Unidade<select v-model.number="units[p]" :aria-label="'Unidade do intervalo '+services[p].label"><option :value="1">Minutos</option><option :value="60">Horas</option><option :value="1440">Dias</option></select></label></div>
<small>{{Number(forms[p].interval_minutes)/60}} hora(s). A pausa do serviço prevalece quando for maior. O intervalo não é aplicado entre páginas positivas normais do mesmo histórico.</small>
<p role="status">{{statuses[row.status]||row.status}} · Próxima tentativa: {{stamp(row.next_run_at)}}<br/>Última coleta concluída: {{stamp(row.last_success_at)}} · {{row.pages}} lote(s) · {{row.downloaded}} item(ns)</p>
<p v-if="row.last_error" class="message warning">{{row.last_error}}</p>
<button class="button" type="submit" :disabled="!different(p)">Salvar automação {{services[p].label}}</button>
<button v-if="row.status==='blocked'" class="button" type="button" @click="save(p,true)">Revisar e reagendar {{services[p].label}}</button>
</fieldset></form>
<p class="field-help">A execução continua com a tela fechada enquanto a aplicação/servidor estiver ativo e retoma o estado salvo após reinício. As automações começam desabilitadas para preservar a configuração existente.</p>
<p class="message warning">Outros buscadores externos não compartilham a trava desta instalação. Aumente o intervalo ou desabilite este coletor e coordene a sequência NSU entre os sistemas; o intervalo, sozinho, não garante ausência de conflito.</p>
<p class="field-help">NFS-e: são recolhidos os documentos disponibilizados ao prestador, tomador e intermediário. NF-e: a distribuição não fornece ao próprio emitente o XML da nota que ele emitiu; importe os XMLs do emissor em Importações fiscais. Resumos não são XMLs completos e não geram manifestação automática.</p>
<button type="button" class="button" :disabled="busy||disabled||dirty" @click="load">Atualizar situação das automações</button>
</section></template>
<style scoped>
.interval-fields{display:flex;gap:12px;align-items:end;flex-wrap:wrap}h4{margin:15px 0}fieldset{border:1px solid var(--line);padding:16px;border-radius:8px;margin:14px 0}.inline-choice{display:flex;flex-direction:row;gap:8px;align-items:center}.inline-choice input{width:auto}input[type="number"]{max-width:260px}label{display:flex;flex-direction:column;gap:6px}small{display:block;margin:10px 0;color:var(--muted)}p{line-height:1.6;margin:12px 0}
</style>
