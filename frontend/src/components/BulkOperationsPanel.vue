<script setup>
import {ref,computed,watch,onUnmounted} from 'vue';
import BaseModal from './BaseModal.vue';
import {state,company,api,scope,can,changed,notify,captureContext} from '../lib/workspace';
const props=defineProps({kind:{type:String,required:true},records:{type:Array,default:()=>[]},selectedIds:{type:Array,default:()=>[]},resetKey:String,loading:Boolean});
const emit=defineEmits(['update:selectedIds','busy']);
const show=ref(false),action=ref('delete'),field=ref('history'),value=ref(''),linked=ref(false),reversalPairs=ref(false),preview=ref(null),reason=ref(''),phrase=ref(''),ack=ref(false),busy=ref(false),error=ref(''),now=ref(Date.now());
const routine=computed(()=>props.kind==='documents'?'fiscal.documents':'accounting.journals');
const actions=computed(()=>props.kind==='documents'?[['delete','Excluir definitivamente','delete'],['review','Registrar conferência fiscal','edit'],['book','Escriturar somente no fiscal','book'],['update','Alterar CFOP','edit']]:[['delete','Excluir definitivamente','delete'],['update','Alterar histórico / documento','edit']]);
const permission=computed(()=>actions.value.find(a=>a[0]===action.value)?.[2]);
const permitted=computed(()=>can(routine.value,'read')&&can(routine.value,permission.value)&&(!(props.kind==='documents'&&action.value==='delete'&&linked.value)||(can('accounting.journals','read')&&can('accounting.journals','delete'))));
const selected=computed(()=>props.records.filter(r=>props.selectedIds.includes(r.id)));
const periods=computed(()=>[...new Set(selected.value.map(r=>r.period||String(r.posting_date||r.date||'').slice(0,7)))]);
const selectionIssue=computed(()=>!selected.value.length?'Selecione ao menos um registro.':selected.value.length!==props.selectedIds.length?'A seleção contém registros fora da tabela visível. Selecione novamente.':selected.value.length>500?'O limite é 500 registros por lote.':periods.value.length!==1?'Selecione registros de uma única competência. Lotes com competências diferentes são bloqueados.':!/^\d{4}-\d{2}$/.test(periods.value[0])?'Competência inválida. Atualize a consulta.':periods.value[0].slice(0,4)!==state.period.slice(0,4)?'Selecione uma competência do exercício ativo da empresa.':'');
const changes=computed(()=>action.value!=='update'?{}:props.kind==='documents'?{cfop:value.value.trim()}:{[field.value]:value.value.trim()});
const canPrepare=computed(()=>!busy.value&&!props.loading&&!state.contextBusy&&state.companyId&&permitted.value&&!selectionIssue.value&&(action.value!=='update'||value.value.trim().length>0));
const expiry=computed(()=>typeof preview.value?.expires_at==='number'?preview.value.expires_at*1000:Date.parse(preview.value?.expires_at));
const expired=computed(()=>preview.value&&(!Number.isFinite(expiry.value)||expiry.value<=now.value));
const canConfirm=computed(()=>canPrepare.value&&preview.value?.can_confirm===true&&!preview.value.blockers?.length&&!expired.value&&reason.value.trim().length>0&&(action.value!=='delete'||(ack.value&&!!preview.value.confirmation_phrase&&phrase.value===preview.value.confirmation_phrase)));
let sequence=0,requestOwner=0;
function invalidate(){sequence++;preview.value=null;phrase.value='';ack.value=false;error.value='';}
function reset(){invalidate();requestOwner++;busy.value=false;show.value=false;reason.value='';emit('update:selectedIds',[]);}
watch(busy,b=>emit('busy',b),{flush:'sync'});
watch([action,field,value,linked,reversalPairs,()=>JSON.stringify(props.selectedIds)],invalidate,{flush:'sync'});
watch([()=>props.resetKey,()=>state.companyId,()=>state.period,()=>state.module,()=>JSON.stringify(props.records),()=>props.loading],reset,{flush:'sync'});
const timer=setInterval(()=>now.value=Date.now(),1000);
onUnmounted(()=>{sequence++;requestOwner++;clearInterval(timer);emit('busy',false);});
function selectVisible(){if(busy.value||props.loading)return;emit('update:selectedIds',props.records.slice(0,500).map(r=>r.id));}
function open(){if(!selected.value.length||busy.value)return;invalidate();linked.value=false;reversalPairs.value=false;reason.value='';show.value=true;}
function close(){if(busy.value)return;invalidate();reason.value='';show.value=false;}
async function prepare(){
 if(!canPrepare.value)return;invalidate();const token=sequence,owner=++requestOwner,cid=state.companyId,context=captureContext();busy.value=true;
 try{const result=await api(scope('/bulk-operations/preview',cid),{method:'POST',context,body:{kind:props.kind,action:action.value,period:periods.value[0],ids:selected.value.map(r=>r.id),changes:changes.value,include_linked_journals:props.kind==='documents'&&action.value==='delete'&&linked.value,include_reversal_pairs:action.value==='delete'&&(props.kind==='journals'||linked.value)&&reversalPairs.value}});if(token===sequence&&cid===state.companyId){now.value=Date.now();preview.value=result;}}
 catch(e){if(token===sequence)error.value=e.message;}
 finally{if(owner===requestOwner)busy.value=false;}
}
async function confirm(){
 now.value=Date.now();if(!canConfirm.value)return;const token=sequence,owner=++requestOwner,cid=state.companyId,p=preview.value,context=captureContext();busy.value=true;error.value='';
 try{await api(scope('/bulk-operations/confirm',cid),{method:'POST',context,body:{preview_id:p.id,preview_hash:p.preview_hash,reason:reason.value.trim(),confirmation_phrase:action.value==='delete'?phrase.value:p.confirmation_phrase,irreversible_acknowledged:action.value==='delete'&&ack.value}});if(token!==sequence||cid!==state.companyId)return;reset();changed();notify('Operação concluída nos registros da prévia.');}
 catch(e){if(token===sequence){invalidate();error.value=e.status?`${e.message} Gere uma nova prévia antes de tentar novamente.`:'Não foi possível verificar o resultado da confirmação. Atualize a consulta e confira os registros antes de iniciar outra operação.';}}
 finally{if(owner===requestOwner)busy.value=false;}
}
const describe=v=>typeof v==='string'?v:JSON.stringify(v);
const countLabels={documents:'Documentos fiscais',journals:'Lançamentos contábeis',journal_lines:'Partidas contábeis',document_items:'Itens fiscais',files:'Arquivos',sources:'Fontes',titles:'Títulos financeiros'};
</script>
<template>
<div class="bulk-toolbar" aria-label="Operações nos registros selecionados">
 <span aria-live="polite">{{selectedIds.length}} selecionado(s) · limite de 500</span>
 <button class="button small" :disabled="busy||loading||!records.length||!can(routine,'read')" @click="selectVisible">Selecionar somente os {{Math.min(records.length,500)}} visíveis{{records.length>500?' (primeiros 500)':''}}</button>
 <button class="button small" :disabled="busy||!selectedIds.length" @click="reset">Limpar seleção</button>
 <button class="button outline small" :disabled="busy||loading||!selectedIds.length" @click="open">Operar selecionados</button>
 <small>Uma seleção vale como operação individual. Trocar consulta, página, empresa ou exercício limpa a seleção.</small>
</div>
<BaseModal v-if="show" title="Operação nos registros selecionados" :subtitle="`${company?.code||''} · ${company?.trade_name||company?.name||''} · Empresa #${state.companyId}`" wide @close="close">
 <p class="context-notice"><strong>{{selected.length}} registro(s)</strong> · Competência: {{periods.join(', ')||'não identificada'}}</p>
 <p>Inclui registros escriturados ou consolidados quando permitidos. Período fechado ou apuração encerrada exige reabertura prévia por pessoa autorizada. Esta operação não reabre períodos.</p>
 <div v-if="selectionIssue" class="message error" role="alert">{{selectionIssue}}</div>
 <div v-if="error" class="message error" role="alert">{{error}}</div>
 <fieldset class="plain-fieldset" :disabled="busy">
  <label>Operação<select v-model="action"><option v-for="a in actions" :key="a[0]" :value="a[0]" :disabled="!can(routine,'read')||!can(routine,a[2])">{{a[1]}}{{!can(routine,a[2])?' · sem permissão':''}}</option></select></label>
  <p>Permissões exigidas: {{routine}}.read e {{routine}}.{{permission}}. <strong>{{permitted?'Disponíveis para seu usuário.':'Sem permissão para esta operação.'}}</strong></p>
  <template v-if="action==='update'"><label v-if="kind==='journals'">Campo a substituir<select v-model="field"><option value="history">Histórico</option><option value="document">Documento / referência</option></select></label><label>{{kind==='documents'?'Novo CFOP':'Novo conteúdo'}}<input v-model="value" :maxlength="kind==='documents'?4:field==='history'?1000:100" :inputmode="kind==='documents'?'numeric':'text'"/></label><p>Somente o campo informado será alterado. Valores, datas e partidas não são editados por este lote. Confira os efeitos e bloqueios na prévia.</p></template>
  <p v-if="action==='book'" class="message subtle">Escrituração somente fiscal, sem gerar lançamentos contábeis nem títulos financeiros.</p>
  <p v-if="action==='review'" class="message subtle">A conferência registra sua revisão dos dados. Não certifica o tratamento tributário.</p>
  <template v-if="action==='delete'"><p class="message warning">Exclusão física definitiva dos registros autorizados e dependências indicadas na prévia, sem exclusão lógica. Fontes compartilhadas, originais, auditoria e backups podem permanecer. Não há garantia de apagamento seguro do disco.</p><label v-if="kind==='documents'" class="check-label"><input type="checkbox" v-model="linked"/>Incluir lançamentos contábeis vinculados na prévia</label><p v-if="kind==='documents'&&linked">Também exige accounting.journals.read e accounting.journals.delete; vínculos fora do conjunto autorizado bloqueiam a exclusão.</p><label v-if="kind==='journals'||linked" class="check-label"><input type="checkbox" v-model="reversalPairs"/>Incluir pares de estorno e suas competências na prévia</label><p v-if="reversalPairs&&(kind==='journals'||linked)">A prévia pode incluir lançamentos ligados por estorno em outras competências e exercícios. Todos exigem permissões e períodos abertos. Confira os identificadores e todas as competências antes de digitar a frase de confirmação.</p></template>
 </fieldset>
 <button class="button outline" :disabled="!canPrepare" @click="prepare">{{busy?'Processando…':'Gerar prévia'}}</button>
 <section v-if="preview" class="bulk-preview" aria-label="Prévia da operação">
  <h3>Confira o conjunto afetado</h3><p>{{preview.selected_count}} selecionado(s) · {{preview.period}} · Prévia #{{preview.id}}</p>
  <p v-if="preview.affected_periods?.length"><strong>Competências afetadas:</strong> {{preview.affected_periods.join(', ')}}</p><p v-if="preview.linkedJournalIds?.length||preview.linked_journal_ids?.length"><strong>Lançamentos vinculados incluídos:</strong> {{(preview.linkedJournalIds||preview.linked_journal_ids).join(', ')}}</p>
  <dl class="bulk-counts"><template v-for="(count,key) in preview.affected_counts" :key="key"><dt>{{countLabels[key]||key}}</dt><dd>{{describe(count)}}</dd></template></dl>
  <details v-if="preview.retained_counts"><summary>Fontes, arquivos e evidências que permanecerão</summary><dl class="bulk-counts"><template v-for="(count,key) in preview.retained_counts" :key="key"><dt>{{countLabels[key]||key}}</dt><dd>{{describe(count)}}</dd></template></dl></details>
  <div v-if="preview.blockers?.length" class="message error" role="alert"><strong>Operação bloqueada. Resolva as dependências sem contornar as permissões.</strong><ul><li v-for="(b,i) in preview.blockers" :key="i">{{describe(b)}}</li></ul></div>
  <ul v-if="preview.warnings?.length" class="message warning"><li v-for="(w,i) in preview.warnings" :key="i">{{describe(w)}}</li></ul>
  <details open><summary>Registros e dependências: {{Math.min(preview.rows?.length||0,100)}} linhas exibidas (máximo 100); {{preview.selected_count}} selecionados no total</summary><ol class="bulk-rows"><li v-for="(row,i) in (preview.rows||[]).slice(0,100)" :key="i">{{describe(row)}}</li></ol></details>
  <p>Validade da prévia: {{Number.isFinite(expiry)?new Date(expiry).toLocaleString('pt-BR'):'não informada'}}. O servidor revalida permissões, períodos e dependências na confirmação.</p><p v-if="expired" role="alert" class="message error">Prévia vencida. Gere uma nova prévia.</p>
  <fieldset class="plain-fieldset" :disabled="busy"><label>Motivo da operação *<textarea v-model="reason" rows="2" maxlength="1000" required/></label><template v-if="action==='delete'"><label class="check-label"><input v-model="ack" type="checkbox"/>Entendo que a exclusão física é definitiva e não pode ser desfeita nesta tela.</label><label>Digite exatamente: {{preview.confirmation_phrase}}<input v-model="phrase" autocomplete="off" spellcheck="false"/></label></template></fieldset>
 </section>
 <template #footer><button class="button" :disabled="busy" @click="close">Cancelar</button><button class="button" :class="action==='delete'?'danger':'primary'" :disabled="!canConfirm" @click="confirm">{{busy?'Processando…':action==='delete'?'Excluir definitivamente':'Confirmar operação'}}</button></template>
</BaseModal>
</template>
<style scoped>
.bulk-toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid var(--border,#ddd)}
.bulk-toolbar small{flex-basis:100%;color:var(--muted,#666)}
.bulk-preview{margin-top:20px}.bulk-counts{display:grid;grid-template-columns:1fr 1fr;gap:6px}.bulk-counts dd{margin:0}.bulk-rows{max-height:280px;overflow:auto;padding-left:24px}.bulk-rows li{overflow-wrap:anywhere;margin:8px 0}
</style>
