<script setup>
import {ref,watch,onUnmounted,computed} from 'vue';
import BaseModal from './BaseModal.vue';
import {state,company,api,scope,can,captureContext,changed,notify,ask} from '../lib/workspace';
const show=ref(false),busy=ref(false),error=ref(''),config=ref(null),preview=ref(null),reason=ref('');
const destination=ref(null),originalDigits=ref(3);let sequence=0;
const canCorrect=computed(()=>can('fiscal.documents','read')&&can('fiscal.documents','edit'));
function clear(){sequence++;show.value=false;preview.value=null;config.value=null;busy.value=false;if(state.editor?.owner==='series-settings')state.editor=null;}
watch(()=>[state.companyId,state.period,state.module],clear,{flush:'sync'});onUnmounted(clear);
watch(()=>config.value?.digits,()=>preview.value=null,{flush:'sync'});
async function open(){
 if(busy.value||state.editor)return;
 destination.value={cid:state.companyId,context:captureContext(),name:company.value?.trade_name||company.value?.name};
 const token=++sequence;busy.value=true;error.value='';
 try{const result=await api(scope('/fiscal-series/settings',destination.value.cid));if(token!==sequence)return;config.value=result;originalDigits.value=result.digits;reason.value='';show.value=true;state.editor={owner:'series-settings',name:'Séries fiscais',companyId:destination.value.cid};}
 catch(e){if(token===sequence)error.value=e.message;}finally{if(token===sequence)busy.value=false;}
}
async function close(){if(busy.value)return;if(config.value?.digits!==originalDigits.value&&!await ask({title:'Descartar parâmetro não salvo?',message:'A quantidade de dígitos ainda não foi salva.',confirmLabel:'Descartar',danger:true}))return;clear();}
async function save(){
 if(busy.value)return;const token=sequence;busy.value=true;error.value='';preview.value=null;
 try{const result=await api(scope('/fiscal-series/settings',destination.value.cid),{method:'PUT',context:destination.value.context,body:config.value});if(token!==sequence)return;config.value=result;originalDigits.value=result.digits;changed();notify('Parâmetro de série salvo. A correção dos registros existentes exige prévia e confirmação separadas.');}
 catch(e){if(token===sequence)error.value=e.message;}finally{if(token===sequence)busy.value=false;}
}
async function prepare(){
 if(busy.value||config.value?.digits!==originalDigits.value)return;const token=sequence;busy.value=true;error.value='';preview.value=null;
 try{const result=await api(scope('/fiscal-series/preview',destination.value.cid),{method:'POST',context:destination.value.context,body:{period:state.period}});if(token===sequence)preview.value=result;}
 catch(e){if(token===sequence)error.value=e.message;}finally{if(token===sequence)busy.value=false;}
}
async function confirm(){
 if(busy.value||!preview.value?.can_confirm)return;const token=sequence;busy.value=true;error.value='';
 try{const p=preview.value;const result=await api(scope('/fiscal-series/confirm',destination.value.cid),{method:'POST',context:destination.value.context,body:{preview_id:p.id,preview_hash:p.preview_hash,reason:reason.value.trim()}});if(token!==sequence)return;preview.value=null;changed();notify(`Séries corrigidas: ${result.selected_count}. Registros preservados: ${result.preserved_count}.`);}
 catch(e){if(token===sequence){preview.value=null;error.value=e.status?`${e.message} Gere uma nova prévia.`:'Resultado não confirmado. Atualize os registros antes de tentar novamente.';}}
 finally{if(token===sequence)busy.value=false;}
}
</script>
<template>
<section v-if="can('fiscal.parameters','read')" class="panel panel-body">
 <h2>Série dos documentos fiscais</h2><p>Quantidade mínima de dígitos por empresa, com padrão de 3. Somente séries numéricas recebem zeros à esquerda.</p>
 <button class="button outline" :disabled="busy||!!state.editor||!state.companyId" @click="open">Configurar série e corrigir existentes</button>
 <p v-if="error&&!show" class="message error" role="alert">{{error}}</p>
</section>
<BaseModal v-if="show" title="Padronização de séries fiscais" :subtitle="destination.name" wide @close="close">
 <p v-if="error" class="message error" role="alert">{{error}}</p>
 <form id="series-settings-form" @submit.prevent="save">
  <label>Dígitos mínimos da série<input v-model.number="config.digits" type="number" min="1" max="20" step="1" required :disabled="busy||!can('fiscal.parameters','edit')"/></label>
  <p>Com 3 dígitos: 1 → 001 e 20 → 020. Séries vazias e alfanuméricas são preservadas. Séries maiores nunca são truncadas. Leiautes externos podem exigir um limite menor e bloquear a exportação.</p>
  <button v-if="can('fiscal.parameters','edit')" class="button primary" :disabled="busy||config.digits===originalDigits">Salvar parâmetro</button>
 </form><hr/>
 <h3>Correção em massa, separada do parâmetro</h3>
 <p>Abrange documentos desta empresa em todos os exercícios. A prévia não altera movimentos. Identidades conflitantes, competências protegidas e apurações finalizadas impedem a confirmação. Originais e evidências históricas não são reescritos.</p>
 <button v-if="canCorrect" class="button outline" :disabled="busy||config.digits!==originalDigits" @click="prepare">Gerar prévia da correção</button>
 <p v-else>Seu perfil não permite alterar documentos fiscais.</p>
 <div v-if="preview">
  <p><strong>{{preview.selected_count}} correções propostas</strong> em {{preview.total_count}} documentos. {{preview.preserved_count}} preservados.</p>
  <ul v-if="preview.blockers.length" class="message warning"><li v-for="(b,i) in preview.blockers.slice(0,100)" :key="i">{{b.id?'#'+b.id+' · ':''}}{{b.message}}</li></ul>
  <div class="table-scroll"><table aria-label="Prévia da correção de séries"><thead><tr><th>Documento</th><th>Competência</th><th>Série gravada</th><th>Após correção</th></tr></thead><tbody><tr v-for="r in preview.rows.slice(0,200)" :key="r.id"><td>#{{r.id}} · {{r.number}}</td><td>{{r.period}}</td><td>{{r.before}}</td><td>{{r.after}}</td></tr></tbody></table></div>
  <p v-if="preview.rows.length>200">Exibindo as primeiras 200 alterações de {{preview.rows.length}}. A confirmação abrange todas as alterações da prévia.</p>
  <details><summary>Registros preservados ({{preview.preserved_count}})</summary><p v-for="r in preview.preserved_rows.slice(0,200)" :key="r.id">#{{r.id}} · {{r.series||'(vazia)'}} · {{r.reasons.join(' ')}}</p></details>
  <label>Motivo para o histórico<input v-model="reason" maxlength="1000" :disabled="busy"/></label>
 </div>
 <template #footer><button class="button" :disabled="busy" @click="close">Fechar</button><button v-if="preview" class="button primary" :disabled="busy||!preview.can_confirm" @click="confirm">Confirmar {{preview.selected_count}} correções nesta empresa</button></template>
</BaseModal>
</template>
