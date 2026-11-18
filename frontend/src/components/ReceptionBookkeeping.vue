<script setup>
import {ref,computed,watch,onUnmounted} from 'vue';
import {state,api,scope,can,navigate} from '../lib/workspace';
const props=defineProps({provider:String,environment:String,filters:Object,selected:{type:Array,default:()=>[]}});
const day=ref(''),busy=ref(false),error=ref(''),profile=ref(null),profileError=ref(''),baseline=ref('');let generation=0,pendingOwner=null;
const dirty=computed(()=>!!profile.value&&JSON.stringify(profile.value)!==baseline.value);
function release(){if(state.editor?.owner===pendingOwner)state.editor=null;pendingOwner=null;}
onUnmounted(()=>{generation++;release();});
const allowed=computed(()=>can('fiscal.imports','import')&&can('fiscal.imports','export')&&can('fiscal.documents','book'));
const identity=()=>JSON.stringify([state.companyId,state.period,state.session?.user?.id,props.provider,props.environment,state.tab]);
watch(()=>identity(),async()=>{const g=++generation;release();baseline.value='';day.value=state.period+'-01';error.value='';profileError.value='';profile.value=null;busy.value=false;
 if(props.provider!=='nfse_adn'||!state.companyId)return;
 try{const r=await api(scope('/service-bookkeeping-profile'));if(g===generation){profile.value=r;baseline.value=JSON.stringify(r);}}catch(e){if(g===generation)profileError.value=e.message;}
},{immediate:true});
async function saveProfile(){if(busy.value||!can('fiscal.parameters','edit'))return;const c=identity(),g=generation;busy.value=true;profileError.value='';
 try{const r=await api(scope('/service-bookkeeping-profile'),{method:'PUT',body:{...profile.value}});if(c===identity()&&g===generation){profile.value=r;baseline.value=JSON.stringify(r);}}catch(e){if(c===identity())profileError.value=e.message;}finally{if(g===generation)busy.value=false;}}
async function reloadProfile(){if(busy.value)return;const c=identity(),g=generation;busy.value=true;profileError.value='';try{const r=await api(scope('/service-bookkeeping-profile'));if(g===generation&&c===identity()){profile.value=r;baseline.value=JSON.stringify(r);}}catch(e){if(g===generation)profileError.value=e.message;}finally{if(g===generation)busy.value=false;}}
async function prepare(all=false){if(!allowed.value||busy.value||dirty.value||state.editor)return;const c=identity(),cid=state.companyId,g=generation;busy.value=true;error.value='';
 const owner=Symbol('reception-book');pendingOwner=owner;state.editor={owner,name:'Preparação do lote de recepção',companyId:cid};
 try{const body={period:state.period,environment:props.environment,posting_date:day.value,...(all?{filters:{...props.filters}}:{documents:props.selected.map(d=>({receipt_key:d.receipt_key,nsu:d.nsu}))})};
  const result=await api(scope('/reception/'+props.provider+'/bookkeeping-preview'),{method:'POST',body});
  if(c!==identity()||g!==generation)return;
  if(state.editor?.owner===owner)state.editor=null;
  state.receptionImport={companyId:cid,uid:state.session.user.id,year:state.period.slice(0,4),period:state.period,importId:result.import_id};await navigate('imports');
 }catch(e){if(c===identity())error.value=e.message;}finally{if(state.editor?.owner===owner)state.editor=null;if(g===generation)busy.value=false;}}
</script>
<template><section class="panel reception-book" aria-label="Escrituração em lote">
<h2>Escrituração em lote</h2><p>Selecione os XMLs ou prepare todos os resultados filtrados, inclusive de consultas feitas em outros exercícios. A conferência permite revisar CFOPs, datas, selecionar os aptos e confirmar o lote. Resumos e eventos não são notas.</p>
<label>Data de escrituração do lote<input type="date" v-model="day" :disabled="busy"/></label><p>Competência de destino: {{state.period}}. Emissão e competência declarada no XML são preservadas.</p>
<details v-if="provider==='nfse_adn'"><summary>Perfil de escrituração de serviços desta empresa</summary>
<p>Valor contábil dos serviços é sempre mantido. Escolha os demais campos; esta decisão não converte ISS em ICMS nem altera o XML.</p>
<form v-if="profile" @submit.prevent="saveProfile"><fieldset :disabled="busy||!can('fiscal.parameters','edit')">
<label><input type="checkbox" v-model="profile.base"/> Base de cálculo declarada</label><label><input type="checkbox" v-model="profile.iss"/> ISS declarado</label><label><input type="checkbox" v-model="profile.iss_withheld"/> ISS retido, quando informado</label>
<label>Fonte / fundamento<input v-model="profile.source" required maxlength="1000"/></label><label>Responsável<input v-model="profile.responsible" required maxlength="200"/></label>
<button class="button" :disabled="busy||!can('fiscal.parameters','edit')">Salvar perfil de serviços</button></fieldset>
<p>{{profile.version?'Perfil configurado · versão '+profile.version:'Cadastre o perfil antes de escriturar serviços.'}}. Alterações futuras não modificam documentos já escriturados.</p></form>
<p v-if="dirty" class="message warning">Salve o perfil para aplicar as alterações ao próximo lote.</p><p v-if="profileError" role="alert">{{profileError}}</p></details>
<button v-if="provider==='nfse_adn'" type="button" class="button" :disabled="busy" @click="reloadProfile">Recarregar perfil de serviços</button>
<a v-if="provider==='nfse_adn'&&can('fiscal.reports','export')" class="button" :href="'/api'+scope('/service-bookkeeping-profile/report?period='+state.period)">Relatório de serviços escriturados · CSV</a>
<div class="actions"><button class="button" :disabled="busy||dirty||!allowed||!selected.length" @click="prepare(false)">Conferir {{selected.length}} selecionados</button><button class="button primary" :disabled="busy||dirty||!allowed" @click="prepare(true)">Conferir todos os resultados filtrados</button></div>
<p v-if="!allowed">Necessárias permissões de importar e exportar XMLs e escriturar documentos fiscais.</p><p v-if="busy" role="status">Preparando lote local…</p><p v-if="error" role="alert" class="message error">{{error}}</p></section></template>
<style scoped>.reception-book{padding:20px;margin-top:18px}.reception-book p{margin:12px 0}.reception-book label{display:flex;gap:8px;margin:10px 0}.reception-book input[type=checkbox]{width:auto}.reception-book input[type=date]{max-width:200px}.reception-book .actions{display:flex;flex-wrap:wrap;gap:8px}.reception-book fieldset{border:1px solid var(--line);padding:16px}</style>
