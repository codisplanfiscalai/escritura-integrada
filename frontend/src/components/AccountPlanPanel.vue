<script setup>
import {ref,computed,watch,onUnmounted} from 'vue';
import {api,scope,state,company,can,rows,changed,notify} from '../lib/workspace';
import {fileName} from '../lib/files';
import GlobalAccountPlanPanel from './GlobalAccountPlanPanel.vue';
const expanded=ref(false),mode=ref('import'),format=ref('native'),file=ref(null),input=ref(null);
const busy=ref(false),error=ref(''),preview=ref(null),result=ref(null),history=ref([]),historyLoaded=ref(false);
const activationMode=ref('activate'),savedBatchId=ref(null),globalName=ref(''),globalReviewed=ref(false);
const isAdmin=computed(()=>state.session?.user?.role==='admin');
const reason=ref(''),reviewed=ref(false),destinationReviewed=ref(false),allowAscii=ref(false),trimGroups=ref(false);
const identityByAccess=ref(false);
const planCode=ref('0050'),encoding=ref('cp1252'),readingAdjustments=ref('');
const defaults=()=>({mask:'',generated_access:'0',groups:{asset:'1',liability:'2',compensation:'9',cost:'4',expense:'5',revenue:'3'},plan_type:'0',special_mask:''});
const properties=ref(defaults());
const groupLabels={asset:'Ativo',liability:'Passivo',compensation:'Compensação',cost:'Custo',expense:'Despesa',revenue:'Receita'};
const formats=[{value:'native',label:'Escritura Integrada · JSON'},{value:'prosoft-export',label:'Prosoft · layout de exportação (204 posições)'},{value:'prosoft-import',label:'Prosoft · layout de importação (P: 103 / C: 204 posições)'}];
const canImport=computed(()=>can('accounting.imports','import'));
const canActivate=computed(()=>canImport.value&&can('accounting.accounts','create'));
const canExport=computed(()=>can('accounting.imports','export'));
const isProsoft=computed(()=>format.value!=='native'&&mode.value!=='default');
const needsProperties=computed(()=>isProsoft.value&&(mode.value==='export'||format.value==='prosoft-export'));
const conflicts=computed(()=>preview.value?.conflicts||[]);
const conflictCount=computed(()=>preview.value?.conflict_count??conflicts.value.length);
const warningCount=computed(()=>preview.value?.warning_count??preview.value?.warnings?.length??0);
const visibleAccounts=computed(()=>(preview.value?.accounts||[]).slice(0,100));
const visibleChanges=computed(()=>Array.isArray(preview.value?.manifest?.text_changes)?preview.value.manifest.text_changes.slice(0,100):[]);
const canPrepare=computed(()=>state.companyId&&!busy.value&&(mode.value==='export'?canExport.value:canImport.value)&&(mode.value!=='import'||file.value)&&(!needsProperties.value||properties.value.mask.trim()));
const canConfirm=computed(()=>{
 if(!preview.value||busy.value)return false;
 if(mode.value==='export')return canExport.value&&destinationReviewed.value&&(!preview.value.manifest?.needs_ascii_review||allowAscii.value);
 if(!canImport.value||!reviewed.value||!reason.value.trim())return false;
 if(activationMode.value==='reference')return true;
 if(activationMode.value==='global')return isAdmin.value&&Boolean(globalName.value.trim())&&globalReviewed.value;
 return canActivate.value&&preview.value.can_confirm!==false&&!conflictCount.value;
});
let sequence=0;
function invalidate(){sequence++;preview.value=null;result.value=null;savedBatchId.value=null;activationMode.value='activate';reviewed.value=false;destinationReviewed.value=false;allowAscii.value=false;globalReviewed.value=false;error.value='';}
watch(activationMode,()=>{reviewed.value=false;globalReviewed.value=false;},{flush:'sync'});
watch([mode,format,properties,planCode,encoding,trimGroups,readingAdjustments,identityByAccess],invalidate,{deep:true,flush:'sync'});
watch(()=>[state.companyId,state.module,state.period],()=>{invalidate();busy.value=false;file.value=null;if(input.value)input.value.value='';properties.value=defaults();trimGroups.value=false;readingAdjustments.value='';reason.value='';history.value=[];historyLoaded.value=false;expanded.value=false;});
onUnmounted(()=>{sequence++;});
function cancel(){if(busy.value)return;invalidate();reason.value='';file.value=null;if(input.value)input.value.value='';expanded.value=false;}
function choose(event){if(busy.value)return;invalidate();file.value=null;const chosen=event.target.files?.[0];if(!chosen)return;if(chosen.size>15_000_000){error.value='Selecione um arquivo de até 15 MB.';event.target.value='';return;}file.value=chosen;}
const encode=f=>new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('Não foi possível ler o arquivo selecionado.'));reader.readAsDataURL(f);});
function parsedAdjustments(){
 if(!isProsoft.value||!readingAdjustments.value.trim())return {};
 let adjustments;try{adjustments=JSON.parse(readingAdjustments.value);}catch{throw new Error('Ajustes de leitura: informe um objeto JSON válido.');}
 if(!adjustments||Array.isArray(adjustments)||typeof adjustments!=='object'||Object.keys(adjustments).some(key=>!['group_natures','nature_overrides'].includes(key)))throw new Error('Ajustes permitidos: group_natures e nature_overrides.');
 for(const key of Object.keys(adjustments)){if(!adjustments[key]||Array.isArray(adjustments[key])||typeof adjustments[key]!=='object'||Object.values(adjustments[key]).some(value=>!['debit','credit'].includes(value)))throw new Error('Cada ajuste deve mapear um código para debit ou credit.');}
 return adjustments;
}
function exportPayload(){
 const adjustments=parsedAdjustments();
 return {format:format.value,plan_code:planCode.value,...(format.value!=='native'?{properties:{...JSON.parse(JSON.stringify(properties.value)),...(adjustments.group_natures?{group_natures:adjustments.group_natures}:{})}}:{}),allow_ascii:false};
}
async function prepare(){
 if(!canPrepare.value)return;
 invalidate();const n=sequence,cid=state.companyId;busy.value=true;
 try{
  let payload,path;
  if(mode.value==='export'){payload=exportPayload();path='/account-plans/export-preview';}
  else{payload={format:mode.value==='default'?'default':format.value,options:{identity_mode:identityByAccess.value?'access':'traditional',...(needsProperties.value?{properties:JSON.parse(JSON.stringify(properties.value))}:{}),encoding:encoding.value,...(isProsoft.value&&trimGroups.value?{trailing_zero_policy:'trim_groups'}:{})}};path='/account-plans/preview';
   if(mode.value==='import'&&isProsoft.value&&readingAdjustments.value.trim()){
    const adjustments=parsedAdjustments();
    if(adjustments.group_natures)payload.options.properties={...(payload.options.properties||{}),group_natures:adjustments.group_natures};
    if(adjustments.nature_overrides)payload.options.nature_overrides=adjustments.nature_overrides;
   }
   if(mode.value==='import'){payload.filename=file.value.name;payload.content_base64=await encode(file.value);}}
  if(n!==sequence||cid!==state.companyId)return;
  const response=await api(scope(path,cid),{method:'POST',body:payload});
  if(n===sequence&&cid===state.companyId)preview.value=response;
 }catch(e){if(n===sequence)error.value=e.message;}finally{if(n===sequence)busy.value=false;}
}
async function confirm(){
 if(!canConfirm.value)return;
 const n=sequence,cid=state.companyId,p=preview.value;busy.value=true;error.value='';
 try{
  if(mode.value==='export'){
   const response=await api(scope('/account-plans/export-confirm',cid),{method:'POST',body:{...exportPayload(),preview_hash:p.preview_hash,allow_ascii:allowAscii.value,destination_reviewed:true}});
   if(n!==sequence||cid!==state.companyId)return;
   const bytes=Uint8Array.from(atob(response.content_base64),c=>c.charCodeAt(0));
   const url=URL.createObjectURL(new Blob([bytes],{type:format.value==='native'?'application/json':'text/plain'}));
   const link=document.createElement('a');link.href=url;link.download=fileName('',response.filename||'plano-contas.txt');document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
   result.value='Arquivo preparado. Confira o salvamento na janela de downloads.';notify(result.value);
  }else if(activationMode.value==='global'){
   const response=await api(scope(`/global-account-plans/batches/${p.id}/publish`,cid),{method:'POST',body:{name:globalName.value.trim(),description:'',preview_hash:p.preview_hash,reason:reason.value.trim(),properties_reviewed:true,global_visibility_reviewed:true}});
   if(n!==sequence||cid!==state.companyId)return;
   result.value=`Versão global #${response.id} publicada com ${response.record_count} contas. Selecione-a na biblioteca para usar nesta empresa.`;changed();notify(result.value);
  }else{
   const response=await api(scope(`/account-plans/${p.id}/confirm`,cid),{method:'POST',body:{preview_hash:p.preview_hash,reason:reason.value.trim(),properties_reviewed:true,activation_mode:activationMode.value}});
   if(n!==sequence||cid!==state.companyId)return;
   savedBatchId.value=p.id;
   result.value=response.reference_only?`${response.record_count} registros preservados como referência, sem ativar contas para lançamentos.`:response.duplicate?'Este lote já foi confirmado. Nenhuma conta duplicada.':`${response.created} contas criadas; ${response.preserved} contas existentes preservadas.`;changed();notify(result.value);historyLoaded.value=false;
  }
  preview.value=null;reviewed.value=false;destinationReviewed.value=false;
 }catch(e){if(n===sequence)error.value=e.message;}finally{if(n===sequence)busy.value=false;}
}
async function loadHistory(){
 if(busy.value||!state.companyId||!can('accounting.imports'))return;
 const n=sequence,cid=state.companyId;busy.value=true;error.value='';
 try{const response=await api(scope('/account-plans',cid));if(n===sequence&&cid===state.companyId){history.value=rows(response);historyLoaded.value=true;}}
 catch(e){if(n===sequence)error.value=e.message;}finally{if(n===sequence)busy.value=false;}
}
function downloadManifest(){
 if(!preview.value?.manifest)return;
 const url=URL.createObjectURL(new Blob([JSON.stringify(preview.value.manifest,null,2)],{type:'application/json'}));
 const link=document.createElement('a');link.href=url;link.download='manifesto-plano-contas.json';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
}
const describe=value=>typeof value==='string'?value:JSON.stringify(value);
</script>

<template>
<GlobalAccountPlanPanel/>
<section class="panel account-plan-panel" aria-label="Intercâmbio de plano de contas">
 <div class="plan-actions"><div><h2>Plano padrão e intercâmbio</h2><p>Importe ou exporte para o Escritura Integrada e a Prosoft, sempre com prévia.</p></div><button class="button outline" :aria-expanded="expanded" :disabled="busy" @click="expanded?cancel():expanded=true">{{expanded?'Fechar':'Abrir ferramentas'}}</button></div>
 <template v-if="expanded">
  <p class="context-notice">Empresa: {{company?.code}} · {{company?.trade_name||company?.name}}. A importação adiciona contas e preserva as existentes; conflitos devem ser corrigidos antes de ativar contas. Você também pode guardar o lote completo apenas como referência, sem alterar o plano ativo.</p>
  <div v-if="error" class="message error" role="alert">{{error}}</div><p v-if="result" class="message success" role="status">{{result}}</p><a v-if="savedBatchId&&canExport" class="text-button" :href="'/api'+scope(`/account-plans/${savedBatchId}/native`)" download>Baixar carga completa em JSON nativo</a>
  <fieldset :disabled="busy" class="plan-fields">
   <legend>Preparar operação</legend>
   <div class="form-grid">
    <label>Operação<select v-model="mode"><option value="import" :disabled="!canImport">Importar arquivo</option><option value="default" :disabled="!canImport">Aplicar plano contábil padrão</option><option value="export" :disabled="!canExport">Exportar contas da empresa</option></select></label>
    <label v-if="mode!=='default'">Formato<select v-model="format"><option v-for="f in formats" :key="f.value" :value="f.value">{{f.label}}</option></select></label>
    <label v-if="mode==='import'">Arquivo de origem<input ref="input" type="file" accept=".json,.txt,.txtx,.csv" @change="choose"/><small v-if="file">{{file.name}} · {{Math.ceil(file.size/1024)}} KB</small></label>
    <label v-if="mode==='export'&&isProsoft">Código do plano na Prosoft<input v-model="planCode" maxlength="4" pattern="[0-9]{4}" placeholder="0050"/></label>
   </div>
   <p v-if="mode==='default'">O plano padrão será acrescentado sem substituir cadastros. Confira a estrutura proposta na prévia antes de aplicar.</p>
   <label v-if="mode==='import'" class="choice-card"><input v-model="identityByAccess" type="checkbox"/><span>Identificar contas por acesso, preservando classificadores repetidos como agrupamentos hierárquicos. Contas com acessos diferentes não serão mescladas nem renumeradas. Revise esta decisão antes de ativar.</span></label>
   <template v-if="needsProperties">
    <p class="message warning">O layout Prosoft de 204 posições não inclui propriedades do plano. Informe e revise a máscara e os grupos com o responsável contábil. Não deduzimos essas propriedades do arquivo.</p>
    <div class="form-grid three">
     <label>Máscara do classificador *<input v-model="properties.mask" placeholder="#.#.##.### (exemplo)" required/></label>
     <label>Acesso gerado<select v-model="properties.generated_access"><option value="0">0 · Não</option><option value="1">1 · Sim</option></select></label>
     <label>Tipo do plano<select v-model="properties.plan_type"><option value="0">0</option><option value="1">1</option><option value="2">2</option></select></label>
     <label v-for="(label,key) in groupLabels" :key="key">Grupo · {{label}}<input v-model="properties.groups[key]" maxlength="1" pattern="[1-9]"/></label>
     <label>Máscara especial<input v-model="properties.special_mask"/></label>
    </div>
   </template>
   <template v-if="mode==='import'&&isProsoft">
    <label>Codificação<select v-model="encoding"><option value="cp1252">Windows-1252</option><option value="utf-8">UTF-8</option></select></label>
    <label class="choice-card"><input v-model="trimGroups" type="checkbox"/><span>Autorizo remover grupos finais compostos apenas por zeros (trim_groups). Zeros podem ser parte legítima do classificador; reconheço a ambiguidade e conferirei o resultado na prévia.</span></label>
   </template>
   <template v-if="isProsoft">
    <label>Ajustes explícitos de natureza (JSON, opcional)<textarea v-model="readingAdjustments" rows="3" placeholder='{"group_natures":{"6":"debit"},"nature_overrides":{"12345":"credit"}}'/><small>Exemplo ilustrativo, não aplicado automaticamente. group_natures define a natureza de um grupo sem mapeamento; nature_overrides define a natureza pelo código de acesso. Use debit (devedora) ou credit (credora), somente após conferir a origem. Na exportação, somente group_natures é utilizado; nature_overrides é exclusivo da leitura.</small></label>
   </template>
  </fieldset>
  <div class="plan-actions"><button class="button primary" :disabled="!canPrepare" @click="prepare">{{busy?'Processando…':'Gerar prévia'}}</button><button class="button" :disabled="busy" @click="cancel">Cancelar</button><button v-if="can('accounting.imports')" class="button outline" :disabled="busy" @click="loadHistory">Consultar histórico</button></div>
  <p v-if="!canImport&&!canExport" class="message warning">Você não tem permissão para importar ou exportar planos de contas.</p>
  <section v-if="preview" class="plan-preview" aria-label="Prévia do plano de contas">
   <h3>Prévia · {{mode==='export'?'exportação':'importação'}}</h3>
   <template v-if="mode!=='export'">
    <p><strong>{{preview.record_count}} registros no total</strong> · {{preview.created}} a criar · {{preview.preserved}} existentes preservados · {{conflictCount}} conflitos</p>
    <div v-if="conflictCount" class="message error" role="alert"><strong>Ativação de contas bloqueada no modo de importação tradicional. Classificadores repetidos podem ser preservados em versão global; acessos repetidos continuam bloqueados.</strong><ul><li v-for="(conflict,i) in conflicts.slice(0,100)" :key="i">{{conflict.access_code}}: {{conflict.reason}}</li></ul><p v-if="conflictCount>conflicts.length">Exibidos {{conflicts.length}} de {{conflictCount}} conflitos.</p></div>
    <ul v-if="preview.warnings?.length" class="message warning"><li v-for="(warning,i) in preview.warnings.slice(0,100)" :key="i">{{describe(warning)}}</li></ul>
    <p v-if="warningCount">{{warningCount}} avisos no total; {{preview.warnings?.length||0}} exibidos.</p><a v-if="canExport" class="text-button" :href="'/api'+scope(`/account-plans/${preview.id}/native`)" download>Baixar carga completa em JSON nativo (todos os registros)</a>
    <details><summary>Propriedades interpretadas do plano</summary><pre>{{JSON.stringify(preview.properties,null,2)}}</pre></details>
    <p>Exibição limitada às primeiras 100 contas ({{visibleAccounts.length}} exibidas de {{preview.record_count}}). A confirmação considera o lote completo.</p>
    <div class="table-scroll"><table><thead><tr><th>Acesso</th><th>Classificador</th><th>Nome</th><th>Tipo</th><th>Natureza</th></tr></thead><tbody><tr v-for="(account,i) in visibleAccounts" :key="i"><td>{{account.access_code}}</td><td>{{account.classifier}}</td><td>{{account.name}}</td><td>{{account.analytical?'Analítica':'Sintética'}}</td><td>{{account.nature==='debit'?'Devedora':account.nature==='credit'?'Credora':account.nature}}</td></tr></tbody></table></div>
    <label>Destino do lote<select v-model="activationMode" :disabled="busy"><option value="activate" :disabled="!canActivate||preview.can_confirm===false||conflictCount>0">Ativar contas no plano da empresa</option><option value="reference">Guardar como referência sem ativar contas</option><option v-if="isAdmin" value="global">Publicar versão na biblioteca global</option></select></label>
    <p v-if="activationMode==='reference'" class="message warning">Todos os {{preview.record_count}} registros serão preservados como referência, inclusive classificadores repetidos. Nenhuma conta será criada ou alterada no plano ativo e esses registros não estarão disponíveis para lançamentos. O JSON nativo completo permanece disponível para download.</p>
    <template v-if="activationMode==='global'"><label>Nome da versão global *<input v-model="globalName" :disabled="busy" maxlength="200" placeholder="Plano do escritório"/></label><label class="choice-card"><input v-model="globalReviewed" type="checkbox" :disabled="busy"/><span>Autorizo disponibilizar o conteúdo integral deste plano, inclusive nomes de contas e metadados, para todas as empresas desta instalação. Os bytes originais serão preservados. A publicação não ativa contas automaticamente.</span></label></template>
    <label>Motivo da importação *<textarea v-model="reason" :disabled="busy" maxlength="1000"/></label>
    <label class="choice-card"><input v-model="reviewed" type="checkbox" :disabled="busy"/><span>Revisei as propriedades, a máscara, os grupos e os avisos desta prévia para a empresa indicada.</span></label>
   </template>
   <template v-else>
    <p>{{preview.filename}} · {{preview.manifest?.records}} registros</p><p class="hash">SHA-256: {{preview.sha256}}</p>
    <ul v-if="preview.manifest?.warnings?.length" class="message warning"><li v-for="(warning,i) in preview.manifest.warnings.slice(0,100)" :key="i">{{describe(warning)}}</li></ul>
    <details><summary>Amostra do arquivo</summary><pre>{{typeof preview.sample==='string'?preview.sample:JSON.stringify(preview.sample,null,2)}}</pre></details>
    <div v-if="preview.manifest?.needs_ascii_review" class="message warning"><strong>A conversão para ASCII altera textos.</strong><ul><li v-for="(change,i) in visibleChanges" :key="i">{{describe(change)}}</li></ul><p>Até 100 alterações exibidas de {{preview.manifest.text_changes?.length||0}}. A autorização abrange todas as alterações do manifesto.</p><button type="button" class="button outline" @click="downloadManifest">Baixar manifesto completo</button><label class="check-label"><input v-model="allowAscii" type="checkbox" :disabled="busy"/>Revisei e autorizo as alterações de texto para ASCII.</label></div>
    <label class="choice-card"><input v-model="destinationReviewed" type="checkbox" :disabled="busy"/><span>Conferi o formato e as propriedades para o sistema de destino. O arquivo será baixado, não enviado automaticamente à Prosoft.</span></label>
   </template>
   <button class="button primary" :disabled="!canConfirm" @click="confirm">{{mode==='export'?'Confirmar e baixar arquivo':activationMode==='reference'?'Guardar referência sem ativar contas':activationMode==='global'?'Publicar versão global':'Confirmar ativação de contas'}}</button>
  </section>
  <section v-if="historyLoaded"><h3>Histórico de lotes · empresa atual</h3><p v-if="!history.length">Nenhum lote encontrado.</p><div v-else class="table-scroll"><table><thead><tr><th>Lote / arquivo</th><th>Formato</th><th>Estado</th><th>Origem</th></tr></thead><tbody><tr v-for="batch in history.slice(0,100)" :key="batch.id"><td>{{batch.filename||batch.name||`Lote ${batch.id}`}}</td><td>{{batch.format}}</td><td>{{batch.status==='reference'?'Referência · sem contas ativas':batch.status}}</td><td><a v-if="canExport" class="text-button" :href="'/api'+scope(`/account-plans/${batch.id}/original`)" download>Baixar original</a><a v-if="canExport" class="text-button" :href="'/api'+scope(`/account-plans/${batch.id}/native`)" download>Baixar JSON nativo completo</a></td></tr></tbody></table></div><p v-if="history.length>100">Exibidos os 100 primeiros lotes de {{history.length}}.</p></section>
 </template>
</section>
</template>

<style scoped>
.account-plan-panel{padding:18px;display:grid;gap:16px;margin-bottom:18px}.account-plan-panel h2,.account-plan-panel h3,.account-plan-panel p{margin:0}.account-plan-panel h2{font-size:17px}.account-plan-panel p{line-height:1.6}.plan-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.plan-actions>div:first-child{flex:1;min-width:220px}.plan-fields{border:1px solid var(--border,#dce1e8);border-radius:8px;padding:16px;display:grid;gap:16px;min-width:0}.plan-fields legend{padding:0 6px;font-weight:600}.plan-preview{display:grid;gap:14px;border-top:1px solid var(--border,#dce1e8);padding-top:16px}.plan-preview>button{justify-self:start}.account-plan-panel pre{max-height:240px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}.account-plan-panel .table-scroll{max-height:360px}.account-plan-panel .hash{overflow-wrap:anywhere;font-size:12px}.account-plan-panel ul.message{display:block;padding-left:32px}.account-plan-panel fieldset:disabled{opacity:.75}
</style>
