<script setup>
import {ref,computed,watch,markRaw,onActivated,onDeactivated,onUnmounted} from 'vue';
import BaseModal from './BaseModal.vue';
import {api,scope,state,ask,captureContext,contextMatches} from '../lib/workspace';
const plans=ref([]),drafts=ref([]),canManage=ref(false),source=ref(''),newName=ref(''),draft=ref(null),form=ref(null),baseline=ref('');
const previousCompanies=ref([]);
const sourceCompanies=computed(()=>draft.value?.companies_on_source||plans.value.find(p=>p.id===Number(source.value))?.companies||[]);
const busy=ref(false),error=ref(''),message=ref(''),search=ref(''),page=ref(1),account=ref(null),previous=ref(null),accountBaseline=ref('');
const groups=[['asset','Ativo'],['liability','Passivo'],['compensation','Compensação'],['cost','Custos'],['expense','Despesas'],['revenue','Receitas']];
const reports=[['','Sem grupo'],['asset','Ativo'],['liability','Passivo'],['equity','Patrimônio líquido'],['revenue','Receitas'],['expense','Despesas']];
const defaults={mask:'#.#.##.###',generated_access:'0',groups:{asset:'1',liability:'2',compensation:'9',cost:'4',expense:'5',revenue:'3'},plan_type:'0',special_mask:''};
const copy=v=>JSON.parse(JSON.stringify(v));
const dirty=computed(()=>!!form.value&&JSON.stringify(form.value)!==baseline.value);
const locked=computed(()=>busy.value||state.contextBusy);
const owner=markRaw({type:'global-plan-manager'});
let sequence=0,active=true,alive=true,timer;
function release(){if(state.editor===owner)state.editor=null;}
// The shared workspace guard also protects browser close and company/context changes.
watch([dirty,account,busy],()=>{if(active&&(dirty.value||account.value||busy.value))state.editor=owner;else release();},{flush:'sync'});
function accept(d){page.value=d.page||1;draft.value=d;form.value={name:d.name,description:d.description||'',properties:{...copy(defaults),...copy(d.properties||{}),groups:{...defaults.groups,...d.properties?.groups}}};baseline.value=JSON.stringify(form.value);}
async function request(path='',options={}){
 const n=++sequence,ctx=captureContext();busy.value=true;error.value='';
 try{const result=await api(scope('/accounting-settings/plan-manager'+path,ctx.companyId),{...options,context:ctx});return n===sequence&&active&&alive&&contextMatches(ctx)?result:null;}
 catch(e){if(n===sequence&&active){error.value=e.status===409?`${e.message} Reabra o rascunho para obter a versão atual antes de tentar novamente.`:e.message;}return null;}
 finally{if(n===sequence)busy.value=false;}
}
async function load(){if(!active||!alive||!state.companyId||state.contextBusy||busy.value)return;const d=await request();if(d){plans.value=d.plans||[];drafts.value=d.drafts||[];canManage.value=d.can_manage!==false&&state.session?.user?.role==='admin';}}
function schedule(){clearTimeout(timer);timer=setTimeout(load,0);}
async function discard(){return !dirty.value||await ask({title:'Descartar alterações não salvas?',message:'As alterações das propriedades ainda não foram guardadas. As contas já guardadas no rascunho serão preservadas.',confirmLabel:'Descartar',danger:true});}
async function create(){if(locked.value||!canManage.value||!newName.value.trim()||!await discard())return;const d=await request('/drafts',{method:'POST',body:{name:newName.value.trim(),...(source.value?{source_global_id:Number(source.value)}:{properties:copy(defaults)})}});if(d){search.value='';page.value=1;accept(d);message.value='Edição aberta. O plano original e os vínculos das empresas permanecem preservados.';await load();}}
async function open(id){if(locked.value||!await discard())return;search.value='';page.value=1;const d=await request(`/drafts/${id}?page=1&per_page=100`);if(d)accept(d);}
async function fetchPage(next=1){if(locked.value||dirty.value||!draft.value)return;const d=await request(`/drafts/${draft.value.id}?search=${encodeURIComponent(search.value)}&page=${next}&per_page=100`);if(d){draft.value=d;page.value=d.page||next;}}
async function saveProperties(){if(!dirty.value&&JSON.stringify(form.value.properties)===JSON.stringify(draft.value.properties))return true;const d=await request(`/drafts/${draft.value.id}`,{method:'PUT',body:{version:draft.value.version,...copy(form.value)}});if(d)accept(d);return !!d;}
async function save(){if(locked.value||!canManage.value||!draft.value)return;if(!await saveProperties())return;const d=await request(`/drafts/${draft.value.id}/publish`,{method:'POST',body:{version:draft.value.version}});if(d){previousCompanies.value=d.companies_on_previous||sourceCompanies.value;message.value=d.duplicate?'Esta versão já está na biblioteca. Nenhum vínculo de empresa foi alterado.':'Plano salvo na biblioteca como nova versão. Disponível para adoção; nenhum vínculo de empresa foi alterado.';draft.value=null;form.value=null;baseline.value='';await load();}}
async function closeDraft(){if(locked.value||!await discard())return;draft.value=null;form.value=null;baseline.value='';}
function edit(row=null,parent=null){if(locked.value||dirty.value)return;previous.value=row?.access_code??null;account.value=row?Object.fromEntries(['access_code','classifier','name','nature','analytical','requires_cost_center','active','report_group','prosoft_code'].map(k=>[k,row[k]])):{access_code:'',classifier:parent?parent.classifier+'.':'',name:'',nature:parent?.nature||'debit',analytical:true,requires_cost_center:false,active:true,report_group:parent?.report_group||'',prosoft_code:''};for(const k of ['analytical','requires_cost_center','active'])account.value[k]=!!account.value[k];accountBaseline.value=JSON.stringify(account.value);}
async function closeAccount(){if(locked.value)return;if(JSON.stringify(account.value)!==accountBaseline.value&&!await ask({title:'Descartar edição da conta?',message:'Os campos alterados nesta janela ainda não foram guardados.',confirmLabel:'Descartar',danger:true}))return;account.value=null;}
async function saveAccount(){if(locked.value||!canManage.value)return;const d=await request(`/drafts/${draft.value.id}/accounts`,{method:'POST',body:{version:draft.value.version,account:copy(account.value),...(previous.value!==null?{previous_access_code:previous.value}:{})}});if(d){account.value=null;accept(d);await fetchPage(page.value);}}
async function remove(row){if(locked.value||dirty.value||!canManage.value)return;if(!await ask({title:'Remover conta do rascunho?',message:`${row.access_code} · ${row.name}. A versão global original e as contas das empresas não serão alteradas.`,confirmLabel:'Remover do rascunho',danger:true}))return;const d=await request(`/drafts/${draft.value.id}/accounts?access_code=${encodeURIComponent(row.access_code)}&version=${draft.value.version}`,{method:'DELETE'});if(d){accept(d);await fetchPage(1);}}
watch(()=>[state.companyId,state.module,state.period,state.contextBusy],()=>{sequence++;busy.value=false;draft.value=null;form.value=null;account.value=null;plans.value=[];drafts.value=[];error.value='';message.value='';previousCompanies.value=[];schedule();},{immediate:true});
onActivated(()=>{active=true;schedule();});
function suspend(){active=false;sequence++;clearTimeout(timer);busy.value=false;release();}
onDeactivated(suspend);onUnmounted(()=>{alive=false;suspend();});
</script>
<template>
<section class="global-editor panel" aria-label="Gerenciador de planos globais">
 <p>Edite uma cópia ou crie um plano vazio. Salvar na biblioteca cria uma versão independente, sem alterar os vínculos atuais das empresas. O plano 050 e suas referências permanecem preservados.</p>
 <p v-if="error" class="message error" role="alert">{{error}}</p><p v-if="message" class="message success" role="status">{{message}}</p>
 <p v-if="busy" role="status">Carregando…</p>
 <p v-if="!canManage&&!busy" class="context-notice">A edição de planos globais é exclusiva de administradores. Use o plano da empresa para consultar suas contas.</p>
 <section v-if="previousCompanies.length" class="context-notice" aria-label="Empresas preservadas na versão anterior"><strong>Empresas que continuam na versão anterior</strong><ul><li v-for="c in previousCompanies" :key="c.id">{{c.code}} · {{c.name}} · {{c.mode==='shared'?'Plano compartilhado':'Plano próprio'}}<span v-if="c.journal_lines!=null"> · {{c.journal_lines}} itens de lançamento</span></li></ul><p>Para adotar a nova versão, abra os parâmetros contábeis de cada empresa e confira a prévia de impacto. Nenhuma empresa foi atualizada ao salvar.</p></section>
 <template v-if="canManage">
 <form class="manager-create" @submit.prevent="create"><fieldset :disabled="locked">
 <label>Plano de origem<select v-model="source" @change="newName=plans.find(p=>p.id===Number(source))?.name||''"><option value="">Novo plano vazio</option><option v-for="p in plans" :key="p.id" :value="p.id">{{p.name}} · versão {{p.id}} · {{p.record_count}} contas</option></select></label>
 <label>Nome do plano<input v-model="newName" required maxlength="200" placeholder="Nome para a biblioteca"/></label>
 <button class="button primary" type="submit">{{source?'Editar cópia':'Criar plano'}}</button>
 </fieldset></form>
 <label v-if="drafts.length">Continuar edição salva<select :value="draft?.id||''" :disabled="locked" @change="$event.target.value&&open($event.target.value)"><option value="">Selecione um rascunho</option><option v-for="d in drafts" :key="d.id" :value="d.id">{{d.name}} · revisão {{d.version}} · {{d.record_count}} contas</option></select></label>
 </template>
 <details v-if="sourceCompanies.length"><summary>{{sourceCompanies.length}} empresa(s) na versão de origem, sem atualização automática</summary><ul><li v-for="c in sourceCompanies" :key="c.id">{{c.code}} · {{c.name}} · {{c.mode==='shared'?'Plano compartilhado':'Plano próprio'}}<span v-if="c.journal_lines!=null"> · {{c.journal_lines}} itens de lançamento</span></li></ul><p>Após salvar, adote a nova versão nos parâmetros da respectiva empresa, com a prévia de impacto.</p></details>
 <section v-if="draft&&form" class="draft-area">
 <div class="manager-actions"><h3>{{draft.name}}</h3><span class="badge">Rascunho · revisão {{draft.version}}</span><button class="button" :disabled="locked" @click="closeDraft">Fechar edição</button><button class="button primary" :disabled="locked" @click="save">Salvar plano na biblioteca</button></div>
 <form @submit.prevent="saveProperties"><fieldset :disabled="locked"><div class="form-grid">
 <label>Nome<input v-model="form.name" required maxlength="200"/></label><label>Descrição<input v-model="form.description" maxlength="1000"/></label>
 <label>Máscara de classificação<input v-model="form.properties.mask" required maxlength="200" placeholder="#.#.##.###"/></label>
 <label v-for="[key,label] in groups" :key="key">Grupo {{label}}<select v-model="form.properties.groups[key]"><option v-for="n in 9" :key="n" :value="String(n)">{{n}}</option></select></label>
 </div><button v-if="dirty" class="button" type="submit">Guardar propriedades no rascunho</button></fieldset></form>
 <p v-if="dirty" class="context-notice">Guarde as propriedades antes de editar contas, ou salve o plano diretamente na biblioteca.</p>
 <form class="manager-actions" @submit.prevent="fetchPage(1)"><label>Buscar conta<input v-model="search" placeholder="Acesso, classificação ou nome" :disabled="locked"/></label><button class="button" :disabled="locked||dirty">Buscar</button><button type="button" class="button primary" :disabled="locked||dirty" @click="edit()">Nova conta</button></form>
 <p v-if="draft.missing_parent_classifiers?.length" class="message info">Classificadores sem conta-pai explícita neste rascunho: {{draft.missing_parent_classifiers.join(', ')}}. Nenhuma conta será inventada automaticamente.</p>
 <div class="table-wrap"><table><thead><tr><th>Acesso</th><th>Classificação</th><th>Conta</th><th>Tipo</th><th>Natureza</th><th>Situação</th><th>Ações</th></tr></thead><tbody><tr v-for="row in draft.accounts||[]" :key="row.access_code"><td>{{row.access_code}}</td><td>{{row.classifier}}</td><td>{{row.name}}</td><td>{{row.analytical?'Analítica':'Sintética'}}</td><td>{{row.nature==='debit'?'Devedora':'Credora'}}</td><td>{{row.active?'Ativa':'Inativa'}}</td><td><div class="manager-actions"><button class="button" :disabled="locked||dirty" @click="edit(row)">Editar</button><button v-if="!row.analytical" class="button" :disabled="locked||dirty" @click="edit(null,row)">Subconta</button><button class="button" :disabled="locked||dirty" @click="remove(row)">Remover</button></div></td></tr><tr v-if="!draft.accounts?.length"><td colspan="7">Nenhuma conta encontrada. Adicione contas ou ajuste a busca.</td></tr></tbody></table></div>
 <div class="manager-actions"><span>{{draft.total??draft.record_count??0}} contas · página {{page}}</span><button class="button" :disabled="locked||dirty||page<=1" @click="fetchPage(page-1)">Anterior</button><button class="button" :disabled="locked||dirty||page*(draft.per_page||100)>=(draft.total??draft.record_count??0)" @click="fetchPage(page+1)">Próxima</button></div>
 </section>
 <BaseModal v-if="account" :title="previous!==null?'Editar conta':'Nova conta ou subconta'" @close="closeAccount">
 <p v-if="error" class="message error" role="alert">{{error}}</p>
 <form id="global-account-form" @submit.prevent="saveAccount"><fieldset :disabled="locked"><div class="form-grid"><label>Acesso<input v-model="account.access_code" required maxlength="200"/></label><label>Classificação<input v-model="account.classifier" required pattern="[0-9]+(\.[0-9]+)*" maxlength="200" placeholder="1.1.01.001"/></label><label>Nome<input v-model="account.name" required maxlength="200"/></label><label>Natureza<select v-model="account.nature"><option value="debit">Devedora</option><option value="credit">Credora</option></select></label><label>Tipo<select v-model="account.analytical"><option :value="false">Sintética (agrupamento)</option><option :value="true">Analítica (lançamentos)</option></select></label><label>Grupo do demonstrativo<select v-model="account.report_group"><option v-for="[value,label] in reports" :key="value" :value="value">{{label}}</option></select></label><label>Acesso Prosoft<input v-model="account.prosoft_code" maxlength="5" pattern="[0-9]{1,5}"/></label><label><input type="checkbox" v-model="account.requires_cost_center"/> Exige centro de custo</label><label><input type="checkbox" v-model="account.active"/> Conta ativa</label></div></fieldset></form>
 <template #footer><button class="button" :disabled="locked" @click="closeAccount">Cancelar</button><button class="button primary" form="global-account-form" :disabled="locked">Guardar conta no rascunho</button></template>
 </BaseModal>
</section>
</template>
<style scoped>
.global-editor{display:grid;gap:18px}.global-editor fieldset{border:0;padding:0;margin:0;min-width:0}.manager-create fieldset,.manager-actions{display:flex;gap:12px;align-items:end;flex-wrap:wrap}.manager-create label{flex:1;min-width:220px}.manager-actions h3{margin-right:auto}.draft-area{display:grid;gap:18px;border-top:1px solid var(--border,#ddd);padding-top:20px}.table-wrap{overflow:auto}.manager-actions .button{white-space:nowrap}.form-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px}label{display:grid;gap:6px}td{vertical-align:top}
</style>
