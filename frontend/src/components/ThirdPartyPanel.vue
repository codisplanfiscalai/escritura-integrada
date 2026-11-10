<script setup>
import {ref,computed,watch,onMounted,onUnmounted,onDeactivated} from 'vue';
import BaseModal from './BaseModal.vue';
import {state,company,api,scope,can,changed,notify,rows,ask} from '../lib/workspace';
import {reusableFields,matchingParties,replacementParties,requestGuard,contextKey} from '../lib/third-party-state';
const props=defineProps({master:{type:Object,required:true}}),emit=defineEmits(['close']);
const context={companyId:state.companyId,period:state.period,module:state.module,name:company.value?.name||''};
const requestContext={companyId:context.companyId,year:context.period.slice(0,4),module:context.module};
const initialContext=contextKey(state),guard=requestGuard(initialContext,()=>contextKey(state)),sourceGuard=requestGuard(initialContext,()=>contextKey(state));
const correctionGuard=requestGuard(initialContext,()=>contextKey(state));
const replacements=ref([]),replacementId=ref(''),correctionReason=ref(''),replacementLoading=ref(false),replacementLoaded=ref(false);
const replacementOptions=computed(()=>replacementParties(replacements.value,detail.value));
const registrationBaseline=ref('[]');
const detail=ref(null),history=ref([]),registrations=ref([]),reason=ref(''),error=ref(''),busy=ref(false),loading=ref(true);
const sourceCompany=ref(''),sourceMaster=ref(''),sources=ref([]),sourceLoading=ref(false),fields=ref([]),preview=ref(null),reuseReason=ref('');
const destination=scope(`/third-parties/${props.master.id}`,context.companyId);
const registrationsDirty=computed(()=>JSON.stringify(registrations.value)!==registrationBaseline.value);
const editable=computed(()=>can('fiscal.masters','edit'));
const companies=computed(()=>state.companies.filter(c=>c.id!==context.companyId));
const candidates=computed(()=>matchingParties(sources.value,detail.value));
function invalidatePreview(){preview.value=null;guard.invalidate();}
const editorKey=Symbol('third-party-editor');
const editor={name:'Identidade e histórico de terceiro',companyId:context.companyId,key:editorKey};
function releaseEditor(){if(state.editor?.key===editorKey)state.editor=null;}
function forceClose(){guard.dispose();sourceGuard.dispose();correctionGuard.dispose();preview.value=null;releaseEditor();emit('close');}
async function close(){if(busy.value)return;if(registrationsDirty.value&&!await ask({title:'Descartar inscrições não salvas?',message:'As alterações de inscrições estaduais ainda não foram salvas.',confirmLabel:'Descartar'}))return;forceClose();}
function discardRegistrations(){registrations.value=JSON.parse(registrationBaseline.value);preview.value=null;}
watch(()=>[state.companyId,state.period,state.module],forceClose,{flush:'sync'});
onUnmounted(()=>{guard.dispose();sourceGuard.dispose();correctionGuard.dispose();releaseEditor();});onDeactivated(forceClose);
const clone=value=>JSON.parse(JSON.stringify(value));
function applyDetail(value){detail.value=value;registrations.value=clone(value.data?.profile?.state_registrations||[]).map(r=>({...r,status:r.status??'',active:r.active??null}));registrationBaseline.value=JSON.stringify(registrations.value);}
async function load(){const n=guard.begin();loading.value=true;error.value='';try{const [d,h]=await Promise.all([api(destination),api(`${destination}/history`)]);if(guard.current(n)){applyDetail(d);history.value=rows(h);}}catch(e){if(guard.current(n))error.value=e.message;}finally{if(guard.current(n))loading.value=false;}}
onMounted(()=>{state.editor=editor;load();});
watch(sourceCompany,async()=>{invalidatePreview();sourceMaster.value='';sources.value=[];const n=sourceGuard.begin();sourceLoading.value=false;if(!sourceCompany.value)return;sourceLoading.value=true;error.value='';try{const list=await api(scope('/third-parties',sourceCompany.value));if(sourceGuard.current(n))sources.value=rows(list);}catch(e){if(sourceGuard.current(n))error.value=`Origem indisponível: ${e.message}`;}finally{if(sourceGuard.current(n))sourceLoading.value=false;}});
watch([sourceMaster,fields],invalidatePreview,{deep:true,flush:'sync'});
async function createPreview(){if(busy.value||registrationsDirty.value||!sourceMaster.value||!fields.value.length)return;const n=guard.begin();busy.value=true;error.value='';preview.value=null;try{const p=await api(`${destination}/reuse-preview`,{method:'POST',context:requestContext,body:{source_company_id:sourceCompany.value,source_master_id:sourceMaster.value,fields:[...fields.value]}});if(guard.current(n))preview.value=p;}catch(e){if(guard.current(n))error.value=e.message;}finally{if(guard.current(n))busy.value=false;}}
async function mutate(suffix,method,body,success){if(busy.value||!editable.value||contextKey(state)!==initialContext)return;const n=guard.begin();busy.value=true;error.value='';try{const d=await api(`${destination}/${suffix}`,{method,body,context:requestContext});if(!guard.current(n))return;applyDetail(d);preview.value=null;reason.value='';reuseReason.value='';changed();notify(success);try{const h=await api(`${destination}/history`);if(guard.current(n))history.value=rows(h);}catch(e){if(guard.current(n))error.value=`Dados salvos; não foi possível atualizar o histórico: ${e.message}`;}}catch(e){if(guard.current(n)){error.value=e.message;preview.value=null;}}finally{if(guard.current(n))busy.value=false;}}
function saveRegistrations(){mutate('registrations','PUT',{version:detail.value.version,reason:reason.value,state_registrations:clone(registrations.value)},'Inscrições estaduais salvas.');}
function confirmReuse(){if(!preview.value||registrationsDirty.value)return;mutate('reuse-confirm','POST',{...clone(preview.value),reason:reuseReason.value},'Campos cadastrais reutilizados na empresa de destino.');}
async function loadReplacements(){
 if(busy.value||replacementLoading.value||registrationsDirty.value||!editable.value||!detail.value||detail.value.replacement_master_id)return;
 const n=correctionGuard.begin();replacementLoading.value=true;replacementLoaded.value=false;replacementId.value='';replacements.value=[];error.value='';
 try{const list=await api(scope('/third-parties',context.companyId));if(correctionGuard.current(n)){replacements.value=rows(list);replacementLoaded.value=true;}}
 catch(e){if(correctionGuard.current(n))error.value=`Não foi possível carregar os cadastros locais: ${e.message}`;}
 finally{if(correctionGuard.current(n))replacementLoading.value=false;}
}
async function confirmCorrection(){
 if(busy.value||registrationsDirty.value||!editable.value||!correctionReason.value.trim()||detail.value.replacement_master_id)return;
 const successor=replacementOptions.value.find(r=>r.id===replacementId.value);if(!successor)return;
 const n=correctionGuard.begin(),payload={replacement_master_id:successor.id,version:detail.value.version,reason:correctionReason.value};busy.value=true;
 try{
  const approved=await ask({title:'Confirmar substituição auditada?',message:`Empresa: ${context.name}. Original: ${detail.value.code} · ${detail.value.name} · ${detail.value.tax_id} (ID ${detail.value.id}). Sucessor: ${successor.code} · ${successor.name} · ${successor.tax_id} (ID ${successor.id}). O cadastro anterior será inativado. Documentos, títulos e IDs existentes serão preservados e continuarão vinculados ao anterior. Use o sucessor somente nas novas operações.`,confirmLabel:'Registrar substituição'});
  if(!correctionGuard.current(n))return;
  busy.value=false;
  if(!approved||registrationsDirty.value)return;
  await mutate('identity-correction','POST',payload,'Substituição auditada registrada; vínculos anteriores preservados.');
  if(correctionGuard.current(n)&&detail.value.replacement_master_id){correctionReason.value='';replacementId.value='';replacements.value=[];}
 }finally{if(correctionGuard.current(n))busy.value=false;}
}
function display(value){return value===null||value===undefined||value===''?'Não informado':typeof value==='object'?JSON.stringify(value,null,2):String(value);}
function currentValue(field){return field==='name'?detail.value.name:field==='state_registrations'?detail.value.data?.profile?.state_registrations:detail.value.data?.[field];}
</script>
<template>
<BaseModal title="Identidade e dados do terceiro" :subtitle="`Destino: ${context.name} · cadastro local ${master.code}`" wide @close="close">
<p v-if="error" class="message error" role="alert">{{error}}</p><p v-if="loading" role="status">Carregando cadastro e histórico…</p>
<template v-if="detail">
<section><h3>Identidade compartilhada mínima</h3><p v-if="detail.identity">{{detail.identity.entity_type==='person'?'CPF':'Raiz do CNPJ'}}: <strong>{{detail.identity.identity_key}}</strong> · CPF/CNPJ completo: {{detail.tax_id}}</p><p v-else>Sem identidade global válida. O cadastro permanece local.</p><p class="message subtle">Somente a identidade é compartilhada. Cada estabelecimento é identificado pelo CNPJ completo. A mesma raiz não autoriza acesso a outras empresas.</p></section>
<section><h3>Dados privados de {{context.name}}</h3><p>{{detail.name}} · ID local {{detail.id}} · versão {{detail.version}} · {{detail.active?'Ativo':'Inativo'}}</p><p>E-mail: {{display(detail.data?.email)}} · Telefone: {{display(detail.data?.phone)}}</p><p>Funções locais: {{(detail.data?.roles||[]).join(', ')||'Não informadas'}}</p><p v-if="detail.replacement_master_id">Substituído pelo cadastro local {{detail.replacement_master_id}}. Documentos e títulos anteriores mantêm seus vínculos.</p></section>
<section><h3>Inscrições estaduais da empresa</h3><p>IE principal preservada: {{display(detail.data?.ie)}}</p><p>Situação ausente não significa isenção. Atividade pode ser verdadeira, falsa ou não informada.</p>
<form @submit.prevent="saveRegistrations"><fieldset :disabled="busy||!editable"><div v-for="(r,i) in registrations" :key="i" class="registration-row form-grid three">
<label>UF<input v-model="r.state" required maxlength="2"/></label><label>Número da IE<input v-model="r.number"/></label><label>Situação explícita<input v-model="r.status" list="third-party-ie-status"/></label>
<label>Ativa<select v-model="r.active"><option :value="null">Não informado</option><option :value="true">Verdadeiro</option><option :value="false">Falso</option></select></label><label>Fonte<input v-model="r.source"/></label><label>Atualização informada<input v-model="r.updated_at"/></label><button type="button" class="button small" @click="registrations.splice(i,1)">Remover IE {{i+1}}</button></div>
<datalist id="third-party-ie-status"><option value="active">Ativa</option><option value="exempt">Isenta</option><option value="not_applicable">Não aplicável</option><option value="not_found">Não encontrada</option></datalist>
<p v-if="!registrations.length">Nenhuma IE detalhada por UF.</p><p>Sem número, informe explicitamente exempt (isenta), not_applicable (não aplicável) ou not_found (não encontrada).</p>
<template v-if="editable"><button type="button" class="button small" @click="registrations.push({state:'',number:'',status:'',active:null,source:'',updated_at:''})">Adicionar IE</button><label>Motivo da revisão<input v-model="reason" required maxlength="1000"/></label><button class="button" :disabled="!reason.trim()">Salvar inscrições</button><button type="button" class="button" :disabled="!registrationsDirty" @click="discardRegistrations">Descartar alterações de IEs</button></template></fieldset></form></section>
<section v-if="editable&&detail.identity"><p v-if="registrationsDirty" class="message subtle">Salve ou descarte as alterações de IEs antes de reutilizar campos.</p><h3>Reutilizar campos de outra empresa</h3><p>Destino fixo: <strong>{{context.name}}</strong>. Somente o mesmo CPF ou CNPJ completo é aceito. Contatos, funções, notas e condições financeiras não são copiados.</p>
<fieldset :disabled="busy||registrationsDirty"><label>Empresa de origem<select v-model.number="sourceCompany"><option value="">Selecione uma empresa permitida</option><option v-for="c in companies" :key="c.id" :value="c.id">{{c.name}}</option></select></label>
<p v-if="sourceLoading" role="status">Verificando acesso aos cadastros da origem…</p><label v-if="sourceCompany&&!sourceLoading">Cadastro de origem<select v-model.number="sourceMaster"><option value="">Selecione</option><option v-for="r in candidates" :key="r.id" :value="r.id">{{r.code}} · {{r.name}} · {{r.tax_id}}</option></select></label><p v-if="sourceCompany&&!sourceLoading&&!candidates.length">Nenhum cadastro acessível com o mesmo CPF/CNPJ completo.</p>
<div class="form-grid three"><label v-for="(label,key) in reusableFields" :key="key" class="inline-choice"><input v-model="fields" type="checkbox" :value="key"/>{{label}}</label></div><button class="button" :disabled="!sourceMaster||!fields.length||sourceLoading" @click="createPreview">Conferir prévia</button></fieldset>
<div v-if="preview&&!registrationsDirty"><h4>Prévia da alteração em {{context.name}}</h4><p>Os valores selecionados substituirão os atuais, inclusive valores vazios.</p><div class="table-scroll"><table><thead><tr><th>Campo</th><th>Atual no destino</th><th>Valor proposto</th></tr></thead><tbody><tr v-for="field in preview.fields" :key="field"><td>{{reusableFields[field]}}</td><td class="value">{{display(currentValue(field))}}</td><td class="value">{{display(preview.values[field])}}</td></tr></tbody></table></div><form @submit.prevent="confirmReuse"><label>Motivo da reutilização<input v-model="reuseReason" required maxlength="1000" :disabled="busy"/></label><div class="actions"><button type="button" class="button" :disabled="busy" @click="invalidatePreview">Cancelar prévia</button><button class="button primary" :disabled="busy||!reuseReason.trim()">Confirmar reutilização em {{context.name}}</button></div></form></div></section>
<section v-if="editable&&!detail.replacement_master_id"><details><summary>Corrigir CPF/CNPJ por substituição auditada</summary>
<p>Crie primeiro um cadastro local do mesmo tipo com o CPF/CNPJ correto. A substituição inativa o cadastro anterior, preserva seus IDs, documentos, títulos e histórico e indica o sucessor para novas operações. Não transfere os lançamentos antigos.</p>
<p v-if="registrationsDirty" class="message subtle">Salve ou descarte as alterações de IEs antes de substituir este cadastro.</p>
<fieldset :disabled="busy||registrationsDirty||replacementLoading"><button type="button" class="button" @click="loadReplacements">Carregar cadastros locais para substituição</button>
<p v-if="replacementLoading" role="status">Carregando cadastros de {{context.name}}…</p>
<form v-if="replacementLoaded" @submit.prevent="confirmCorrection"><label>Cadastro correto / sucessor<select v-model.number="replacementId" required><option value="">Selecione</option><option v-for="r in replacementOptions" :key="r.id" :value="r.id">{{r.code}} · {{r.name}} · {{r.tax_id}} · ID {{r.id}}</option></select></label>
<p v-if="!replacementOptions.length">Nenhum cadastro ativo, não substituído e do mesmo tipo com identidade diferente. Crie primeiro o cadastro correto.</p>
<label>Motivo da correção<input v-model="correctionReason" required maxlength="1000"/></label><button class="button" :disabled="!replacementId||!correctionReason.trim()">Revisar e confirmar substituição</button></form></fieldset>
</details></section>
<section><h3>Histórico deste cadastro local</h3><p v-if="!history.length">Sem eventos registrados.</p><details v-for="event in history" :key="event.id"><summary>{{event.created_at}} · {{event.event}} · {{event.actor}}</summary><p>{{event.details?.reason}}</p><p v-if="event.details?.replacement_master_id">Sucessor local: {{event.details.replacement_master_id}}</p><div class="form-grid"><div><strong>Antes</strong><pre>{{display(event.details?.before)}}</pre></div><div><strong>Depois</strong><pre>{{display(event.details?.after)}}</pre></div></div></details></section>
</template><template #footer><button class="button" :disabled="busy" @click="close">Fechar</button></template>
</BaseModal>
</template>
<style scoped>
section+section{margin-top:1.5rem;border-top:1px solid var(--border,#ddd);padding-top:1rem}fieldset{border:0;padding:0;min-width:0}fieldset:disabled{opacity:.7}.registration-row{padding:.75rem 0;border-bottom:1px solid var(--border,#ddd)}pre,.value{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.85rem}pre{max-height:18rem;overflow:auto}details{margin:.75rem 0}label{margin:.5rem 0}
</style>
