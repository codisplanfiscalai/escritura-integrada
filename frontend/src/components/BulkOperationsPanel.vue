<script setup>
import {ref,computed,watch,onUnmounted} from 'vue';
import BaseModal from './BaseModal.vue';
import {state,company,api,scope,can,changed,notify,captureContext} from '../lib/workspace';
const props=defineProps({kind:{type:String,required:true},records:{type:Array,default:()=>[]},selectedIds:{type:Array,default:()=>[]},resetKey:String,loading:Boolean});
const emit=defineEmits(['update:selectedIds','busy']);
const show=ref(false),action=ref('delete'),field=ref('history'),value=ref(''),linked=ref(false),reversalPairs=ref(false),preview=ref(null),reason=ref(''),selectionScope=ref('selection'),busy=ref(false),error=ref(''),now=ref(Date.now());
const routine=computed(()=>props.kind==='documents'?'fiscal.documents':'accounting.journals');
const actions=computed(()=>props.kind==='documents'?[['delete','Excluir definitivamente','delete'],['review','Registrar conferência fiscal','edit'],['book','Escriturar somente no fiscal','book'],['update','Alterar CFOP','edit']]:[['delete','Excluir definitivamente','delete'],['update','Alterar histórico / documento','edit']]);
const permission=computed(()=>actions.value.find(a=>a[0]===action.value)?.[2]);
const permitted=computed(()=>can(routine.value,'read')&&can(routine.value,permission.value)&&(!(props.kind==='documents'&&action.value==='delete'&&linked.value)||(can('accounting.journals','read')&&can('accounting.journals','delete'))));
const selected=computed(()=>props.records.filter(r=>props.selectedIds.includes(r.id)));
const periods=computed(()=>[...new Set(selected.value.map(r=>r.period||String(r.posting_date||r.date||'').slice(0,7)))]);
const selectionIssue=computed(()=>selectionScope.value==='company'?'':!selected.value.length?'Selecione ao menos um registro.':selected.value.length!==props.selectedIds.length?'A seleção contém registros fora da tabela visível. Selecione novamente.':selected.value.length>5000?'Selecione até 5.000 registros ou use Limpar tudo neste módulo.':periods.value.length!==1?'Selecione registros de uma única competência. Lotes com competências diferentes são bloqueados.':!/^\d{4}-\d{2}$/.test(periods.value[0])?'Competência inválida. Atualize a consulta.':periods.value[0].slice(0,4)!==state.period.slice(0,4)?'Selecione uma competência do exercício ativo da empresa.':'');
const changes=computed(()=>action.value!=='update'?{}:props.kind==='documents'?{cfop:value.value.trim()}:{[field.value]:value.value.trim()});
const canPrepare=computed(()=>!busy.value&&!props.loading&&!state.contextBusy&&state.companyId&&permitted.value&&!selectionIssue.value&&(action.value!=='update'||value.value.trim().length>0));
const expiry=computed(()=>typeof preview.value?.expires_at==='number'?preview.value.expires_at*1000:Date.parse(preview.value?.expires_at));
const expired=computed(()=>preview.value&&(!Number.isFinite(expiry.value)||expiry.value<=now.value));
const canConfirm=computed(()=>canPrepare.value&&preview.value?.can_confirm===true&&!preview.value.blockers?.length&&!expired.value);
let sequence=0,requestOwner=0;
function invalidate(){sequence++;preview.value=null;error.value='';}
function reset(){invalidate();requestOwner++;busy.value=false;show.value=false;reason.value='';emit('update:selectedIds',[]);}
watch(busy,b=>emit('busy',b),{flush:'sync'});
watch([selectionScope,action,field,value,linked,reversalPairs,()=>JSON.stringify(props.selectedIds)],invalidate,{flush:'sync'});
watch([()=>props.resetKey,()=>state.companyId,()=>state.period,()=>state.module,()=>JSON.stringify(props.records),()=>props.loading],reset,{flush:'sync'});
const timer=setInterval(()=>now.value=Date.now(),1000);
onUnmounted(()=>{sequence++;requestOwner++;clearInterval(timer);emit('busy',false);});
function selectVisible(){if(busy.value||props.loading)return;emit('update:selectedIds',props.records.slice(0,5000).map(r=>r.id));}
function open(all=false){if((!all&&!selected.value.length)||busy.value)return;invalidate();selectionScope.value=all?'company':'selection';action.value='delete';linked.value=false;reversalPairs.value=false;reason.value='';show.value=true;prepare();}
function close(){if(busy.value)return;invalidate();reason.value='';show.value=false;}
async function prepare(){
 if(!canPrepare.value)return;invalidate();const token=sequence,owner=++requestOwner,cid=state.companyId,context=captureContext();busy.value=true;
 try{const result=await api(scope('/bulk-operations/preview',cid),{method:'POST',context,body:{kind:props.kind,action:action.value,period:selectionScope.value==='company'?state.period:periods.value[0],scope:selectionScope.value,ids:selectionScope.value==='company'?[]:selected.value.map(r=>r.id),changes:changes.value,include_linked_journals:props.kind==='documents'&&action.value==='delete'&&linked.value,include_reversal_pairs:action.value==='delete'&&(props.kind==='journals'||linked.value)&&reversalPairs.value}});if(token===sequence&&cid===state.companyId){now.value=Date.now();preview.value=result;}}
 catch(e){if(token===sequence)error.value=e.message;}
 finally{if(owner===requestOwner)busy.value=false;}
}
async function confirm(){
 now.value=Date.now();if(!canConfirm.value)return;const token=sequence,owner=++requestOwner,cid=state.companyId,p=preview.value,context=captureContext();busy.value=true;error.value='';
 try{const result=await api(scope('/bulk-operations/confirm',cid),{method:'POST',context,body:{preview_id:p.id,preview_hash:p.preview_hash,reason:reason.value.trim(),irreversible_acknowledged:action.value==='delete'}});if(token!==sequence||cid!==state.companyId)return;reset();changed();notify(`Operação concluída: ${result.selected_count} registros processados${result.preserved_count?`; ${result.preserved_count} protegidos foram preservados`:''}.`);}
 catch(e){if(token===sequence){invalidate();error.value=e.status?`${e.message} Gere uma nova prévia antes de tentar novamente.`:'Não foi possível verificar o resultado da confirmação. Atualize a consulta e confira os registros antes de iniciar outra operação.';}}
 finally{if(owner===requestOwner)busy.value=false;}
}
const describe=v=>typeof v==='string'?v:v?.message||String(v??'');
const countLabels={documents:'Documentos fiscais',journals:'Lançamentos contábeis',journal_lines:'Partidas contábeis',document_items:'Itens fiscais',document_sources:'Referências de origem',files:'Arquivos',sources:'Fontes',titles:'Títulos financeiros'};
</script>
<template>
<div class="bulk-toolbar" aria-label="Operações nos registros selecionados">
 <span aria-live="polite">{{selectedIds.length}} selecionado(s) · até 5.000 por seleção</span>
 <button class="button small" :disabled="busy||loading||!records.length||!can(routine,'read')" @click="selectVisible">Selecionar somente os {{Math.min(records.length,5000)}} visíveis</button>
 <button class="button small" :disabled="busy||!selectedIds.length" @click="reset">Limpar seleção</button>
 <button class="button outline small" :disabled="busy||loading||!selectedIds.length" @click="open(false)">Operar selecionados</button>
 <button class="button danger small" :disabled="busy||loading||state.contextBusy||!can(routine,'read')||!can(routine,'delete')" @click="open(true)">Limpar tudo neste módulo</button>
 <small>Uma seleção vale como operação individual. Trocar consulta, página, empresa ou exercício limpa a seleção.</small>
</div>
<BaseModal v-if="show" :title="selectionScope==='company'?'Limpar todos os movimentos do módulo':'Operação nos registros selecionados'" :subtitle="`${company?.code||''} · ${company?.trade_name||company?.name||''} · Empresa #${state.companyId}`" wide @close="close">
 <p v-if="selectionScope==='company'" class="context-notice"><strong>Todos os {{kind==='documents'?'documentos fiscais':'lançamentos contábeis'}} desta empresa, de todos os exercícios.</strong> Ignora filtros, página e seleção.</p>
 <p v-else class="context-notice">Somente os <strong>{{selected.length}} registro(s) selecionado(s)</strong>.</p>
 <div v-if="selectionIssue" class="message error" role="alert">{{selectionIssue}}</div>
 <div v-if="error" class="message error" role="alert">{{error}}</div>
 <p v-if="!permitted" class="message error" role="alert">Seu usuário não tem permissão para esta operação.</p>
 <fieldset class="plain-fieldset" :disabled="busy">
  <label v-if="selectionScope!=='company'">Operação<select v-model="action"><option v-for="a in actions" :key="a[0]" :value="a[0]" :disabled="!can(routine,'read')||!can(routine,a[2])">{{a[1]}}{{!can(routine,a[2])?' · sem permissão':''}}</option></select></label>
  <template v-if="action==='update'"><label v-if="kind==='journals'">Campo a substituir<select v-model="field"><option value="history">Histórico</option><option value="document">Documento / referência</option></select></label><label>{{kind==='documents'?'Novo CFOP':'Novo conteúdo'}}<input v-model="value" :maxlength="kind==='documents'?4:field==='history'?1000:100" :inputmode="kind==='documents'?'numeric':'text'"/></label></template>
  <p v-if="action==='book'">Escrituração somente fiscal, sem gerar lançamentos contábeis nem títulos financeiros.</p>
  <template v-if="action==='delete'">
   <label v-if="kind==='documents'" class="check-label"><input type="checkbox" v-model="linked"/>Incluir lançamentos contábeis vinculados</label>
   <label v-if="kind==='journals'||linked" class="check-label"><input type="checkbox" v-model="reversalPairs"/>Incluir pares de estorno</label>
  </template>
 </fieldset>
 <p v-if="busy" role="status">Conferindo a operação…</p>
 <button v-else-if="!preview||expired" class="button outline" :disabled="!canPrepare" @click="prepare">{{action==='update'?'Conferir alteração':'Atualizar prévia'}}</button>
 <section v-if="preview" class="bulk-preview" aria-label="Prévia da operação">
  <p class="bulk-summary"><strong>{{preview.selected_count}} registro(s) {{action==='delete'?'a excluir':'a processar'}}</strong><span v-if="preview.scope==='company'"> · {{preview.preserved_count||0}} protegido(s), mantidos</span></p>
  <p v-if="preview.affected_periods?.length"><strong>Competências:</strong> {{preview.affected_periods.join(', ')}}</p>
  <p v-if="preview.linked_journal_ids?.length"><strong>Também inclui:</strong> {{preview.linked_journal_ids.length}} lançamento(s) contábil(is) vinculado(s).</p>
  <div v-if="preview.blockers?.length" class="message error" role="alert"><strong>Operação bloqueada.</strong> {{describe(preview.blockers[0])}}<span v-if="preview.blockers.length>1"> Consulte os demais motivos nos detalhes.</span></div>
  <p v-if="expired" role="alert" class="message error">Prévia vencida. Atualize antes de confirmar.</p>
  <p v-if="action==='delete'" class="message warning">A exclusão é definitiva e não pode ser desfeita nesta tela.</p>
  <details class="operation-details">
   <summary>Detalhes da operação</summary>
   <p>Cadastros e outras empresas não serão apagados. Períodos fechados e dependências permanecem protegidos. O servidor revalida o conjunto na confirmação.</p>
   <p>Permissões: {{routine}}.read e {{routine}}.{{permission}}<span v-if="linked">; accounting.journals.read e accounting.journals.delete</span>.</p>
   <p>Prévia #{{preview.id}} · Validade: {{Number.isFinite(expiry)?new Date(expiry).toLocaleString('pt-BR'):'não informada'}}</p>
   <h4>Quantidades afetadas</h4><dl class="bulk-counts"><template v-for="(count,key) in preview.affected_counts" :key="key"><dt>{{countLabels[key]||key}}</dt><dd>{{count}}</dd></template></dl>
   <details v-if="preview.retained_counts"><summary>Fontes e evidências conservadas</summary><dl class="bulk-counts"><template v-for="(count,key) in preview.retained_counts" :key="key"><dt>{{countLabels[key]||key}}</dt><dd>{{count}}</dd></template></dl></details>
   <ul v-if="preview.blockers?.length"><li v-for="(item,i) in preview.blockers" :key="i">{{describe(item)}}</li></ul>
   <ul v-if="preview.warnings?.length"><li v-for="(item,i) in preview.warnings" :key="i">{{describe(item)}}</li></ul>
   <h4>Movimentos da operação (primeiros 100)</h4><ol class="bulk-rows"><li v-for="row in (preview.rows||[]).slice(0,100)" :key="row.id">{{row.number||`Registro #${row.id}`}} · {{row.period}}</li></ol>
   <template v-if="preview.preserved_count"><h4>Protegidos e motivos (primeiros 100)</h4><ul class="bulk-rows"><li v-for="row in (preview.preserved_rows||[]).slice(0,100)" :key="row.id">Registro #{{row.id}} · {{row.period}}: {{row.reasons?.join('; ')}}</li></ul></template>
   <label>Observação (opcional)<textarea v-model="reason" :disabled="busy" rows="2" maxlength="1000"/></label>
  </details>
 </section>
 <template #footer><button class="button" :disabled="busy" @click="close">Cancelar</button><button class="button" :class="action==='delete'?'danger':'primary'" :disabled="!canConfirm" @click="confirm">{{busy?'Processando…':action==='delete'?`Excluir definitivamente ${preview?.selected_count??''} registros`:'Confirmar operação'}}</button></template>
</BaseModal>
</template>
<style scoped>
.bulk-toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid var(--border,#ddd)}
.bulk-toolbar small{flex-basis:100%;color:var(--muted,#666)}
.bulk-preview{margin-top:16px}.bulk-summary{font-size:1.1em}.operation-details{margin-top:16px}.operation-details summary{cursor:pointer}.operation-details p,.operation-details li{overflow-wrap:anywhere}.operation-details ul{display:block;padding-left:22px}.operation-details li{margin:6px 0}.operation-details h4{margin:14px 0 8px}.bulk-counts{display:grid;grid-template-columns:1fr 1fr;gap:6px}.bulk-counts dd{margin:0}.bulk-rows{max-height:280px;overflow:auto;padding-left:24px}.bulk-rows li{overflow-wrap:anywhere;margin:8px 0}
</style>
