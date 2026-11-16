<script setup>
import {ref,computed,watch,onActivated,onDeactivated,onUnmounted,markRaw} from 'vue';
import BaseModal from '../components/BaseModal.vue';
import Icon from '../components/Icon.vue';
import {state,company,api,scope,can,changed,captureContext,contextMatches} from '../lib/workspace';
import {money,date,normalized,uid} from '../lib/format';
import {useSuggestedMonth} from '../lib/context-preferences.js';
const direction=ref('outgoing'),preview=ref(null),previewLoading=ref(false);
const config=ref(null),mode=ref('individual'),documents=ref([]),models=ref([]);
const loading=ref(false),busy=ref(false),error=ref(''),result=ref(null),intent=ref(null);
const query=ref(''),month=ref(state.period.slice(5)),status=ref('all'),page=ref(1),pageSize=ref(50);
const selectedIds=ref([]),modelIds=ref({}),commonModel=ref(''),reason=ref('');
const trace=ref(null),traceLoading=ref(false),traceError=ref('');
let alive=true,active=true,sequence=0,traceSequence=0,reader=null,scheduled=null,previewReader=null,previewSequence=0;
useSuggestedMonth(state,month);
const modeDirty=computed(()=>direction.value==='outgoing'&&!!config.value&&mode.value!==config.value.mode);
const endpoint=computed(()=>direction.value==='incoming'?'/fiscal-purchases-accounting':'/fiscal-sales-accounting');
const directionLabel=computed(()=>direction.value==='incoming'?'entradas':'saídas');
const permitted=computed(()=>can('fiscal.documents')&&can('accounting.accounts')&&can('accounting.histories'));
const canGenerate=computed(()=>permitted.value&&can('accounting.journals','create'));
const locked=computed(()=>busy.value||!!intent.value||state.contextBusy);
const eligible=d=>d.direction===direction.value&&d.status==='booked'&&!d.journal_id&&!d.book_cancellation&&d.document_state!=='cancelled'&&d.total_cents>0;
const selection=computed(()=>documents.value.filter(d=>selectedIds.value.includes(d.id)));
const filtered=computed(()=>documents.value.filter(d=>(!month.value||d.period.slice(5)===month.value)&&
 (status.value==='all'||(status.value==='eligible'?eligible(d):status.value==='accounted'?!!d.journal_id:!eligible(d)&&!d.journal_id))&&
 normalized(`${d.number} ${d.partner_name} ${d.cfop} ${d.key}`).includes(normalized(query.value))));
const pageCount=computed(()=>Math.max(1,Math.ceil(filtered.value.length/pageSize.value)));
const visible=computed(()=>filtered.value.slice((page.value-1)*pageSize.value,page.value*pageSize.value));
const selectedTotal=computed(()=>selection.value.reduce((n,d)=>n+BigInt(d.total_cents),0n));
const wholeFormatter=new Intl.NumberFormat('pt-BR');
const selectedAmount=computed(()=>`R$ ${wholeFormatter.format(selectedTotal.value/100n)},${String(selectedTotal.value%100n).padStart(2,'0')}`);
const availableModels=computed(()=>models.value.filter(m=>m.active&&m.data.status==='validated'&&[direction.value,'both'].includes(m.data.direction)));
const modelFits=(m,d)=>m&&m.data.valid_from<=d.posting_date&&(!m.data.valid_to||m.data.valid_to>=d.posting_date);
const modelFor=id=>availableModels.value.find(m=>m.id===Number(id));
const closure=computed(()=>selection.value.find(d=>state.yearLocks?.fiscal?.[d.period]?.closed||state.yearLocks?.accounting?.[d.period]?.closed)?.period||'');
const selectionIssue=computed(()=>!selection.value.length?'Selecione notas escrituradas sem lançamento.':
 selectedIds.value.length!==selection.value.length?'Atualize a consulta e selecione novamente.':
 selection.value.length>1000?'A API aceita até 1000 notas por solicitação. Refine a seleção.':
 selection.value.some(d=>!eligible(d))?'Há notas que já não estão aptas. Atualize a consulta.':
 closure.value?`A competência ${closure.value} está fechada no fiscal ou contábil. Reabra para contabilizar.`:
 selection.value.some(d=>!modelFits(modelFor(modelIds.value[d.id]),d))?'Escolha um modelo revisado e vigente para cada nota selecionada.':'');
const canSubmit=computed(()=>active&&alive&&canGenerate.value&&!locked.value&&!loading.value&&!!config.value&&!modeDirty.value&&!selectionIssue.value&&!state.editor);
function clearSelection(){selectedIds.value=[];modelIds.value={};commonModel.value='';reason.value='';}
function contextKey(){return `${state.companyId}:${state.module}:${state.period}:${direction.value}`;}
function valid(n,key){return alive&&active&&n===sequence&&key===contextKey()&&!state.contextBusy;}
function release(owner){if(state.editor===owner)state.editor=null;}
function clearPreview(){previewSequence++;previewReader?.abort();preview.value=null;previewLoading.value=false;}
function resetContext(){clearPreview();sequence++;traceSequence++;reader?.abort();trace.value=null;traceLoading.value=false;traceError.value='';config.value=null;documents.value=[];models.value=[];mode.value='individual';result.value=null;intent.value=null;error.value='';loading.value=false;clearSelection();}
async function load({discardIntent=false}={}){
 if(!alive||!active||!state.companyId||state.contextBusy||busy.value)return;
 clearPreview();const n=++sequence,key=contextKey(),cid=state.companyId,year=state.period.slice(0,4),draft=mode.value,dirty=modeDirty.value;
 reader?.abort();reader=new AbortController();loading.value=true;error.value='';
 try{
  if(!permitted.value){config.value=null;documents.value=[];models.value=[];clearSelection();return;}
  const [cfg,docs,mods]=await Promise.all([api(scope('/fiscal-sales-accounting/settings',cid),{signal:reader.signal}),api(scope(`/documents?year=${year}`,cid),{signal:reader.signal}),api(scope('/masters/accounting_model',cid),{signal:reader.signal})]);
  if(!valid(n,key))return;
  config.value=cfg;mode.value=dirty&&!discardIntent?draft:cfg.mode;documents.value=docs.filter(d=>d.direction===direction.value);models.value=mods;
  if(discardIntent){intent.value=null;result.value=null;clearSelection();}
 }catch(e){if(valid(n,key)&&e.name!=='AbortError')error.value=e.message;}
 finally{if(alive&&n===sequence)loading.value=false;}
}
function scheduleLoad(){clearTimeout(scheduled);scheduled=setTimeout(()=>load(),0);}
watch(direction,()=>{resetContext();scheduleLoad();},{flush:'sync'});
watch([selectedIds,modelIds,reason,mode,()=>config.value?.version],clearPreview,{deep:true,flush:'sync'});
watch([()=>state.companyId,()=>state.module,()=>state.period],()=>{resetContext();scheduleLoad();},{flush:'sync'});
watch([()=>JSON.stringify(state.session?.permissions),()=>state.session?.user?.role],()=>{resetContext();scheduleLoad();},{flush:'sync'});
watch([()=>state.contextBusy,()=>state.refresh],()=>{
 if(state.contextBusy){clearPreview();sequence++;reader?.abort();traceSequence++;trace.value=null;return;}scheduleLoad();});
watch([query,month,status,pageSize],()=>{page.value=1;if(!intent.value)clearSelection();},{flush:'sync'});
watch(pageCount,n=>page.value=Math.min(page.value,n));
onActivated(()=>{active=true;scheduleLoad();});
onDeactivated(()=>{clearPreview();active=false;sequence++;traceSequence++;reader?.abort();clearTimeout(scheduled);trace.value=null;traceLoading.value=false;});
onUnmounted(()=>{clearPreview();alive=false;active=false;sequence++;traceSequence++;reader?.abort();clearTimeout(scheduled);});
scheduleLoad();
function toggle(d,checked){if(locked.value||loading.value||!canGenerate.value||!eligible(d))return;selectedIds.value=checked?[...new Set([...selectedIds.value,d.id])]:selectedIds.value.filter(id=>id!==d.id);if(checked&&!modelIds.value[d.id])modelIds.value[d.id]='';}
function selectFiltered(){if(locked.value||loading.value||!canGenerate.value)return;const ids=filtered.value.filter(eligible).map(d=>d.id);if(ids.length>1000){error.value='A consulta tem mais de 1000 notas aptas. Refine os filtros ou selecione manualmente.';return;}selectedIds.value=ids;for(const id of ids)if(!modelIds.value[id])modelIds.value[id]='';error.value='';}
function applyModel(){if(locked.value||!selection.value.length)return;const model=modelFor(commonModel.value);if(!model||selection.value.some(d=>!modelFits(model,d))){error.value='O modelo deve estar revisado e vigente em todas as notas selecionadas.';return;}modelIds.value={...modelIds.value,...Object.fromEntries(selection.value.map(d=>[d.id,model.id]))};error.value='';}
async function saveMode(){
 if(direction.value!=='outgoing'||!config.value||!modeDirty.value||!can('accounting.accounts','edit')||locked.value||loading.value||state.editor)return;
 const n=sequence,key=contextKey(),ctx=captureContext(),cid=state.companyId,value=mode.value,owner=markRaw({name:'Configuração da integração contábil',companyId:cid});
 busy.value=true;error.value='';state.editor=owner;
 try{const saved=await api(scope('/fiscal-sales-accounting/settings',cid),{method:'PUT',context:ctx,body:{version:config.value.version,mode:value}});if(valid(n,key)){config.value=saved;mode.value=saved.mode;result.value=null;}}
 catch(e){if(valid(n,key))error.value=`${e.message} Recarregue os parâmetros para conferir o modo salvo.`;}
 finally{release(owner);if(alive){busy.value=false;if(active&&(key!==contextKey()||!config.value))scheduleLoad();}}
}
async function generate(replay=false){
 if(!alive||!active)return;
 if(replay){if(!intent.value||busy.value||state.contextBusy||!contextMatches(intent.value.context)||intent.value.key!==contextKey()||!active||!canGenerate.value||state.editor)return;}
 else{if(!canSubmit.value)return;intent.value={key:contextKey(),context:captureContext(),endpoint:endpoint.value,body:{settings_version:config.value.version,idempotency_key:uid(),reason:reason.value.trim(),entries:selection.value.map(d=>({document_id:d.id,version:d.version,model_id:Number(modelIds.value[d.id])}))}};}
 const pending=intent.value,n=sequence,key=contextKey(),cid=pending.context.companyId,owner=markRaw({name:'Integração contábil fiscal',companyId:cid});
 clearPreview();busy.value=true;state.editor=owner;error.value='';result.value=null;
 try{const response=await api(scope(`${pending.endpoint}/generate`,cid),{method:'POST',context:pending.context,body:pending.body});
  if(!valid(n,key))return;result.value=response;intent.value=null;clearSelection();changed();
 }catch(e){if(valid(n,key)){
  if(e.status&&e.status<500){intent.value=null;error.value=e.message;}
  else error.value='O resultado não foi confirmado. Confira os vínculos atualizando a consulta ou repita a mesma solicitação; a repetição usa a mesma chave e não duplica lançamentos.';
 }}finally{release(owner);if(alive){busy.value=false;if(active&&(key!==contextKey()||!config.value))scheduleLoad();}}
}
async function showPreview(){
 if(!canSubmit.value||!can('accounting.journals'))return;
 clearPreview();const n=previewSequence,seq=sequence,key=contextKey(),cid=state.companyId;
 previewReader=new AbortController();previewLoading.value=true;error.value='';
 const body={settings_version:config.value.version,reason:reason.value.trim(),entries:selection.value.map(d=>({document_id:d.id,version:d.version,model_id:Number(modelIds.value[d.id])}))};
 try{const response=await api(scope(`${endpoint.value}/preview`,cid),{method:'POST',context:captureContext(),signal:previewReader.signal,body});
  if(n===previewSequence&&valid(seq,key))preview.value=response;
 }catch(e){if(n===previewSequence&&valid(seq,key)&&e.name!=='AbortError')error.value=e.message;}
 finally{if(alive&&n===previewSequence)previewLoading.value=false;}
}
function closeTrace(){traceSequence++;trace.value=null;traceLoading.value=false;traceError.value='';}
async function showTrace(kind,id){
 if(!active||state.contextBusy||!can('accounting.journals')||!can('fiscal.documents'))return;
 const n=++traceSequence,key=contextKey(),cid=state.companyId;trace.value={kind,data:null};traceLoading.value=true;traceError.value='';
 try{const path=kind==='journal'?`/fiscal-sales-accounting/journals/${id}/sources`:`/documents/${id}/trace`;const response=await api(scope(path,cid));if(alive&&active&&n===traceSequence&&key===contextKey()&&!state.contextBusy)trace.value={kind,data:response};}
 catch(e){if(alive&&active&&n===traceSequence&&key===contextKey())traceError.value=e.message;}
 finally{if(alive&&n===traceSequence)traceLoading.value=false;}
}
const traceSources=computed(()=>trace.value?.data?.sources||trace.value?.data?.accounting_sources||[]);
const traceJournals=computed(()=>trace.value?.data?.journal?[trace.value.data.journal]:trace.value?.data?.journals||[]);
const eligibilityLabel=d=>d.journal_id?'Já contabilizada':d.document_state==='cancelled'||d.book_cancellation?'Cancelada':d.status!=='booked'?'Ainda não escriturada':!d.total_cents?'Sem valor contábil':'Apta à contabilização';
const classLabel=c=>[c.cfop&&`CFOP ${c.cfop}`,c.cst_icms&&`CST ${c.cst_icms}`,c.csosn&&`CSOSN ${c.csosn}`,c.ncm&&`NCM ${c.ncm}`,c.rate!=null&&`Alíquota ${c.rate}%`,c.cclass_trib&&`ClassTrib ${c.cclass_trib}`,...Object.entries(c.declared_tax_classifications||{}).map(([k,v])=>`${k}: ${v}`)].filter(Boolean).join(' · ')||'Sem classificação adicional informada';
</script>
<template><div class="view sales-accounting-view">
<header class="view-heading"><div><div class="eyebrow">FISCAL ↔ CONTÁBIL</div><h1>Integração Contábil</h1><p>{{company?.code}} · {{company?.trade_name||company?.name}} · exercício {{state.period.slice(0,4)}}</p></div><button class="button outline" :disabled="busy||loading||state.contextBusy" @click="load({discardIntent:true})">Atualizar consulta e parâmetros</button></header>
<section class="panel sales-configuration"><label>Sentido da integração<select v-model="direction" :disabled="locked"><option value="outgoing">Saídas</option><option value="incoming">Entradas · individual por nota</option></select></label><p v-if="direction==='incoming'" class="message info">Entradas geram um lançamento por nota. O modo salvo para saídas permanece preservado.</p></section>
<p class="message info">O modo das saídas vale para esta integração de notas já escrituradas. Novas seleções criam lançamentos complementares, inclusive no mesmo dia. O Diário Consolidado, em Relatórios, somente consulta lançamentos existentes.</p>
<p class="message subtle">Integração em desenvolvimento: a importação automática e a distribuição contábil por itens continuam pendentes. Os botões individuais da escrituração mantêm o fluxo anterior.</p>
<p v-if="!permitted" class="message warning" role="status">Para consultar esta integração são necessárias permissões de leitura de documentos fiscais, contas e modelos contábeis.</p>
<p v-if="loading" role="status">Carregando notas e parâmetros desta empresa…</p><p v-if="error" class="message error" role="alert">{{error}}</p>
<section v-if="config&&direction==='outgoing'" class="panel sales-configuration" aria-label="Configuração contábil de saídas da empresa"><h2>Modo das saídas desta empresa</h2><div class="form-grid"><label>Geração de lançamentos<select v-model="mode" :disabled="locked||loading||!can('accounting.accounts','edit')"><option value="individual">Individual · um lançamento por nota</option><option value="daily">Diário · agrupar por data, classificação e contas</option></select></label><div class="actions"><span>{{modeDirty?'Escolha ainda não salva':`Modo salvo: ${config.mode==='daily'?'diário':'individual'}`}}</span><button type="button" class="button outline" :disabled="locked||loading||!modeDirty||!can('accounting.accounts','edit')" @click="saveMode">Salvar modo da empresa</button></div></div><p>{{config.notice}}</p></section>
<section v-if="permitted" class="panel" aria-label="Seleção fiscal para contabilização"><div class="table-toolbar"><label>Pesquisar notas<input v-model="query" :disabled="locked" placeholder="Número, participante, CFOP ou chave"/></label><label>Competência da escrituração<select v-model="month" :disabled="locked"><option value="">Todo o exercício</option><option v-for="m in 12" :key="m" :value="String(m).padStart(2,'0')">{{String(m).padStart(2,'0')}}/{{state.period.slice(0,4)}}</option></select></label><label>Situação contábil<select v-model="status" :disabled="locked"><option value="all">Todas as notas</option><option value="eligible">Aptas à contabilização</option><option value="accounted">Já contabilizadas</option><option value="other">Demais situações</option></select></label><label>Notas por página<select v-model.number="pageSize" :disabled="locked"><option :value="50">50</option><option :value="100">100</option><option :value="250">250</option></select></label></div>
<div class="sales-selection"><span aria-live="polite">{{filtered.length}} {{directionLabel}} na consulta · {{selection.length}} selecionadas · {{selectedAmount}}</span><div class="actions"><button class="button small" :disabled="locked||loading||!canGenerate" @click="selectFiltered">Selecionar aptas da consulta</button><button class="button small" :disabled="locked||!selectedIds.length" @click="clearSelection">Limpar seleção contábil</button></div><small>Selecionar a consulta inclui outras páginas. Mudar filtros limpa a seleção; mudar apenas a página a preserva.</small></div>
<div class="table-scroll"><table><thead><tr><th>Selecionar</th><th>Nota / participante</th><th>Escrituração</th><th>CFOP</th><th class="right">Total</th><th>Situação</th><th>Modelo contábil</th><th>Origem</th></tr></thead><tbody><tr v-for="d in visible" :key="d.id"><td><input type="checkbox" :aria-label="`Contabilizar nota ${d.number}`" :checked="selectedIds.includes(d.id)" :disabled="locked||loading||!canGenerate||!eligible(d)" @change="toggle(d,$event.target.checked)"/></td><td><strong>{{d.number}}</strong><small class="cell-secondary">{{d.partner_name}} · modelo {{d.model}} · série {{d.series}}</small></td><td>{{date(d.posting_date)}}<small class="cell-secondary">Emissão {{date(d.issue_date)}}</small></td><td>{{d.cfop||'Não informado'}}</td><td class="right">{{money(d.total_cents)}}</td><td>{{eligibilityLabel(d)}}</td><td><select v-if="selectedIds.includes(d.id)" v-model.number="modelIds[d.id]" :aria-label="`Modelo contábil da nota ${d.number}`" :disabled="locked"><option value="">Selecione um modelo</option><option v-for="m in availableModels.filter(m=>modelFits(m,d))" :key="m.id" :value="m.id">{{m.code}} · {{m.name}}</option></select><span v-else>—</span></td><td><button type="button" class="button small" :disabled="state.contextBusy||!can('accounting.journals')" @click="showTrace('document',d.id)">Origem da nota {{d.number}}</button></td></tr></tbody></table><p v-if="!loading&&!filtered.length" class="report-note">Nenhuma nota nos filtros selecionados.</p></div>
<footer class="table-footer"><span>Página {{page}} de {{pageCount}}</span><div class="actions"><button class="button small" :disabled="page<=1||loading" @click="page--">Página anterior</button><button class="button small" :disabled="page>=pageCount||loading" @click="page++">Página seguinte</button></div></footer>
<div class="sales-generation"><h2>Contabilizar seleção</h2><p>O modelo contabiliza o total da nota. Selecione modelos revisados com as contas da empresa; não há escolha automática de contas nem rateio por item.</p><div class="form-grid"><label>Modelo comum para as selecionadas<select v-model.number="commonModel" :disabled="locked||!selection.length"><option value="">Selecione um modelo</option><option v-for="m in availableModels" :key="m.id" :value="m.id">{{m.code}} · {{m.name}}</option></select></label><button type="button" class="button outline" :disabled="locked||!selection.length||!commonModel" @click="applyModel">Aplicar modelo às selecionadas</button><label class="span-2">Histórico da geração (opcional)<input v-model="reason" :disabled="locked" maxlength="1000"/></label></div><p v-if="!canGenerate" class="message info">Seu usuário pode consultar, mas não possui as permissões necessárias para gerar lançamentos.</p><p v-if="modeDirty" class="message info">Salve o modo da empresa antes de gerar.</p><p v-if="selectionIssue&&selectedIds.length" class="message info">{{selectionIssue}}</p><p v-if="intent&&!busy" class="message warning">Há uma solicitação sem resultado confirmado. Repetir envia exatamente a mesma seleção e chave. Atualizar consulta e parâmetros permite conferir os vínculos antes de selecionar novamente.</p><button type="button" class="button outline" :disabled="!canSubmit||previewLoading||!can('accounting.journals')" @click="showPreview">{{previewLoading?'Consultando prévia…':'Consultar prévia contábil'}}</button><button v-if="intent&&!busy" type="button" class="button primary" :disabled="!canGenerate||state.contextBusy" @click="generate(true)">Repetir a mesma solicitação</button><button v-else type="button" class="button primary" :disabled="!canSubmit" @click="generate(false)"><Icon v-if="busy" name="loading"/>{{busy?'Processando…':'Gerar lançamentos da seleção'}}</button></div></section>
<section v-if="preview" class="panel sales-result" aria-label="Prévia contábil"><h2>Prévia contábil · somente leitura</h2><p>{{preview.created_count}} lançamento(s) previsto(s) · {{preview.accounted_count}} nota(s) · {{preview.skipped.length}} ignorada(s). Nenhum lançamento foi gerado. A execução revalida os dados atuais.</p><article v-for="(j,i) in preview.journals" :key="i"><h3>{{date(j.date)}} · {{money(j.total_cents)}} · {{j.document_ids.length}} nota(s)</h3><p>Origens: {{preview.sources.filter(s=>j.document_ids.includes(s.document_id)).map(s=>s.document_number).join(', ')}}</p><p v-for="(l,index) in j.lines" :key="index">{{l.account_code}} · {{l.account_name}} · Débito {{money(l.debit_cents)}} · Crédito {{money(l.credit_cents)}}<span v-if="l.participant_id"> · Terceiro #{{l.participant_id}}</span><span v-if="l.cost_center_id"> · Centro #{{l.cost_center_id}}</span></p></article><button class="button outline" @click="clearPreview">Fechar prévia</button></section>
<section v-if="result" class="panel sales-result" aria-label="Resultado da contabilização"><h2>{{result.duplicate?'Solicitação já processada':'Resultado da contabilização'}}</h2><p role="status">{{result.created_count}} lançamento(s) {{result.duplicate?'registrado(s) na solicitação anterior; nenhuma nova gravação nesta repetição':'gerado(s)'}} · {{result.accounted_count}} nota(s) vinculada(s) · {{result.skipped.length}} ignorada(s).</p><p>{{result.notice}}</p><p v-for="j in result.journals" :key="j.id">Lançamento #{{j.number}} · {{date(j.date)}} · {{money(j.total_cents)}} <button class="button small" :disabled="!can('accounting.journals')||state.contextBusy" @click="showTrace('journal',j.id)">Notas do lançamento #{{j.number}}</button></p><ul v-if="result.skipped.length"><li v-for="s in result.skipped" :key="s.document_id">Nota #{{s.document_id}}: {{s.reason==='already_accounted'?'já contabilizada; vínculo preservado':'não apta; não houve contabilização'}}.</li></ul></section>
<BaseModal v-if="trace" title="Rastreabilidade contábil fiscal" wide @close="closeTrace"><p v-if="traceLoading" role="status">Consultando origens…</p><p v-if="traceError" class="message error" role="alert">{{traceError}}</p><template v-if="trace.data"><p v-if="trace.data.document">Nota {{trace.data.document.number}} · {{trace.data.document.partner_name}} · {{eligibilityLabel(trace.data.document)}}</p><section v-for="j in traceJournals" :key="j.id"><h3>Lançamento #{{j.number||j.id}}</h3><p v-if="j.deleted">Excluído fisicamente; referência histórica preservada.</p><template v-else><p>{{date(j.date)}} · {{money(j.total_cents)}} · {{j.history}}</p><table><thead><tr><th>Conta</th><th>Débito</th><th>Crédito</th></tr></thead><tbody><tr v-for="line in j.lines" :key="line.id"><td>{{line.access_code}} · {{line.account_name}}</td><td>{{money(line.debit_cents)}}</td><td>{{money(line.credit_cents)}}</td></tr></tbody></table></template></section><h3>Contribuições das notas</h3><p v-if="!traceSources.length">Sem contribuições registradas por esta integração. Os vínculos anteriores continuam preservados.</p><article v-for="(s,i) in traceSources" :key="`${s.document_id}-${s.journal_id}-${i}`" class="sales-source"><strong>Nota {{s.document_number}} · série {{s.document_series}} · {{money(s.total_cents)}}</strong><p>Escrituração {{date(s.posting_date)}} · emissão {{date(s.issue_date)}} · lançamento #{{s.journal_id}}</p><p v-if="s.model_snapshot">Modelo: {{s.model_snapshot.code}} · {{s.model_snapshot.name}}</p><p v-for="(c,k) in s.classification.item_classifications" :key="k">{{classLabel(c)}}</p><details><summary>Identificação da origem</summary><p>Documento #{{s.document_id}} · versão fiscal {{s.document_version}}</p><p>Chave: {{s.document_key||'Não informada'}}</p><p class="wrap-anywhere">Hash de origem: {{s.source_hash||'Não informado'}}</p></details><button v-if="trace.kind==='journal'" class="button small" @click="showTrace('document',s.document_id)">Consultar nota {{s.document_number}}</button></article><template v-if="trace.data.reversals?.length"><h3>Compensações por nota</h3><p v-for="r in trace.data.reversals" :key="r.journal_id">Nota #{{r.document_id}} · lançamento de compensação #{{r.journal_id}} · {{money(r.total_cents)}}</p></template><p class="message subtle">As contribuições são históricas. Estornos e novas escriturações não apagam a origem anterior.</p></template><template #footer><button class="button" @click="closeTrace">Fechar rastreabilidade</button></template></BaseModal>
</div></template>
<style scoped>
.sales-configuration,.sales-generation,.sales-result{padding:20px}.sales-configuration h2,.sales-generation h2,.sales-result h2{margin:0 0 12px}.sales-configuration .actions{align-self:end}.sales-selection{display:grid;gap:10px;padding:16px}.sales-generation{border-top:1px solid var(--border,#ddd)}.sales-generation .button{align-self:end}.sales-source{padding:14px 0;border-bottom:1px solid var(--border,#ddd)}.sales-source p{margin:8px 0}.sales-source details{margin:12px 0}.sales-source details p{overflow-wrap:anywhere}.sales-accounting-view .actions{flex-wrap:wrap}.sales-accounting-view select{max-width:100%}
</style>
