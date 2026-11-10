<script setup>
import {ref,watch,onUnmounted} from 'vue';
import {api,scope,state,can,changed} from '../lib/workspace';
const plans=ref([]),binding=ref(null),selected=ref(''),detail=ref(null),preview=ref(null),mode=ref('shared'),copyScope=ref('all');
const busy=ref(false),error=ref(''),result=ref(''),reason=ref(''),reviewed=ref(false),query=ref(''),page=ref(1);
let sequence=0;
function invalidate(){sequence++;preview.value=null;reviewed.value=false;error.value='';result.value='';}
async function load(){
 if(!state.companyId||!can('accounting.accounts','read'))return;
 const n=sequence,cid=state.companyId;busy.value=true;
 try{const r=await api(scope('/global-account-plans',cid));if(n===sequence){plans.value=r.plans;binding.value=r.binding;}}
 catch(e){if(n===sequence)error.value=e.message;}finally{if(n===sequence)busy.value=false;}
}
watch(()=>[state.companyId,state.module,state.period],()=>{invalidate();busy.value=false;plans.value=[];binding.value=null;selected.value='';detail.value=null;reason.value='';load();},{immediate:true});
watch(()=>state.refresh,()=>{if(!busy.value)load();});
watch([selected,mode,copyScope],()=>{invalidate();detail.value=null;query.value='';page.value=1;},{flush:'sync'});

onUnmounted(()=>sequence++);
async function inspect(){
 if(!selected.value||busy.value)return;
 const n=sequence,cid=state.companyId,search=query.value,pn=page.value;busy.value=true;error.value='';
 try{const r=await api(scope(`/global-account-plans/${selected.value}?page=${pn}&search=${encodeURIComponent(search)}`,cid));if(n===sequence&&search===query.value&&pn===page.value)detail.value=r;}
 catch(e){if(n===sequence)error.value=e.message;}finally{if(n===sequence)busy.value=false;}
}
async function prepare(){
 if(!selected.value||busy.value)return;
 invalidate();const n=sequence,cid=state.companyId;busy.value=true;
 try{const r=await api(scope(`/global-account-plans/${selected.value}/preview`,cid),{method:'POST',body:{mode:mode.value,copy_scope:copyScope.value}});if(n===sequence)preview.value=r;}
 catch(e){if(n===sequence)error.value=e.message;}finally{if(n===sequence)busy.value=false;}
}
async function confirm(){
 if(!preview.value?.can_confirm||!reviewed.value||!reason.value.trim()||busy.value)return;
 const n=sequence,cid=state.companyId,p=preview.value;busy.value=true;error.value='';
 try{
  const r=await api(scope(`/global-account-plans/previews/${p.id}/confirm`,cid),{method:'POST',body:{preview_hash:p.preview_hash,reason:reason.value,properties_reviewed:true}});
  if(n!==sequence)return;
  preview.value=null;reviewed.value=false;result.value=r.mode==='shared'?`${r.available} contas globais disponíveis por vínculo, sem copiar o plano para a empresa. Referências serão criadas somente ao usar as contas. Plano compartilhado, protegido contra edição local.`:`${r.record_count} contas globais selecionadas para plano próprio ${r.copy_scope==='used'?'restrito às usadas e pais existentes':'integral'}; ${r.created} contas novas criadas e IDs usados preservados. ${r.copy_scope==='used'&&!r.record_count?'Nenhuma conta global foi copiada. ':''}Plano próprio disponível para adaptação.`;
  changed();
 }catch(e){if(n===sequence)error.value=e.message;}finally{if(n===sequence){busy.value=false;load();}}
}
async function detach(){
 if(!binding.value||!reason.value.trim()||busy.value)return;
 const n=sequence,cid=state.companyId;busy.value=true;error.value='';
 try{const r=await api(scope('/global-account-plans/binding/detach',cid),{method:'POST',body:{version:binding.value.version,reason:reason.value,copy_scope:copyScope.value}});if(n===sequence){binding.value=r;result.value=r.copy_scope==='used'?`Plano próprio restrito às usadas: ${r.copied_accounts??0} contas globais selecionadas, incluindo pais existentes. ${r.copied_accounts?'':'Nenhuma conta global foi copiada. '}Identificadores e lançamentos foram preservados.`:'Plano próprio integral liberado para adaptação. Identificadores e lançamentos foram preservados.';changed();}}
 catch(e){if(n===sequence)error.value=e.message;}finally{if(n===sequence)busy.value=false;}
}
function cancel(){if(busy.value)return;invalidate();selected.value='';detail.value=null;reason.value='';}
</script>
<template>
<section class="panel global-plan" aria-label="Plano global compartilhado">
 <h2>Biblioteca global de planos</h2>
 <p>Uma versão pode ser vinculada a várias empresas sem cópia integral. Referências empresariais mínimas são criadas somente quando usadas. Acesso identifica a conta; classificadores repetidos mantêm os agrupamentos originais. Novas versões nunca alteram contas ou lançamentos automaticamente.</p>
 <p v-if="binding" class="context-notice">Versão global #{{binding.global_plan_id}} · {{binding.mode==='shared'?'Compartilhado, sem edição local':'Próprio, adaptável'}} · vínculo v{{binding.version}}</p>
 <p v-if="error" class="message error" role="alert">{{error}}</p><p v-if="result" class="message success" role="status">{{result}}</p>
 <fieldset :disabled="busy" class="form-grid">
  <label>Plano e versão<select v-model="selected"><option value="">Selecione</option><option v-for="p in plans" :key="p.id" :value="p.id">{{p.name}} · #{{p.id}} · {{p.record_count}} contas</option></select></label>
  <label v-if="mode==='own'||binding?.mode==='shared'">Escopo da cópia própria<select v-model="copyScope"><option value="all">Duplicar integralmente</option><option value="used">Somente contas usadas e pais existentes necessários</option></select></label>
  <label>Uso nesta empresa<select v-model="mode"><option value="shared">Usar versão global compartilhada</option><option value="own">Duplicar para plano próprio adaptável</option></select></label>
 </fieldset>
 <p v-if="!plans.length&&!busy">Nenhum plano global publicado. O administrador pode importar o arquivo original nas ferramentas abaixo e publicar a prévia revisada. O modelo genérico não substitui o plano fornecido.</p>
 <div class="actions"><button class="button outline" :disabled="busy||!selected" @click="inspect">Consultar contas</button><button class="button outline" :disabled="busy||!selected||!can('accounting.accounts','create')" @click="prepare">Preparar uso na empresa</button><button class="button" :disabled="busy" @click="cancel">Cancelar</button><button class="button" :disabled="busy" @click="load">Atualizar biblioteca</button></div>
 <section v-if="detail" class="plan-detail">
  <p>{{detail.record_count}} contas · {{detail.classifier_count}} classificadores · {{detail.warning_count}} avisos de origem. Exibição paginada, sem deduplicação.</p>
  <div class="actions" v-if="can('accounting.imports','export')"><a class="text-button" :href="'/api'+scope(`/global-account-plans/${detail.id}/original`)" download>Baixar original global</a><a class="text-button" :href="'/api'+scope(`/global-account-plans/${detail.id}/native`)" download>Baixar definição global em JSON</a></div>
  <details><summary>Propriedades da versão</summary><pre>{{JSON.stringify(detail.properties,null,2)}}</pre></details>
  <div class="actions"><input v-model="query" aria-label="Pesquisar contas globais" placeholder="Acesso, classificador ou nome"/><input v-model.number="page" type="number" min="1" aria-label="Página de contas globais"/><button class="button outline" :disabled="busy" @click="inspect">Pesquisar / carregar página</button></div>
  <div class="table-scroll"><table><thead><tr><th>Acesso</th><th>Classificador</th><th>Conta</th><th>Tipo</th><th>Natureza</th></tr></thead><tbody><tr v-for="a in detail.accounts" :key="a.access_code"><td>{{a.access_code}}</td><td>{{a.classifier}}</td><td>{{a.name}}</td><td>{{a.analytical?'Analítica':'Sintética'}}</td><td>{{a.nature==='debit'?'Devedora':'Credora'}}</td></tr></tbody></table></div>
 </section>
 <section v-if="preview" class="plan-detail">
  <p><strong>Prévia da versão #{{preview.plan.id}}</strong> · {{preview.created}} novas contas disponíveis · {{preview.preserved}} contas idênticas preservadas · {{preview.local_accounts_preserved}} contas locais adicionais preservadas · {{preview.conflict_count}} conflitos.</p>
  <p>No modo compartilhado, a confirmação grava apenas o vínculo à versão global. No modo próprio, a definição será copiada para adaptação. Contas existentes e seus vínculos não serão substituídos. Se houver contas locais adicionais, elas continuam na empresa. No modo compartilhado todas as contas ficam protegidas até duplicar para adaptação.</p>
  <ul v-if="preview.conflicts.length" class="message error"><li v-for="(c,i) in preview.conflicts" :key="i">{{c.access_code}}: {{c.reason}}</li></ul>
  <p v-if="preview.copy_scope==='used'">{{preview.used_accounts}} contas usadas e {{preview.parents_included}} contas sintéticas ancestrais existentes selecionadas. Outras contas globais não serão copiadas; cadastros locais anteriores serão preservados.</p>
  <p v-if="preview.missing_parent_classifiers?.length" class="message warning">Prefixos sem conta sintética explícita na origem: {{preview.missing_parent_classifiers.join(', ')}}. Nenhum código ou conta será inventado.</p>
  <label class="check-label"><input v-model="reviewed" type="checkbox" :disabled="busy"/>Revisei a máscara, a hierarquia, as características, as naturezas e os avisos da versão.</label>
 </section>
 <label v-if="preview||binding?.mode==='shared'">Motivo da operação<textarea v-model="reason" :disabled="busy" maxlength="1000"/></label>
 <div class="actions"><button v-if="preview" class="button primary" :disabled="busy||!preview.can_confirm||!reviewed||!reason.trim()" @click="confirm">Confirmar uso nesta empresa</button><button v-if="binding?.mode==='shared'&&can('accounting.accounts','edit')" class="button outline" :disabled="busy||!reason.trim()" @click="detach">Duplicar vínculo para plano próprio</button></div>
</section>
</template>
<style scoped>
.global-plan{padding:18px;display:grid;gap:14px;margin-bottom:18px}.global-plan h2,.global-plan p{margin:0}.global-plan h2{font-size:17px}.plan-detail{display:grid;gap:12px}.table-scroll{max-height:360px}pre{max-height:240px;overflow:auto;white-space:pre-wrap}fieldset{border:0;padding:0;min-width:0}
</style>
