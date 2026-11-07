<script setup>
import {ref,computed,onUnmounted} from 'vue';
import Icon from '../components/Icon.vue';import BaseModal from '../components/BaseModal.vue';import EmptyState from '../components/EmptyState.vue';
import {state,company,api,scope,useResource,rows,notify,changed,ask} from '../lib/workspace';
import {dateTime} from '../lib/format';
const modules=[{id:'fiscal',name:'Fiscal',icon:'documents',description:'Protege a inclusão, a conferência, a edição e a escrituração dos documentos da competência.'},{id:'accounting',name:'Contábil',icon:'journal',description:'Protege os lançamentos e a integração contábil de documentos e baixas financeiras.'}];
const {data,loading,error:loadError}=useResource(async()=>{
 if(!state.companyId)return {periods:{},dashboard:null,audit:[]};
 const[p,d,a]=await Promise.all([api(scope(`/periods?period=${state.period}`)),api(scope(`/dashboard?period=${state.period}`)),api(scope('/audit?limit=200'))]);
 return {periods:p,dashboard:d,audit:rows(a)};
},{periods:{},dashboard:null,audit:[]});
const history=computed(()=>data.value.audit.filter(a=>a.entity==='period'&&String(a.entity_id).startsWith(`${state.period}:`)));
const pending=computed(()=>(data.value.dashboard?.documents.pending||0)+(data.value.dashboard?.documents.reviewed||0));
const show=ref(false),busy=ref(false),error=ref(''),reason=ref(''),selected=ref(null),context=ref(null);
function open(module){selected.value={...module,closed:!!data.value.periods[module.id]?.closed};context.value={id:state.companyId,name:company.value?.name,code:company.value?.code,period:state.period};reason.value='';error.value='';show.value=true;state.editor={name:'Fechamento de competência',companyId:state.companyId};}
async function close(){if(busy.value)return;if(reason.value.trim()&&!await ask({title:'Descartar motivo?',message:'A alteração de competência ainda não foi confirmada.',confirmLabel:'Descartar',danger:true}))return;show.value=false;state.editor=null;}
async function save(){
 if(!reason.value.trim())return;
 busy.value=true;error.value='';
 try{
  const action=selected.value.closed?'reopen':'close';
  await api(scope(`/periods/${action}`,context.value.id),{method:'POST',body:{period:context.value.period,module:selected.value.id,reason:reason.value.trim()}});
  show.value=false;state.editor=null;changed();notify(`Competência ${selected.value.name.toLowerCase()} ${selected.value.closed?'reaberta':'fechada'} com registro do motivo.`);
 }catch(e){error.value=e.message;}finally{busy.value=false;}
}
onUnmounted(()=>{if(show.value)state.editor=null;});
</script>

<template>
 <div class="view periods-view">
  <header class="view-heading"><div><div class="eyebrow">CONTROLE DE COMPETÊNCIA</div><h1>Fechamento e bloqueios</h1><p>Fiscal e contábil possuem fechamento independente, com motivo e responsável.</p></div><span class="badge neutral"><Icon name="periods" :size="15"/>{{state.period.split('-').reverse().join('/')}}</span></header>
  <div v-if="loadError" class="message error" role="alert">{{loadError}}</div>
  <div v-if="loading" class="loading-line"><Icon name="loading"/>Consultando os bloqueios...</div>
  <div class="period-cards">
   <section v-for="module in modules" :key="module.id" class="panel period-card">
    <div class="panel-heading"><div class="module-heading"><span class="module-icon"><Icon :name="module.icon" :size="23"/></span><div><h2>Módulo {{module.name.toLowerCase()}}</h2><p>{{state.period.split('-').reverse().join('/')}}</p></div></div><span class="badge" :class="data.periods[module.id]?.closed?'warning':'success'"><Icon :name="data.periods[module.id]?.closed?'lock':'unlock'" :size="13"/>{{data.periods[module.id]?.closed?'Fechado':'Aberto'}}</span></div>
    <div class="period-card-body"><p>{{module.description}}</p><div class="period-summary"><span>{{module.id==='fiscal'?'Documentos na competência':'Lançamentos na competência'}}</span><strong>{{module.id==='fiscal'?(data.dashboard?.documents.count||0):(data.dashboard?.accounting.journals||0)}}</strong></div><div v-if="module.id==='fiscal'&&pending&&!data.periods.fiscal?.closed" class="message warning"><Icon name="alert" :size="17"/><span>{{pending}} documento(s) ainda precisam concluir a escrituração.<button class="text-button" @click="state.tab='documents'">Conferir documentos<Icon name="arrow" :size="14"/></button></span></div><div v-if="data.periods[module.id]?.changed_at" class="period-last-change"><span>Última alteração · {{dateTime(data.periods[module.id].changed_at)}}</span><strong>{{data.periods[module.id].actor}}</strong><p>{{data.periods[module.id].reason}}</p></div><div v-else class="period-last-change"><span>Nenhum fechamento registrado nesta competência.</span></div></div>
    <footer class="panel-action split"><span class="field-help">O outro módulo mantém seu estado.</span><button class="button" :class="data.periods[module.id]?.closed?'outline':'primary'" :disabled="loading||!state.companyId||(!data.periods[module.id]?.closed&&module.id==='fiscal'&&pending>0)" @click="open(module)"><Icon :name="data.periods[module.id]?.closed?'unlock':'lock'"/>{{data.periods[module.id]?.closed?'Reabrir competência':'Fechar competência'}}</button></footer>
   </section>
  </div>
  <div class="message subtle"><Icon name="info"/><span>Fechar impede novos efeitos no módulo indicado. Uma reabertura precisa de motivo e fica no histórico. Operações com efeito fiscal e contábil exigem ambos os módulos abertos. Movimentos financeiros sem contabilização não alteram esses livros.</span></div>
  <section class="panel"><div class="panel-heading"><div><h2>Histórico desta competência</h2><p>Fechamentos e reaberturas registrados para {{company?.name}}.</p></div><span class="badge neutral">{{history.length}} eventos</span></div><div v-if="history.length" class="table-scroll"><table><thead><tr><th>Data / hora</th><th>Módulo</th><th>Ação</th><th>Responsável</th><th>Motivo</th></tr></thead><tbody><tr v-for="entry in history" :key="entry.id"><td class="nowrap">{{dateTime(entry.created_at)}}</td><td>{{entry.details.module==='fiscal'?'Fiscal':'Contábil'}}</td><td><span class="badge" :class="entry.action==='close'?'warning':'success'"><Icon :name="entry.action==='close'?'lock':'unlock'" :size="13"/>{{entry.action==='close'?'Fechamento':'Reabertura'}}</span></td><td>{{entry.actor}}</td><td>{{entry.details.reason}}</td></tr></tbody></table></div><EmptyState v-else title="Sem alterações de bloqueio" text="O fechamento ou a reabertura registra módulo, competência, motivo e responsável." icon="periods"/><footer class="table-footer"><span>Exibição limitada aos últimos 200 eventos de auditoria da empresa.</span><span>Motivo preservado no histórico</span></footer></section>
  <BaseModal v-if="show" :title="selected.closed?'Reabrir competência':'Fechar competência'" :subtitle="`${context.code} · ${context.name}`" @close="close"><div class="context-notice"><Icon name="building"/><span>Empresa: <strong>{{context.name}}</strong></span></div><div class="summary-strip"><div><span>Módulo</span><strong>{{selected.name}}</strong></div><div><span>Competência</span><strong>{{context.period.split('-').reverse().join('/')}}</strong></div></div><div v-if="error" class="message error" role="alert">{{error}}</div><form id="period-form" @submit.prevent="save"><label>Motivo {{selected.closed?'da reabertura':'do fechamento'}} *<textarea v-model="reason" required maxlength="1000" rows="4" :placeholder="selected.closed?'Explique a correção que exige reabrir a competência.':'Registre a conferência realizada e a decisão de fechar.'" autofocus/></label><div class="message" :class="selected.closed?'warning':'subtle'"><Icon :name="selected.closed?'alert':'shield'"/><span>{{selected.closed?'A reabertura permite novos registros nesse módulo. O evento e o motivo ficarão identificados.':'Após confirmar, novas gravações que afetem este módulo serão bloqueadas nesta competência.'}}</span></div></form><template #footer><span class="footer-hint">O módulo {{selected.id==='fiscal'?'contábil':'fiscal'}} mantém seu estado.</span><div class="actions"><button class="button" :disabled="busy" @click="close">Cancelar</button><button class="button primary" form="period-form" type="submit" :disabled="busy||!reason.trim()"><Icon :name="busy?'loading':selected.closed?'unlock':'lock'"/>{{selected.closed?'Confirmar reabertura':'Confirmar fechamento'}}</button></div></template></BaseModal>
 </div>
</template>

<style scoped>
.period-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.period-card{display:flex;flex-direction:column}.module-heading{display:flex;align-items:center;gap:12px}.module-icon{display:grid;place-items:center;width:44px;height:44px;border-radius:12px;background:#eef5f5;color:#21645c}.period-card-body{padding:2px 20px 18px;flex:1}.period-card-body>p{line-height:1.5;color:#667782;margin-top:0}.period-summary{display:flex;justify-content:space-between;gap:12px;padding:14px 0;border-top:1px solid #edf0f2}.period-summary strong{font-size:20px}.period-last-change{display:grid;gap:5px;font-size:12px;color:#697983;margin-top:12px}.period-last-change p{margin:0;color:#354d5c;overflow-wrap:anywhere}.period-last-change strong{font-size:12px;color:#354d5c}.period-card .panel-action{margin-top:auto;gap:12px}.period-card .text-button{display:flex;margin-top:6px}.periods-view textarea{resize:vertical;min-height:90px;width:100%}
@media(max-width:900px){.period-cards{grid-template-columns:1fr}.period-card .panel-action{flex-wrap:wrap}}
</style>
