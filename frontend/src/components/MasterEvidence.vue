<script setup>
import {ref,watch,onUnmounted} from 'vue';
import {state,api,scope,can} from '../lib/workspace';
import XmlSourceFields from './XmlSourceFields.vue';
import FiscalXmlDetails from './FiscalXmlDetails.vue';
const props=defineProps({master:{type:Object,required:true},companyId:{type:Number,required:true}});
const rows=ref([]),total=ref(0),offset=ref(0),loading=ref(false),error=ref(''),details=ref({}),detailBusy=ref(null),detailError=ref('');
let request=0,detailRequest=0,disposed=false;
const allowed=()=>!disposed&&state.companyId===props.companyId&&can('fiscal.documents','read');
async function load(){const token=++request;rows.value=[];loading.value=true;error.value='';try{if(!allowed())return;const result=await api(scope(`/masters/${props.master.kind}/${props.master.id}/evidence?offset=${offset.value}&limit=25`,props.companyId));if(token!==request||!allowed())return;rows.value=result.items;total.value=result.total;}catch(e){if(token===request&&allowed())error.value=e.message;}finally{if(token===request)loading.value=false;}}
async function readXml(document){if(!allowed()||detailBusy.value!==null)return;const token=++detailRequest;detailBusy.value=document.id;detailError.value='';try{const result=await api(scope(`/documents/${document.id}/xml-details`,props.companyId));if(token===detailRequest&&allowed())details.value={...details.value,[document.id]:result};}catch(e){if(token===detailRequest&&allowed())detailError.value=e.message;}finally{if(token===detailRequest)detailBusy.value=null;}}
watch(()=>[props.master.id,props.companyId],()=>{offset.value=0;details.value={};detailRequest++;detailBusy.value=null;detailError.value='';load();},{immediate:true});
watch(offset,load);onUnmounted(()=>{disposed=true;request++;detailRequest++;});
const roles={issuer:'Emitente',recipient:'Destinatário','transport/carrier':'Transportador','transport/taker':'Tomador',item:'Produto / serviço',initial_origin:'Origem inicial (vínculo atual alterado)'};
</script>
<template>
<section class="master-evidence">
<h3>Documentos e dados de origem</h3>
<p>Observações desta empresa, identificadas por documento e item. Valores, alíquotas e impostos declarados não viram regras automáticas do cadastro.</p>
<p v-if="!can('fiscal.documents','read')" class="message subtle">A consulta de documentos exige permissão fiscal específica.</p>
<template v-else><p v-if="loading" role="status">Carregando origens…</p><p v-if="error" class="message error" role="alert">{{error}} <button type="button" class="button small" @click="load">Tentar novamente</button></p>
<p v-if="!loading&&!error&&!rows.length">Nenhuma ocorrência documental vinculada foi localizada. Campos ausentes não são preenchidos por suposição.</p>
<details v-for="(row,index) in rows" :key="`${row.document.id}-${row.role}-${index}`">
<summary>Documento {{row.document.number}} · {{row.document.issue_date}} · {{roles[row.role]||row.role}}<template v-if="row.item_number"> · item {{row.item_number}}</template></summary>
<p v-if="row.notice" class="message subtle">{{row.notice}}</p><p>{{row.document.source?.file||'Origem não identificada'}} · {{row.document.direction==='incoming'?'Entrada':'Saída'}} · modelo {{row.document.model}} · série {{row.document.series||'Não informada'}}</p>
<p class="mono">Chave: {{row.document.key||'Não informada'}}<br/>Hash: {{row.document.source_hash||'Não informado'}}</p>
<XmlSourceFields title="Dados disponíveis no documento vinculado" :value="row.values"/>
<button type="button" class="button small" :disabled="detailBusy!==null" @click="readXml(row.document)">{{detailBusy===row.document.id?'Carregando XML…':'Consultar XML original e detalhes completos'}}</button>
<template v-if="details[row.document.id]"><p v-if="!details[row.document.id].available" class="message warning">{{details[row.document.id].message}}</p><p v-else class="message subtle">{{details[row.document.id].origin==='retained_xml'?'Original recuperado pelo hash, sem alterar a escrituração.':'Origem preservada na importação.'}}</p><FiscalXmlDetails :document="details[row.document.id].document" :items-only="master.kind==='product'||master.kind==='service'"/></template>
</details>
<p v-if="detailError" class="message error" role="alert">{{detailError}}</p>
<footer class="actions"><span>{{total}} ocorrências · página {{Math.floor(offset/25)+1}}</span><button type="button" class="button small" :disabled="loading||offset===0" @click="offset=Math.max(0,offset-25)">Anterior</button><button type="button" class="button small" :disabled="loading||offset+25>=total" @click="offset+=25">Próxima</button></footer>
</template>
</section>
</template>
<style scoped>
details{border:1px solid var(--border,#ddd);padding:12px;margin:10px 0;border-radius:8px}summary{cursor:pointer;font-weight:600}p{overflow-wrap:anywhere}.actions{margin-top:12px}
</style>
