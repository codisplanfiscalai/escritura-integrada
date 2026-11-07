<script setup>
import DateInput from '../components/DateInput.vue';
import {ref,computed,watch,onUnmounted} from 'vue';
import Icon from '../components/Icon.vue';
import BaseModal from '../components/BaseModal.vue';
import EmptyState from '../components/EmptyState.vue';
import {state,company,api,scope,useResource,rows,notify,ask,changed} from '../lib/workspace';
import {can,allowedApi,writable} from '../lib/workspace';
import {money,date,dateTime,amount,periodDate,normalized,uid} from '../lib/format';

const props=defineProps({initialSection:{type:String,default:'catalogs'}});
const sections=[{id:'catalogs',name:'Cadastros fiscais',icon:'book'},{id:'rules',name:'Regras e vigência',icon:'settings'},{id:'templates',name:'Modelos',icon:'layers'},{id:'audit',name:'Auditoria',icon:'shield'}].filter(s=>props.initialSection==='rules'?['rules','templates'].includes(s.id):s.id===props.initialSection);
const catalogKinds=[{id:'cfop',name:'CFOP',singular:'CFOP',length:4},{id:'ncm',name:'NCM',singular:'NCM',length:8},{id:'revenue',name:'Códigos de receita',singular:'código de receita'},{id:'service',name:'Códigos de serviço',singular:'código de serviço'}];
const section=ref(props.initialSection),catalogKind=ref('cfop'),query=ref(''),catalogStatus=ref('active'),ruleStatus=ref('active'),direction=ref(''),auditEntity=ref(''),auditLimit=ref(100);
const modal=ref(''),form=ref({}),selected=ref(null),context=ref({}),busy=ref(false),error=ref(''),detailLoading=ref(false),versions=ref([]),versionSelected=ref(null),simulation=ref(null),selectionQuery=ref('');
const owner=`settings-${uid()}`;
let baseline='',requestSequence=0;
const {data,loading,error:loadError,reload}=useResource(async()=>{
  if(!state.companyId)return {catalogs:[],rules:[],templates:[],audit:[]};
  const cid=state.companyId;
  const [catalogs,rules,templates,audit]=await Promise.all([allowedApi('fiscal.masters',scope('/catalogs',cid)),allowedApi('fiscal.parameters',scope('/rules',cid)),allowedApi('fiscal.parameters','/templates'),allowedApi('system.audit',scope(`/audit?limit=${auditLimit.value}`,cid))]);
  return {catalogs:rows(catalogs),rules:rows(rules),templates:rows(templates),audit:rows(audit)};
},{catalogs:[],rules:[],templates:[],audit:[]});
watch(section,()=>{query.value='';});
watch(auditLimit,reload);
watch(()=>JSON.stringify(form.value),()=>{if(modal.value==='simulate')simulation.value=null;});

const kindInfo=computed(()=>catalogKinds.find(k=>k.id===catalogKind.value)||catalogKinds[0]);
const formKind=computed(()=>catalogKinds.find(k=>k.id===form.value.kind)||kindInfo.value);
const filteredCatalogs=computed(()=>data.value.catalogs.filter(x=>x.kind===catalogKind.value&&(!direction.value||x.direction===direction.value)&&(catalogStatus.value==='all'||Boolean(x.active)===(catalogStatus.value==='active'))&&normalized(`${x.code} ${x.description} ${x.source}`).includes(normalized(query.value))));
const filteredRules=computed(()=>data.value.rules.filter(x=>(ruleStatus.value==='all'||(ruleStatus.value==='inactive'?!x.active:ruleStatus.value==='active'?x.active:x.active&&x.status===ruleStatus.value))&&normalized(`${x.name} ${x.tax} ${x.cfop} ${x.ncm} ${x.responsible} ${x.source}`).includes(normalized(query.value))));
const filteredTemplates=computed(()=>data.value.templates.filter(x=>normalized(`${x.name} ${x.description} ${companyName(x.source_company_id)}`).includes(normalized(query.value))));
const filteredAudit=computed(()=>data.value.audit.filter(x=>(!auditEntity.value||x.entity===auditEntity.value)&&normalized(`${actionName(x.action)} ${entityName(x.entity)} ${x.entity_id} ${x.actor} ${JSON.stringify(x.details||{})}`).includes(normalized(query.value))));
const auditEntities=computed(()=>[...new Set(data.value.audit.map(x=>x.entity))].sort());
const activeRules=computed(()=>data.value.rules.filter(x=>x.active&&!x.superseded_by));
const selectableRules=computed(()=>activeRules.value.filter(x=>normalized(`${x.name} ${x.tax} ${x.cfop} ${x.ncm}`).includes(normalized(selectionQuery.value))));
const visibleSelected=computed(()=>selectableRules.value.length>0&&selectableRules.value.every(x=>form.value.rule_ids?.includes(x.id)));
const duplicateModelRules=computed(()=>modal.value==='apply'?((selected.value?.rules||[]).filter(x=>data.value.rules.some(r=>r.active&&normalized(r.name)===normalized(x.name)&&normalized(r.tax)===normalized(x.tax))).length):0);
const listCount=computed(()=>section.value==='catalogs'?filteredCatalogs.value.length:section.value==='rules'?filteredRules.value.length:section.value==='templates'?filteredTemplates.value.length:filteredAudit.value.length);
const editableModal=computed(()=>['catalog','rule','template','apply','simulate'].includes(modal.value));
const modalTitle=computed(()=>({catalog:form.value.id?`Editar ${formKind.value.singular}`:`Novo ${formKind.value.singular}`,rule:form.value.id?'Criar nova versão da regra':'Nova regra',template:'Criar modelo reutilizável',apply:'Aplicar modelo na empresa',model:'Detalhes do modelo',versions:'Versões da regra',simulate:'Simulação matemática',audit:'Detalhes da auditoria'}[modal.value]||''));
const saveLabel=computed(()=>({catalog:'Salvar cadastro',rule:form.value.id?'Salvar nova versão':'Salvar regra',template:'Criar modelo',apply:'Aplicar como rascunho'}[modal.value]||'Salvar'));
const auditChanges=computed(()=>{
  const details=selected.value?.details||{},before=details.before||{},after=details.after||{};
  return [...new Set([...Object.keys(before),...Object.keys(after)])].filter(k=>JSON.stringify(before[k])!==JSON.stringify(after[k])).map(k=>({key:k,before:before[k],after:after[k]}));
});
const auditDetails=computed(()=>Object.entries(selected.value?.details||{}).filter(([k])=>k!=='before'&&k!=='after'));

function companyName(id){const c=state.companies.find(x=>x.id===id);return c?`${c.code} · ${c.trade_name||c.name}`:`Empresa ${id}`;}
function directionName(value){return {incoming:'Entrada',outgoing:'Saída',both:'Entradas e saídas'}[value]||'—';}
function ruleState(rule){return !rule?.active?'Inativa':rule.status==='validated'?'Conferida pelo escritório':'Rascunho';}
function rateInput(value){if(value===null||value===undefined||value==='')return '';const s=String(value);return (/[eE]/.test(s)?Number(s).toFixed(6).replace(/\.?0+$/,''):s).replace('.',',');}
function rateLabel(value){return value===null||value===undefined||value===''?'Não informada':`${rateInput(value)}%`;}
function validity(value){return `${value.valid_from?date(value.valid_from):'Sem início informado'}${value.valid_to?` até ${date(value.valid_to)}`:' · sem fim definido'}`;}
function validityState(value){const day=periodDate(state.period);if(value.valid_from&&value.valid_from>day)return 'Início futuro';if(value.valid_to&&value.valid_to<day)return 'Vigência encerrada';return '';}
function entityName(value){return {company:'Empresa',account:'Conta contábil',cost_center:'Centro de custo',journal:'Lançamento',document:'Documento fiscal',title:'Título financeiro',settlement:'Baixa',bank_transaction:'Movimento bancário',reconciliation:'Conciliação',import:'Importação',catalog:'Cadastro fiscal',rule:'Regra',template:'Modelo',period:'Competência'}[value]||value;}
function actionName(value){return {create:'Cadastro',update:'Alteração',version:'Nova versão',deactivate:'Desativação',delete:'Desativação',simulate:'Simulação',apply:'Aplicação de modelo',review:'Conferência',book:'Escrituração',post:'Escrituração contábil',close:'Fechamento',reopen:'Reabertura',reverse:'Estorno',settle:'Baixa',reconcile:'Conciliação',unreconcile:'Desfazer conciliação',import:'Importação',preview:'Prévia de importação',confirm:'Confirmação'}[value]||value;}
function fieldName(value){return {name:'Nome',description:'Descrição',code:'Código',kind:'Tipo',direction:'Operação',valid_from:'Início da vigência',valid_to:'Fim da vigência',source:'Fonte',responsible:'Responsável',status:'Situação',active:'Ativo',version:'Versão',tax:'Tributo',rate:'Alíquota',cfop:'CFOP',ncm:'NCM',reason:'Motivo',module:'Módulo',previous_id:'Registro anterior',rule_ids:'Regras de origem',created_rule_ids:'Regras criadas',calculation_id:'Memória de cálculo',rule_version:'Versão da regra',source_hash:'Hash da origem',sha256:'SHA-256',filename:'Arquivo',period:'Competência',company_id:'Empresa',created_by:'Responsável pela inclusão',created_at:'Incluído em'}[value]||value.replaceAll('_',' ');}
function detailValue(value){if(value===null||value===undefined||value==='')return '—';if(typeof value==='boolean')return value?'Sim':'Não';if(Array.isArray(value)&&value.every(x=>typeof x!=='object'))return value.join(', ')||'—';return typeof value==='object'?JSON.stringify(value,null,2):String(value);}
function safeSourceLink(value){try{const u=new URL(String(value));return ['https:','http:'].includes(u.protocol)?u.href:null;}catch{return null;}}
function releaseEditor(){if(state.editor?.owner===owner)state.editor=null;}
function capture(name){context.value={id:state.companyId,code:company.value?.code,name:company.value?.trade_name||company.value?.name,period:state.period};state.editor={name,companyId:context.value.id,owner};}
function setDialog(kind,record,values={}){selected.value=record?JSON.parse(JSON.stringify(record)):null;form.value=JSON.parse(JSON.stringify(values));baseline=JSON.stringify(form.value);error.value='';selectionQuery.value='';simulation.value=null;versions.value=[];versionSelected.value=null;modal.value=kind;capture(modalTitle.value);}
function openCatalog(record=null){if(state.editor||busy.value)return;setDialog('catalog',record,record?{id:record.id,version:record.version,kind:record.kind,code:record.code,description:record.description,direction:record.direction,valid_from:record.valid_from||'',valid_to:record.valid_to||'',source:record.source||'',active:Boolean(record.active)}:{kind:catalogKind.value,code:'',description:'',direction:'both',valid_from:'',valid_to:'',source:'',active:true});}
function openRule(record=null){if(state.editor||busy.value)return;setDialog('rule',record,record?{id:record.id,version:record.version,name:record.name,tax:record.tax,regime:record.regime||'',state:record.state||'',municipality:record.municipality||'',rate:rateInput(record.rate),direction:record.direction,cfop:record.cfop||'',ncm:record.ncm||'',valid_from:record.valid_from,valid_to:record.valid_to||'',source:record.source||'',responsible:record.responsible||'',status:'draft',active:Boolean(record.active)}:{name:'',tax:'',regime:'',state:'',municipality:'',rate:'',direction:'both',cfop:'',ncm:'',valid_from:'',valid_to:'',source:'',responsible:'',status:'draft',active:true});}
function openTemplate(){if(state.editor||busy.value)return;setDialog('template',null,{name:'',description:'',rule_ids:[]});}
function openModel(record,apply=false){if(state.editor||busy.value)return;setDialog(apply?'apply':'model',record,apply?{reason:''}:{});}
function openAudit(record){if(state.editor||busy.value)return;setDialog('audit',record);}
async function openVersions(record){if(state.editor||busy.value)return;setDialog('versions',record);detailLoading.value=true;const sequence=++requestSequence,cid=context.value.id;try{const found=rows(await api(scope(`/rules/${record.id}/versions`,cid)));if(sequence!==requestSequence||modal.value!=='versions')return;versions.value=found;versionSelected.value=found.find(x=>x.id===record.id)||found[0]||null;}catch(e){if(sequence===requestSequence)error.value=e.message;}finally{if(sequence===requestSequence)detailLoading.value=false;}}
function openSimulation(record,fromVersions=false){if((state.editor&&!fromVersions)||busy.value)return;if(fromVersions){requestSequence++;releaseEditor();}setDialog('simulate',record,{date:periodDate(state.period),base:''});}
async function close(){if(busy.value)return;if(editableModal.value&&baseline!==JSON.stringify(form.value)&&!await ask({title:'Descartar alterações?',message:'Os dados desta janela ainda não foram salvos.',confirmLabel:'Descartar',danger:true}))return;requestSequence++;modal.value='';error.value='';detailLoading.value=false;releaseEditor();}
function verifyContext(){if(context.value.id!==state.companyId)throw new Error('A empresa ativa mudou. Feche esta janela e confira o contexto antes de continuar.');}
function normalizedRate(value){const raw=String(value??'').trim();if(!raw)return null;if(!/^\d{1,3}(?:[.,]\d{1,6})?$/.test(raw))throw new Error('Informe a alíquota entre 0 e 100, com até seis casas decimais e sem separador de milhar.');const result=raw.replace(',','.');if(Number(result)>100)throw new Error('A alíquota declarada deve estar entre 0 e 100.');return result;}
function toggleVisible(){const ids=selectableRules.value.map(x=>x.id),selectedIds=form.value.rule_ids||[];if(visibleSelected.value)form.value.rule_ids=selectedIds.filter(id=>!ids.includes(id));else{const next=[...new Set([...selectedIds,...ids])];if(next.length>200){error.value='Um modelo aceita até 200 regras. Refine o filtro e selecione o conjunto desejado.';return;}form.value.rule_ids=next;}error.value='';}
async function save(){if(busy.value)return;busy.value=true;error.value='';try{
  verifyContext();const kind=modal.value,payload={...form.value};let message='';
  if(kind==='catalog'){await api(scope(`/catalogs${payload.id?`/${payload.id}`:''}`,context.value.id),{method:payload.id?'PUT':'POST',body:payload});message='Cadastro fiscal salvo na empresa.';}
  else if(kind==='rule'){payload.rate=normalizedRate(payload.rate);if(payload.status==='validated'&&(!payload.source.trim()||!payload.responsible.trim()||payload.rate===null))throw new Error('Para registrar a conferência, informe fonte, responsável e alíquota declarada.');const result=await api(scope(`/rules${payload.id?`/${payload.id}`:''}`,context.value.id),{method:payload.id?'PUT':'POST',body:payload});message=`Regra salva na versão ${result.version}, ${result.status==='validated'?'conferida pelo escritório':'como rascunho'}.`;}
  else if(kind==='template'){if(!payload.rule_ids.length||payload.rule_ids.length>200)throw new Error('Selecione entre 1 e 200 regras ativas para compor o modelo.');await api('/templates',{method:'POST',body:{name:payload.name,description:payload.description,source_company_id:context.value.id,rule_ids:payload.rule_ids}});message='Modelo criado com as versões selecionadas.';}
  else if(kind==='apply'){const result=await api(scope(`/templates/${selected.value.id}/apply`,context.value.id),{method:'POST',body:{reason:payload.reason}});message=`${rows(result.rules).length} regra(s) copiadas como rascunho para ${context.value.name}.`;section.value='rules';ruleStatus.value='draft';}
  modal.value='';releaseEditor();changed();notify(message);
}catch(e){error.value=e.message;}finally{busy.value=false;}}
async function simulate(){if(busy.value)return;busy.value=true;error.value='';simulation.value=null;try{verifyContext();const result=await api(scope(`/rules/${selected.value.id}/simulate`,context.value.id),{method:'POST',body:{date:form.value.date,base:amount(form.value.base)}});simulation.value=result;baseline=JSON.stringify(form.value);changed();}catch(e){error.value=e.message;}finally{busy.value=false;}}
async function deactivate(kind,record){if(state.editor||busy.value)return;capture('Desativar parâmetro');const cid=context.value.id;try{const confirmed=await ask({title:kind==='rules'?'Desativar esta regra?':'Desativar este cadastro?',message:`${record.name||`${record.code} · ${record.description}`} ficará inativo em ${context.value.name}. ${kind==='rules'?'Uma nova versão preservará o histórico.':'O cadastro e seu histórico serão preservados.'}`,confirmLabel:'Desativar',danger:true});if(!confirmed)return;busy.value=true;await api(scope(`/${kind}/${record.id}?version=${record.version}`,cid),{method:'DELETE'});changed();notify(kind==='rules'?'Regra desativada em nova versão.':'Cadastro desativado.');}catch(e){notify(e.message,'error');}finally{busy.value=false;releaseEditor();}}
function newRecord(){if(section.value==='catalogs')openCatalog();else if(section.value==='rules')openRule();else if(section.value==='templates')openTemplate();}
onUnmounted(()=>{requestSequence++;releaseEditor();});
</script>

<template>
  <div class="view">
    <header class="view-heading">
      <div><div class="eyebrow">CONFIGURAÇÃO DO ESCRITÓRIO</div><h1>Parâmetros e rastreabilidade</h1><p>Cadastros por empresa, regras com vigência e modelos sujeitos à conferência.</p></div>
      <button v-if="section!=='audit'" class="button primary" :disabled="loading||busy||!!loadError" v-allow="[section==='catalogs'?'fiscal.masters':'fiscal.parameters','create']" @click="newRecord"><Icon name="plus"/>{{section==='catalogs'?`Novo ${kindInfo.singular}`:section==='rules'?'Nova regra':'Novo modelo'}}</button>
      <button v-else class="button outline" :disabled="loading||busy" @click="reload"><Icon :name="loading?'loading':'refresh'"/>Atualizar histórico</button>
    </header>
    <div class="segmented settings-tabs" role="tablist" aria-label="Seções de parametrização">
      <button v-for="item in sections" :key="item.id" role="tab" :aria-selected="section===item.id" :class="{selected:section===item.id}" @click="section=item.id"><Icon :name="item.icon" :size="16"/>{{item.name}}</button>
    </div>
    <div class="summary-strip">
      <div><Icon name="building"/><span>Empresa:</span><strong>{{company?.code}} · {{company?.trade_name||company?.name}}</strong></div>
      <div><span class="dot amber"></span><strong>{{loading||loadError?'—':data.rules.filter(r=>r.active&&r.status==='draft').length}}</strong><span>regras em rascunho</span></div>
      <div><span class="dot green"></span><strong>{{loading||loadError?'—':data.rules.filter(r=>r.active&&r.status==='validated').length}}</strong><span>conferidas pelo escritório</span></div>
    </div>
    <div v-if="loadError" class="message error" role="alert">{{loadError}} <button class="text-button" @click="reload">Tentar novamente</button></div>
    <section class="panel">
      <div class="table-toolbar">
        <div class="search-field"><Icon name="search"/><input v-model="query" :placeholder="section==='catalogs'?'Pesquisar código, descrição ou fonte':section==='rules'?'Pesquisar regra, tributo, código ou responsável':section==='templates'?'Pesquisar modelo ou empresa de origem':'Pesquisar ação, responsável ou registro'" aria-label="Pesquisar parâmetros"/></div>
        <template v-if="section==='catalogs'">
          <select v-model="catalogKind" aria-label="Tipo de cadastro fiscal"><option v-for="kind in catalogKinds" :key="kind.id" :value="kind.id">{{kind.name}}</option></select>
          <select v-model="direction" aria-label="Filtrar operação do cadastro"><option value="">Todas as operações</option><option value="incoming">Entradas</option><option value="outgoing">Saídas</option><option value="both">Ambas as operações</option></select>
          <select v-model="catalogStatus" aria-label="Situação do cadastro"><option value="active">Ativos</option><option value="inactive">Inativos</option><option value="all">Todos</option></select>
        </template>
        <select v-else-if="section==='rules'" v-model="ruleStatus" aria-label="Situação das regras"><option value="active">Regras ativas</option><option value="draft">Rascunhos</option><option value="validated">Conferidas pelo escritório</option><option value="inactive">Inativas</option><option value="all">Todas as atuais</option></select>
        <template v-else-if="section==='audit'">
          <select v-model="auditEntity" aria-label="Tipo de registro auditado"><option value="">Todos os registros</option><option v-for="entity in auditEntities" :key="entity" :value="entity">{{entityName(entity)}}</option></select>
          <select v-model.number="auditLimit" aria-label="Quantidade de eventos de auditoria"><option :value="100">Últimos 100 eventos</option><option :value="250">Últimos 250 eventos</option><option :value="1000">Últimos 1.000 eventos</option></select>
        </template>
        <span class="count">{{listCount}} registros</span>
      </div>
      <div v-if="loading" class="loading-line"><Icon name="loading"/>Carregando parâmetros e histórico...</div>
      <EmptyState v-else-if="loadError" title="Não foi possível carregar os parâmetros" text="Atualize a consulta para trabalhar com os registros da empresa ativa." icon="alert"/>
      <div v-else-if="listCount" class="table-scroll">
        <table v-if="section==='catalogs'">
          <thead><tr><th>Código</th><th>Descrição</th><th>Operação</th><th>Vigência</th><th>Situação</th><th class="right">Ações</th></tr></thead>
          <tbody><tr v-for="item in filteredCatalogs" :key="item.id"><td class="mono"><strong>{{item.code}}</strong></td><td class="truncate-cell">{{item.description}}<small class="cell-secondary">{{item.source||'Fonte ainda não informada'}}</small></td><td>{{directionName(item.direction)}}</td><td><span class="nowrap">{{item.valid_from?date(item.valid_from):'Não informada'}}</span><small class="cell-secondary">{{item.valid_to?`Até ${date(item.valid_to)}`:'Sem fim definido'}}</small></td><td><span class="badge" :class="item.active?'success':'neutral'">{{item.active?'Ativo':'Inativo'}}</span></td><td><div class="actions"><button class="icon-button" :aria-label="`Editar ${item.code}`" title="Editar cadastro" v-allow="['fiscal.masters','edit']" @click="openCatalog(item)"><Icon name="edit"/></button><button v-if="item.active" class="icon-button danger-text" :disabled="busy" :aria-label="`Desativar ${item.code}`" title="Desativar cadastro" v-allow="['fiscal.masters','delete']" @click="deactivate('catalogs',item)"><Icon name="trash"/></button></div></td></tr></tbody>
        </table>
        <table v-else-if="section==='rules'">
          <thead><tr><th>Regra / abrangência</th><th>Tributo</th><th class="right">Alíquota declarada</th><th>Vigência</th><th>Situação</th><th class="right">Ações</th></tr></thead>
          <tbody><tr v-for="rule in filteredRules" :key="rule.id"><td><strong>{{rule.name}}</strong><small class="cell-secondary">{{directionName(rule.direction)}} · {{rule.cfop?`CFOP ${rule.cfop}`:'Sem filtro de CFOP'}}<template v-if="rule.ncm"> · NCM {{rule.ncm}}</template></small></td><td>{{rule.tax}}<small class="cell-secondary">Versão {{rule.version}}</small></td><td class="right nowrap">{{rateLabel(rule.rate)}}</td><td class="nowrap">{{date(rule.valid_from)}}<small class="cell-secondary">{{rule.valid_to?`Até ${date(rule.valid_to)}`:'Sem fim definido'}}<template v-if="validityState(rule)"> · {{validityState(rule)}}</template></small></td><td><span class="badge" :class="!rule.active?'neutral':rule.status==='validated'?'success':'warning'">{{ruleState(rule)}}</span><small v-if="rule.responsible" class="cell-secondary">{{rule.responsible}}</small></td><td><div class="actions"><button class="icon-button" :aria-label="`Editar regra ${rule.name}`" title="Criar nova versão" v-allow="['fiscal.parameters','edit']" @click="openRule(rule)"><Icon name="edit"/></button><button class="icon-button" :aria-label="`Ver versões de ${rule.name}`" title="Histórico de versões" @click="openVersions(rule)"><Icon name="clock"/></button><button class="button small outline" :disabled="!rule.active||rule.rate===null||rule.rate===''" :title="rule.rate===null?'Informe a alíquota em uma nova versão para simular':'Abrir prévia matemática'" v-allow="['fiscal.parameters','create']" @click="openSimulation(rule)">Simular</button><button v-if="rule.active" class="icon-button danger-text" :disabled="busy" :aria-label="`Desativar regra ${rule.name}`" title="Desativar regra" v-allow="['fiscal.parameters','delete']" @click="deactivate('rules',rule)"><Icon name="trash" :size="16"/></button></div></td></tr></tbody>
        </table>
        <table v-else-if="section==='templates'">
          <thead><tr><th>Modelo</th><th>Empresa de origem</th><th>Regras</th><th>Criação</th><th class="right">Ações</th></tr></thead>
          <tbody><tr v-for="model in filteredTemplates" :key="model.id"><td><strong>{{model.name}}</strong><small class="cell-secondary">{{model.description||'Conjunto de versões selecionadas'}}</small></td><td>{{companyName(model.source_company_id)}}</td><td><span class="badge neutral">{{model.rules?.length||0}} regras</span></td><td class="nowrap">{{date(model.created_at)}}<small class="cell-secondary">{{model.created_by||'—'}}</small></td><td><div class="actions"><button class="icon-button" :aria-label="`Ver modelo ${model.name}`" title="Ver conteúdo do modelo" @click="openModel(model)"><Icon name="eye"/></button><button class="button small outline" v-allow="['fiscal.parameters','create']" @click="openModel(model,true)"><Icon name="copy" :size="14"/>Aplicar</button></div></td></tr></tbody>
        </table>
        <table v-else>
          <thead><tr><th>Data e hora</th><th>Ação</th><th>Registro</th><th>Responsável</th><th class="right">Detalhes</th></tr></thead>
          <tbody><tr v-for="event in filteredAudit" :key="event.id"><td class="nowrap">{{dateTime(event.created_at)}}</td><td>{{actionName(event.action)}}</td><td>{{entityName(event.entity)}} <span class="mono">#{{event.entity_id}}</span></td><td>{{event.actor}}</td><td class="right"><button class="icon-button" :aria-label="`Abrir evento ${event.id} da auditoria`" @click="openAudit(event)"><Icon name="eye"/></button></td></tr></tbody>
        </table>
      </div>
      <EmptyState v-else :icon="section==='audit'?'shield':section==='templates'?'layers':'settings'" :title="section==='catalogs'?'Nenhum cadastro neste filtro':section==='rules'?'Nenhuma regra neste filtro':section==='templates'?'Nenhum modelo encontrado':'Nenhum evento neste filtro'" :text="section==='catalogs'?'Cadastre os códigos utilizados pela empresa e registre a fonte de consulta.':section==='rules'?'Crie uma regra em rascunho, sem alíquota predefinida, e documente sua conferência.':section==='templates'?'Selecione versões de regras ativas para compor um modelo reutilizável.':'Os eventos desta empresa aparecem após as operações registradas.'"/>
      <footer class="table-footer"><span>{{section==='catalogs'?'O cadastro do código não certifica sua aplicabilidade fiscal.':section==='rules'?'Edições preservam versões. A conferência é atribuída ao responsável do escritório.':section==='templates'?'Modelos preservam versões de origem e são aplicados como rascunho.':`Consulta dos últimos ${auditLimit} eventos da empresa; os filtros atuam nesse recorte.`}}</span><span>{{listCount}} registros</span></footer>
    </section>

    <BaseModal v-if="modal" :title="modalTitle" :subtitle="`${context.code} · ${context.name}`" :wide="['rule','template','apply','model','versions','audit'].includes(modal)" @close="close">
      <div class="context-notice"><Icon name="building"/><span>{{modal==='apply'?'Empresa de destino':'Empresa do contexto'}}: <strong>{{context.name}}</strong></span><span v-if="modal==='rule'&&form.id" class="badge neutral">Versão atual {{form.version}}</span></div>
      <div v-if="error" class="message error" role="alert">{{error}}</div>
      <form v-if="modal==='catalog'" id="settings-form" @submit.prevent="save"><fieldset class="settings-fieldset" :disabled="busy">
        <div class="section-label">Identificação e uso</div>
        <div class="form-grid">
          <label>Tipo de cadastro<select v-model="form.kind" :disabled="!!form.id"><option v-for="kind in catalogKinds" :key="kind.id" :value="kind.id">{{kind.name}}</option></select></label>
          <label>Código *<input v-model="form.code" required :inputmode="formKind.length?'numeric':'text'" :pattern="formKind.length?`[0-9]{${formKind.length}}`:undefined" :maxlength="formKind.length||100" :placeholder="formKind.length?`${formKind.length} dígitos`:'Código utilizado pela empresa'" autofocus/></label>
          <label class="span-2">Descrição *<input v-model="form.description" required maxlength="1000" placeholder="Descrição correspondente ao código"/></label>
          <label>Operação<select v-model="form.direction"><option value="both">Entradas e saídas</option><option value="incoming">Somente entradas</option><option value="outgoing">Somente saídas</option></select></label>
          <label class="check-label"><input v-model="form.active" type="checkbox"/>Cadastro ativo</label>
        </div>
        <div class="section-label">Vigência e referência</div><div class="form-grid"><label>Início da vigência<DateInput v-model="form.valid_from"/></label><label>Fim da vigência<DateInput v-model="form.valid_to" :min="form.valid_from||undefined"/></label><label class="span-2">Fonte de consulta<textarea v-model="form.source" rows="2" maxlength="1000" placeholder="Documento, tabela, publicação ou URL consultada"/><small>Registre a referência que sustenta o cadastro. A aplicabilidade deve ser conferida para a operação.</small></label></div>
      </fieldset></form>

      <form v-else-if="modal==='rule'" id="settings-form" @submit.prevent="save"><fieldset class="settings-fieldset" :disabled="busy">
        <div v-if="form.id" class="message subtle"><Icon name="layers"/><span>Ao salvar, uma nova versão será criada. Revise os campos e registre novamente a situação de conferência.</span></div>
        <div class="section-label">Regra e abrangência</div><div class="form-grid three">
          <label class="span-3">Nome da regra *<input v-model="form.name" required maxlength="200" placeholder="Identifique o cenário que será conferido" autofocus/></label>
          <label>Tributo *<input v-model="form.tax" required maxlength="100" list="settings-tax-names" placeholder="Informe o tributo"/><datalist id="settings-tax-names"><option v-for="tax in ['ICMS','IPI','ISS','PIS','COFINS','IRPJ','CSLL','IRRF','INSS','IBS','CBS','IS']" :key="tax" :value="tax"/></datalist></label>
          <label>Regime de aplicação<select v-model="form.regime"><option value="">Todos os regimes (exige revisão)</option><option value="simples_nacional">Simples Nacional</option><option value="lucro_presumido">Lucro Presumido</option><option value="lucro_real">Lucro Real</option><option value="outros">Outro</option></select></label><label>UF de aplicação<input v-model="form.state" maxlength="2" placeholder="Todas"/></label><label>Município de aplicação (IBGE)<input v-model="form.municipality" maxlength="7" placeholder="Todos"/></label><label>Alíquota declarada (%)<input v-model="form.rate" inputmode="decimal" placeholder="Não informada" maxlength="11"/><small>Até seis casas decimais. Sem taxa predefinida.</small></label>
          <label>Operação<select v-model="form.direction"><option value="both">Entradas e saídas</option><option value="incoming">Entrada</option><option value="outgoing">Saída</option></select></label>
          <label>CFOP de referência<input v-model="form.cfop" inputmode="numeric" pattern="[0-9]{4}" maxlength="4" list="settings-cfop-codes" placeholder="Sem filtro"/><datalist id="settings-cfop-codes"><option v-for="c in data.catalogs.filter(c=>c.kind==='cfop'&&c.active)" :key="c.id" :value="c.code">{{c.description}}</option></datalist></label>
          <label>NCM de referência<input v-model="form.ncm" inputmode="numeric" pattern="[0-9]{8}" maxlength="8" list="settings-ncm-codes" placeholder="Sem filtro"/><datalist id="settings-ncm-codes"><option v-for="c in data.catalogs.filter(c=>c.kind==='ncm'&&c.active)" :key="c.id" :value="c.code">{{c.description}}</option></datalist></label>
          <label class="check-label"><input v-model="form.active" type="checkbox"/>Regra ativa</label>
        </div>
        <div class="section-label">Vigência e conferência</div><div class="form-grid three">
          <label>Início da vigência *<DateInput v-model="form.valid_from" required/></label><label>Fim da vigência<DateInput v-model="form.valid_to" :min="form.valid_from||undefined"/></label><label>Situação<select v-model="form.status"><option value="draft">Rascunho</option><option value="validated">Conferida pelo escritório</option></select></label>
          <label class="span-3">Fonte / fundamento {{form.status==='validated'?'*':''}}<textarea v-model="form.source" rows="2" maxlength="1000" :required="form.status==='validated'" placeholder="Registre a publicação, documento ou orientação efetivamente conferida"/></label>
          <label class="span-3">Responsável pela conferência {{form.status==='validated'?'*':''}}<input v-model="form.responsible" maxlength="200" :required="form.status==='validated'" placeholder="Identifique quem conferiu esta versão"/></label>
        </div>
        <div class="message subtle"><Icon name="info"/><span>Esta parametrização registra critérios e permite uma prévia matemática. O enquadramento, os créditos e a apuração legal dependem da conferência do escritório.</span></div>
      </fieldset></form>

      <form v-else-if="modal==='template'" id="settings-form" @submit.prevent="save"><fieldset class="settings-fieldset" :disabled="busy">
        <div class="form-grid"><label class="span-2">Nome do modelo *<input v-model="form.name" required maxlength="200" autofocus placeholder="Nome que permita reconhecer o conjunto"/></label><label class="span-2">Descrição<textarea v-model="form.description" rows="2" maxlength="1000" placeholder="Finalidade e cuidados ao reutilizar este modelo"/></label></div>
        <div class="section-label">Versões atuais e ativas <span>{{form.rule_ids.length}} de até 200 selecionadas</span></div>
        <div class="table-toolbar"><div class="search-field"><Icon name="search"/><input v-model="selectionQuery" placeholder="Filtrar regras para o modelo" aria-label="Pesquisar regras disponíveis"/></div><button class="button small" type="button" :disabled="!selectableRules.length" @click="toggleVisible">{{visibleSelected?'Desmarcar visíveis':'Selecionar visíveis'}}</button></div>
        <div v-if="selectableRules.length" class="settings-rule-picker"><label v-for="rule in selectableRules" :key="rule.id" class="settings-picker-row"><input v-model="form.rule_ids" type="checkbox" :value="rule.id" :disabled="form.rule_ids.length>=200&&!form.rule_ids.includes(rule.id)"/><div><strong>{{rule.name}}</strong><small class="cell-secondary">{{rule.tax}} · versão {{rule.version}} · {{validity(rule)}}</small></div><span class="badge" :class="rule.status==='validated'?'success':'warning'">{{rule.status==='validated'?'Conferida':'Rascunho'}}</span></label></div>
        <EmptyState v-else title="Nenhuma regra disponível" text="Cadastre uma regra ativa ou altere o filtro para selecionar o conteúdo do modelo." icon="layers"/>
        <p class="settings-inline-note">O modelo guarda as versões selecionadas. Na empresa de destino, as cópias começam em rascunho e exigem nova conferência.</p>
      </fieldset></form>

      <template v-else-if="modal==='apply'||modal==='model'">
        <div class="settlement-title"><strong>{{selected.name}}</strong><span>{{selected.description||'Conjunto reutilizável de versões de regras.'}}</span></div>
        <dl class="source-details"><dt>Empresa de origem</dt><dd>{{companyName(selected.source_company_id)}}</dd><dt>Conteúdo</dt><dd>{{selected.rules?.length||0}} regras preservadas no modelo</dd><template v-if="selected.created_at"><dt>Criado em</dt><dd>{{dateTime(selected.created_at)}} · {{selected.created_by||'—'}}</dd></template></dl>
        <div class="table-scroll"><table><thead><tr><th>Regra</th><th>Tributo</th><th>Alíquota declarada</th><th>Vigência original</th></tr></thead><tbody><tr v-for="rule in selected.rules||[]" :key="rule.id"><td>{{rule.name}}<small class="cell-secondary">Versão {{rule.version}} · {{directionName(rule.direction)}}</small></td><td>{{rule.tax}}</td><td>{{rateLabel(rule.rate)}}</td><td>{{validity(rule)}}</td></tr></tbody></table></div>
        <template v-if="modal==='apply'">
          <div class="message info"><Icon name="copy"/><span>Serão criadas {{selected.rules?.length||0}} regras independentes em <strong>{{context.name}}</strong>, todas em rascunho e sem responsável pela conferência. Revise a vigência e os critérios de cada cópia.</span></div>
          <div v-if="duplicateModelRules" class="message warning"><Icon name="alert"/><span>{{duplicateModelRules}} regra(s) do modelo têm nome e tributo iguais aos de regras ativas desta empresa. A aplicação criará novos registros; confira o conjunto antes de continuar.</span></div>
          <form id="settings-form" @submit.prevent="save"><label>Motivo da aplicação *<textarea v-model="form.reason" required rows="2" maxlength="1000" :disabled="busy" placeholder="Explique por que este conjunto será usado na empresa de destino" autofocus/></label></form>
        </template>
      </template>

      <template v-else-if="modal==='versions'">
        <div v-if="detailLoading" class="loading-line"><Icon name="loading"/>Carregando versões preservadas...</div>
        <div v-else-if="versions.length" class="settings-version-layout">
          <div class="settings-version-list" aria-label="Versões disponíveis"><button v-for="version in versions" :key="version.id" class="settings-version-button" :class="{selected:versionSelected?.id===version.id}" :aria-pressed="versionSelected?.id===version.id" @click="versionSelected=version"><strong>Versão {{version.version}} <span v-if="!version.superseded_by" class="badge info">Atual</span></strong><small>{{dateTime(version.created_at)}}</small><span>{{ruleState(version)}}</span></button></div>
          <div v-if="versionSelected"><h3>{{versionSelected.name}}</h3><dl class="source-details"><dt>Tributo / alíquota</dt><dd>{{versionSelected.tax}} · {{rateLabel(versionSelected.rate)}}</dd><dt>Operação</dt><dd>{{directionName(versionSelected.direction)}}</dd><dt>CFOP / NCM</dt><dd>{{versionSelected.cfop||'Sem filtro de CFOP'}} · {{versionSelected.ncm||'Sem filtro de NCM'}}</dd><dt>Vigência</dt><dd>{{validity(versionSelected)}}</dd><dt>Situação</dt><dd>{{ruleState(versionSelected)}}</dd><dt>Fonte</dt><dd class="settings-audit-value"><a v-if="safeSourceLink(versionSelected.source)" :href="safeSourceLink(versionSelected.source)" target="_blank" rel="noopener noreferrer">{{versionSelected.source}} <Icon name="external" :size="13"/></a><template v-else>{{versionSelected.source||'Não informada'}}</template></dd><dt>Responsável</dt><dd>{{versionSelected.responsible||'Ainda não conferida'}}</dd><dt>Registrada por</dt><dd>{{versionSelected.created_by||'—'}}</dd></dl><p class="settings-inline-note">Cada edição preserva a versão anterior. A versão selecionada permanece identificada na memória de cálculo.</p></div>
        </div>
        <EmptyState v-else-if="!error" title="Nenhuma versão disponível" text="Reabra o histórico após atualizar a listagem de regras." icon="clock"/>
      </template>

      <template v-else-if="modal==='simulate'">
        <div class="settlement-title"><strong>{{selected.name}} · versão {{selected.version}}</strong><span>{{selected.tax}} · alíquota declarada {{rateLabel(selected.rate)}} · {{validity(selected)}}</span></div>
        <div class="message info"><Icon name="info"/><span>Prévia de base × alíquota ÷ 100, com arredondamento ao centavo. Este resultado não constitui apuração nem homologação fiscal.</span></div>
        <form id="settings-simulation-form" @submit.prevent="simulate"><div class="form-grid"><label>Data de referência *<DateInput v-model="form.date" required :min="selected.valid_from" :max="selected.valid_to||undefined" :disabled="busy"/></label><label>Base declarada (R$) *<input v-model="form.base" required inputmode="decimal" placeholder="Informe a base para simular" :disabled="busy" autofocus/></label></div></form>
        <section v-if="simulation" class="settings-simulation" aria-live="polite"><div class="summary-strip"><div><span>Base informada</span><strong>{{money(simulation.base_cents)}}</strong></div><div><span>Alíquota</span><strong>{{rateLabel(simulation.rate)}}</strong></div><div><span>Resultado da simulação</span><strong>{{money(simulation.result_cents)}}</strong></div></div><div class="section-label">Memória de cálculo <span>#{{simulation.calculation_id}} · versão {{simulation.rule_version}}</span></div><ol class="settings-memory"><li v-for="(step,index) in simulation.memory||[]" :key="index">{{step}}</li></ol><dl class="source-details"><dt>Data de referência</dt><dd>{{date(simulation.date)}}</dd><dt>Fonte registrada</dt><dd class="settings-audit-value">{{simulation.source||'Não informada'}}</dd><dt>Responsável pela regra</dt><dd>{{simulation.responsible||'Regra ainda sem conferência atribuída'}}</dd></dl></section>
      </template>

      <template v-else-if="modal==='audit'">
        <div class="detail-grid"><div><small>Ação</small><strong>{{actionName(selected.action)}}</strong></div><div><small>Data e hora</small><strong>{{dateTime(selected.created_at)}}</strong></div><div><small>Responsável</small><strong>{{selected.actor}}</strong></div></div>
        <dl class="source-details"><dt>Evento</dt><dd class="mono">#{{selected.id}}</dd><dt>Registro</dt><dd>{{entityName(selected.entity)}} · #{{selected.entity_id}}</dd></dl>
        <div v-if="auditChanges.length" class="table-scroll"><table><thead><tr><th>Campo alterado</th><th>Antes</th><th>Depois</th></tr></thead><tbody><tr v-for="change in auditChanges" :key="change.key"><td>{{fieldName(change.key)}}</td><td class="settings-audit-value">{{detailValue(change.before)}}</td><td class="settings-audit-value">{{detailValue(change.after)}}</td></tr></tbody></table></div>
        <dl v-if="auditDetails.length" class="source-details"><template v-for="[key,value] in auditDetails" :key="key"><dt>{{fieldName(key)}}</dt><dd class="settings-audit-value">{{detailValue(value)}}</dd></template></dl>
        <p v-if="!auditChanges.length&&!auditDetails.length" class="settings-inline-note">Este evento registra a ação, a identidade do registro e o responsável, sem outros campos de detalhe.</p>
      </template>

      <template #footer>
        <span class="footer-hint"><Icon name="shield" :size="15"/>{{modal==='simulate'?'A simulação e a versão usada ficam na auditoria.':modal==='apply'?'As regras serão copiadas como rascunho.':'Empresa preservada enquanto esta janela estiver aberta.'}}</span>
        <div class="actions"><button class="button" :disabled="busy" @click="close">{{editableModal?'Cancelar':'Fechar'}}</button>
          <button v-if="['catalog','rule','template','apply'].includes(modal)" class="button primary" type="submit" form="settings-form" :disabled="busy||(modal==='template'&&!form.rule_ids.length)"><Icon :name="busy?'loading':modal==='apply'?'copy':'check'"/>{{saveLabel}}</button>
          <button v-if="modal==='simulate'" class="button primary" type="submit" form="settings-simulation-form" :disabled="busy"><Icon :name="busy?'loading':'settings'"/>{{simulation?'Simular novamente':'Simular valores'}}</button>
          <button v-if="modal==='versions'&&versionSelected" class="button outline" :disabled="!versionSelected.active||versionSelected.rate===null||versionSelected.rate===''" v-allow="['fiscal.parameters','create']" @click="openSimulation(versionSelected,true)">Simular esta versão</button>
        </div>
      </template>
    </BaseModal>
  </div>
</template>
