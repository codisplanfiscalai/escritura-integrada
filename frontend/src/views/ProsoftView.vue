<script setup>
import {ref,watch,computed,onActivated,onDeactivated,onUnmounted,nextTick} from 'vue';
import SectionTabs from '../components/SectionTabs.vue';
import {state,company,api,scope,can,allowedApi} from '../lib/workspace';
import {useSuggestedCompetence} from '../lib/context-preferences.js';
import {money,normalized} from '../lib/format';
import {createProsoftExport,prosoftDownload,prosoftManifest} from '../lib/prosoft-export.js';
const props=defineProps({area:{type:String,default:'accounting'}});
const competence=ref('');useSuggestedCompetence(state,competence);
const routine=computed(()=>props.area+'.prosoft'),fiscal=computed(()=>props.area==='fiscal');
const controller=createProsoftExport({
 context:()=>({cid:state.companyId,year:state.period.slice(0,4),module:state.module,period:competence.value,area:props.area}),
 request:(c,method,path,body)=>api(scope(path,c.cid),{method,body,context:{companyId:c.cid,year:c.year,module:c.module}}),
 references:async c=>{
  if(c.area==='fiscal')return {accounts:[],centers:[],parties:[]};
  const [accounts,centers,journals]=await Promise.all([allowedApi('accounting.accounts',scope('/accounts',c.cid)),allowedApi('accounting.cost_centers',scope('/cost-centers',c.cid)),allowedApi('accounting.journals',scope(`/journals?period=${c.period}`,c.cid))]);
  return {accounts,centers,used:[...new Set(journals.flatMap(j=>j.lines||[]).map(l=>l.account_id))],
   parties:[...new Map(journals.flatMap(j=>j.lines||[]).filter(l=>l.participant_id).map(l=>[l.participant_id,{id:l.participant_id,name:l.participant_name||String(l.participant_id)}])).values()]};
 }
});
const {s,dirty}=controller;
const section=ref('export'),tabs=ref(null);
const sections=[{id:'export',label:'Exportação e prévia'},{id:'settings',label:'Configuração e mapeamentos'},{id:'coverage',label:'Cobertura e limites'}];
function selectSection(value){section.value=value;nextTick(()=>tabs.value?.focusTab(value));}
function reloadSaved(){if(!dirty.value||window.confirm('Descartar as edições de mapeamentos desta empresa e recarregar os valores salvos?'))controller.load(true);}
async function preview(){await controller.run(false);if(s.preview)selectSection('export');}
const query=ref(''),page=ref(1),onlyUsed=ref(true),newCfop=ref('');
let active=true,timer=null,lastCompany='';
function schedule(){clearTimeout(timer);if(!active||state.contextBusy||state.module!==props.area||!can(routine.value))return;timer=setTimeout(()=>controller.load(),0);}
watch(()=>[state.companyId,state.period.slice(0,4),state.module,competence.value,state.contextBusy,state.refresh],()=>{
 controller.invalidate();const key=`${state.companyId}:${props.area}`;
 if(key!==lastCompany){lastCompany=key;controller.reset(company.value?.prosoft_code||'');query.value='';page.value=1;newCfop.value='';}
 schedule();
},{immediate:true,flush:'sync'});
onActivated(()=>{active=true;schedule();});
onDeactivated(()=>{active=false;clearTimeout(timer);controller.invalidate();});
onUnmounted(()=>{clearTimeout(timer);controller.dispose();});
const disabled=computed(()=>s.loading||s.busy||state.contextBusy||!state.companyId||!s.loaded);
const usedAccounts=computed(()=>new Set(s.records.used||[]));
const matchingAccounts=computed(()=>s.records.accounts.filter(a=>a.analytical&&(!onlyUsed.value||usedAccounts.value.has(a.id))&&normalized(`${a.access_code} ${a.name} ${a.classifier}`).includes(normalized(query.value))));
const mappingAccounts=computed(()=>matchingAccounts.value.slice((page.value-1)*100,page.value*100));
watch([query,onlyUsed],()=>page.value=1);
watch(mappingAccounts,records=>{if(s.loaded&&!s.loading)controller.ensureAccounts(records);},{flush:'sync'});
function toggleCta(a,checked){if(checked)s.config.accounts[a.id].create_account={destination_missing:true,classifier:a.classifier||'',name:a.name||'',cost_center_mode:'0',reconciliation:'0'};else delete s.config.accounts[a.id].create_account;}
function addCfop(){if(!/^[0-9]{4}$/.test(newCfop.value)){s.error='Informe quatro dígitos para o CFOP.';return;}s.config.cfop_accounts[newCfop.value]??={code:'',confirmed:false};newCfop.value='';}
const profile=computed({get:()=>fiscal.value?(s.config.record_types.length===2?'both':s.config.record_types[0]):(s.config.record_types.includes('CTA')?'journals_cta':'journals'),set:value=>{s.config.record_types=fiscal.value?(value==='both'?['incoming_notes','outgoing_notes']:[value]):(value==='journals_cta'?['LC1','LC2','CTA']:['LC1','LC2']);}});
const ctaEnabled=computed(()=>s.config.record_types.includes('CTA'));
const summary=computed(()=>s.preview?.manifest);
const hasShortReferences=computed(()=>(summary.value?.trace||[]).some(row=>row.document_reference));
const visibleTrace=computed(()=>(summary.value?.trace||[]).slice(0,100));
const visibleWarnings=computed(()=>(summary.value?.warnings||[]).slice(0,100));
const visibleSkipped=computed(()=>(summary.value?.skipped||[]).slice(0,100));
const skipLabel=code=>({layout_not_selected:'Tipo/layout não selecionado',not_booked:'Ainda não escriturado',cancellation_not_supported:'Cancelamento fora deste perfil',model_not_supported:'Modelo não coberto',species_mapping_required:'Mapeie e confira a espécie no destino'}[code]||code);
const warningLabel=code=>({FISCAL_TREATMENT_REQUIRED:'Tratamento do livro ainda não informado',DESTINATION_ACCOUNT_NOT_INFORMED:'Conta de destino não informada',KEY_NOT_INFORMED:'Chave eletrônica ausente',PARTNER_CNPJ_NOT_REPRESENTABLE:'CPF/CNPJ não representável neste perfil',PARTNER_STATE_NOT_INFORMED:'UF da contraparte ausente',BOOK_BASE_NOT_INFORMED:'Base de ICMS não informada',BOOK_ICMS_NOT_INFORMED:'ICMS do livro não informado',BOOK_OTHER_NOT_INFORMED:'Outras não informado',BOOK_IPI_NOT_INFORMED:'IPI do livro não informado',OTHER_IPI_TREATMENT_REQUIRED:'Confira Outras e tratamento do IPI',RATE_NOT_REPRESENTABLE:'Alíquota não cabe sem arredondamento',DECLARED_IPI_COMPONENT_NOT_EXPORTED:'Componente de IPI declarado não exportado',INVALID_FISCAL_TREATMENT:'Tratamento fiscal inválido ou fora da vigência',DECLARED_ICMS_MISSING:'Base ou ICMS declarado sem informação completa',CFOP_REQUIRED:'CFOP da linha não informado',INVALID_POSTING_GROUP_REVIEW:'Agrupamento revisado precisa de nova conferência',C190_TOTAL_MISMATCH:'Total analítico difere do documento',HEADER_COMPONENT_ALLOCATED:'Parcela do cabeçalho distribuída entre as linhas',TOTAL_ALLOCATION_REVIEW:'Composição do valor contábil precisa de conferência',NO_CONTRIBUTING_ITEMS:'Não há itens contribuintes para distribuir o valor',NEGATIVE_ALLOCATION_REVIEW:'Uma parcela distribuída ficou negativa'}[code]||(code.startsWith('DECLARED_')?'Informação declarada incompleta; confira a origem':'Confira os dados desta linha na origem'));
</script>

<template>
<div class="view prosoft-view">
 <header class="view-heading"><div><div class="eyebrow">{{fiscal?'INTEGRAÇÃO FISCAL':'INTEGRAÇÃO CONTÁBIL'}}</div><h1>Exportação Prosoft {{fiscal?'fiscal':'contábil'}}</h1><p>{{fiscal?'Notas de entrada e saída já escrituradas, modelos 55/65.':'Lançamentos LC1/LC2 e cadastro opcional CTA das contas movimentadas.'}}</p></div></header>
 <p class="message warning">Arquivo para conferir e importar no destino. Não homologado na instalação Prosoft. {{fiscal?'Perfil fiscal parcial; não gera EFD oficial nem transmite obrigações.':'TRC e SLD não são gerados.'}}</p>
 <p v-if="s.error" class="message error" role="alert">{{s.error}} <button class="button small" @click="selectSection('settings')">Revisar configuração e mapeamentos</button></p>
 <p v-if="s.message" class="message success" role="status">{{s.message}}</p>
 <p v-if="s.loading" role="status">Carregando mapeamentos da empresa…</p>
 <section class="panel report-controls" aria-label="Contexto da exportação Prosoft">
  <div class="prosoft-context"><strong>{{company?.name}}</strong><span>Destino {{s.config.company_code||'não informado'}} · plano {{s.config.plan_code||'não informado'}}</span><span>Versão {{s.version}}{{dirty?' · edição ainda não salva':' · mapeamentos salvos'}}</span></div>
  <fieldset :disabled="disabled" class="prosoft-fields">
   <div class="form-grid">
    <label>Tipo de exportação Prosoft<select aria-label="Tipo de exportação Prosoft" v-model="profile"><template v-if="fiscal"><option value="both">Notas de entrada e saída</option><option value="incoming_notes">Somente notas de entrada</option><option value="outgoing_notes">Somente notas de saída</option></template><template v-else><option value="journals">Lançamentos contábeis (LC1/LC2)</option><option value="journals_cta">Lançamentos e contas ausentes (LC1/LC2 + CTA)</option></template></select></label>
    <label>Competência da exportação<select v-model="competence" aria-label="Competência da exportação"><option value="">Selecione</option><option v-for="m in 12" :key="m" :value="`${state.period.slice(0,4)}-${String(m).padStart(2,'0')}`">{{String(m).padStart(2,'0')}}/{{state.period.slice(0,4)}}</option></select></label>
   </div>
   <p class="prosoft-scope">Serão considerados todos os {{fiscal?'documentos':'lançamentos'}} da competência de escrituração selecionada. A emissão pode ser de outro mês.</p>
  </fieldset>
 </section>
 <SectionTabs ref="tabs" v-model="section" :id="`prosoft-${area}`" label="Seções da exportação Prosoft" :tabs="sections"/>
 <section v-show="section==='settings'" :id="`prosoft-${area}-panel-settings`" role="tabpanel" :aria-labelledby="`prosoft-${area}-tab-settings`" tabindex="0" class="panel report-controls">
  <h2>Configuração reutilizável da empresa</h2>
  <div class="actions"><span>Versão salva {{s.version}}{{dirty?' · edição ainda não salva':''}}</span>
   <button v-if="can(routine,'edit')" class="button outline" :disabled="disabled||!dirty" @click="controller.save">Salvar mapeamentos nesta empresa</button>
   <button class="button small" :disabled="s.loading||s.busy||state.contextBusy" @click="reloadSaved">Recarregar salvos{{dirty?' e descartar edição':''}}</button>
  </div>
  <p class="report-note">Os mapeamentos pertencem a esta empresa e podem ser reutilizados em outras competências. Salvar configurações não altera documentos, contas ou lançamentos. A prévia usa os campos exibidos, inclusive edições ainda não salvas.</p>
  <p v-if="Object.keys(s.unavailable).length" class="message warning">{{Object.keys(s.unavailable).length}} mapeamentos de contas indisponíveis no plano atual foram preservados. Eles não são transferidos para contas com acesso igual.</p>
  <fieldset :disabled="disabled" class="prosoft-fields">
   <div class="form-grid">
    <label>Código da empresa na Prosoft<input v-model="s.config.company_code" maxlength="4" inputmode="numeric"/></label>
    <label>Plano escolhido no destino<input v-model="s.config.plan_code" maxlength="4" inputmode="numeric"/><small>050 é o padrão de conferência. Selecione o mesmo plano ao importar.</small></label>
    <label v-if="!fiscal">Lote<input v-model="s.config.batch" maxlength="5" inputmode="numeric"/></label>
   </div>
   <template v-if="fiscal">
    <h2>Espécies cadastradas no destino</h2><p>Informe os códigos da instalação Prosoft; eles não são deduzidos do modelo fiscal.</p>
    <div v-for="model in ['55','65']" :key="model" class="form-grid">
     <label>Espécie Prosoft do modelo {{model}}<input v-model="s.config.species[model].code" maxlength="5"/></label>
     <label class="inline-choice"><input v-model="s.config.species[model].confirmed" type="checkbox"/>Espécie do modelo {{model}} conferida no destino</label>
    </div>
    <h2>Contas fiscais por CFOP</h2><p>Conta ausente gera aviso e deixa o campo em branco. Não define crédito nem tratamento tributário.</p>
    <div class="actions"><label>Adicionar CFOP<input v-model="newCfop" maxlength="4" inputmode="numeric" @keydown.enter.prevent="addCfop"/></label><button class="button small" @click="addCfop">Adicionar mapeamento</button></div>
    <div v-for="(mapping,cfop) in s.config.cfop_accounts" :key="cfop" class="form-grid">
     <label>Acesso Prosoft do CFOP {{cfop}}<input v-model="mapping.code" maxlength="5" inputmode="numeric"/></label>
     <label class="inline-choice"><input v-model="mapping.confirmed" type="checkbox"/>Conta do CFOP {{cfop}} conferida</label>
     <button class="button small" @click="delete s.config.cfop_accounts[cfop]">Remover CFOP {{cfop}}</button>
    </div>

   </template>
   <template v-else>
    <h2>Mapeamento das contas</h2>
    <p v-if="!can('accounting.accounts')" class="message warning">A consulta do plano de contas exige permissão de leitura em Plano de contas. Os mapeamentos já salvos continuam disponíveis para exportação.</p>
    <div class="actions"><input v-model="query" aria-label="Pesquisar mapeamentos de contas" placeholder="Buscar acesso, classificador ou nome"/><label class="inline-choice"><input v-model="onlyUsed" type="checkbox"/>Somente contas movimentadas no mês</label><span>{{matchingAccounts.length}} contas</span><button class="button small" :disabled="page===1" @click="page--">Anterior</button><button class="button small" :disabled="page*100>=matchingAccounts.length" @click="page++">Próxima</button></div>
    <div class="table-scroll"><table><thead><tr><th>Conta da Escritura</th><th>Acesso Prosoft</th><th>Uso de terceiro</th><th>Terceiro fixo / tipo</th><th>Conferido</th></tr></thead><tbody>
     <template v-for="a in mappingAccounts" :key="a.id"><template v-if="s.config.accounts[a.id]">
      <tr><td>{{a.access_code}} · {{a.name}}<small>{{a.classifier}}</small></td>
       <td><input v-model="s.config.accounts[a.id].code" maxlength="5" :aria-label="`Acesso Prosoft da conta ${a.access_code}`"/></td>
       <td><select v-model="s.config.accounts[a.id].third_mode" :aria-label="`Uso de terceiro da conta ${a.access_code}`"><option value="none">Sem terceiro</option><option value="optional">Opcional</option><option value="required">Obrigatório</option></select></td>
       <td><input v-model="s.config.accounts[a.id].third" maxlength="14" :aria-label="`Terceiro fixo da conta ${a.access_code}`"/><select v-model="s.config.accounts[a.id].third_type" :aria-label="`Tipo de terceiro da conta ${a.access_code}`"><option value="normal">Normal</option><option value="free">Livre (sufixo L)</option></select></td>
       <td><input v-model="s.config.accounts[a.id].confirmed" type="checkbox" :aria-label="`Confirmar conta ${a.access_code}`"/></td>
      </tr>
      <tr v-if="ctaEnabled"><td colspan="5"><details><summary>Cadastro opcional CTA · conta {{a.access_code}}</summary>
       <label class="inline-choice"><input type="checkbox" :checked="Boolean(s.config.accounts[a.id].create_account)" @change="toggleCta(a,$event.target.checked)"/>Incluir CTA da conta {{a.access_code}}: confirme que ela está ausente no destino</label>
       <div v-if="s.config.accounts[a.id].create_account" class="form-grid">
        <label>Classificador CTA da conta {{a.access_code}}<input v-model="s.config.accounts[a.id].create_account.classifier"/></label>
        <label>Nome CTA da conta {{a.access_code}}<input v-model="s.config.accounts[a.id].create_account.name" maxlength="30"/></label>
        <label>Política de centro CTA da conta {{a.access_code}}<select :aria-label="`Política de centro CTA da conta ${a.access_code}`" v-model="s.config.accounts[a.id].create_account.cost_center_mode"><option value="0">Sem centro</option><option value="1">Opcional</option><option value="2">Rateio</option><option value="3">Obrigatório</option></select></label>
        <label>Conciliação CTA da conta {{a.access_code}}<select :aria-label="`Conciliação CTA da conta ${a.access_code}`" v-model="s.config.accounts[a.id].create_account.reconciliation"><option value="0">Não</option><option value="1">Sim</option></select></label>
        <label>Classificador especial CTA da conta {{a.access_code}}<input v-model="s.config.accounts[a.id].create_account.special_classifier"/></label>
        <label>Nome especial CTA da conta {{a.access_code}}<input v-model="s.config.accounts[a.id].create_account.special_name" maxlength="80"/></label>
       </div><p class="report-note">CTA é cadastral. Após importar e criar a conta no destino, desmarque esta opção e salve os mapeamentos. Somente contas movimentadas são incluídas no arquivo.</p>
      </details></td></tr>
     </template></template>
     <tr v-if="!mappingAccounts.length"><td colspan="5">Nenhuma conta para este filtro. Desmarque “Somente contas movimentadas no mês” para preparar outras contas.</td></tr>
    </tbody></table></div>
    <h2 v-if="s.records.centers.length">Centros de custo</h2>
    <div v-for="c in s.records.centers" :key="c.id" class="form-grid"><template v-if="s.config.centers[c.id]"><label>Código Prosoft do centro {{c.code}} · {{c.name}}<input v-model="s.config.centers[c.id].code" maxlength="5"/></label><label class="inline-choice"><input v-model="s.config.centers[c.id].confirmed" type="checkbox"/>Centro {{c.code}} conferido no destino</label></template></div>
    <h2 v-if="s.records.parties.length">Terceiros das partidas</h2>
    <div v-for="p in s.records.parties" :key="p.id" class="form-grid"><template v-if="s.config.participants[p.id]"><label>Código Prosoft do terceiro {{p.name}}<input v-model="s.config.participants[p.id].code" maxlength="14"/></label><label>Tipo do terceiro {{p.name}}<select :aria-label="`Tipo do terceiro ${p.name}`" v-model="s.config.participants[p.id].third_type"><option value="normal">Normal</option><option value="free">Livre (sufixo L)</option></select></label><label class="inline-choice"><input v-model="s.config.participants[p.id].confirmed" type="checkbox"/>Terceiro {{p.name}} conferido no destino</label></template></div>
   </template>
  </fieldset>
  <button class="button outline" @click="selectSection('export')">Voltar à exportação</button>
 </section>
 <section v-show="section==='coverage'" :id="`prosoft-${area}-panel-coverage`" role="tabpanel" :aria-labelledby="`prosoft-${area}-tab-coverage`" tabindex="0" class="panel report-controls">
  <h2>Cobertura dos layouts</h2>
   <details open><summary>Outros layouts recebidos e limites de cobertura</summary><p v-if="fiscal">Ainda não disponíveis: mapa resumo ECF, itens de notas/cupons, inventário, RCPE, produtos, faturas e seus itens, meios de pagamento, serviços municipais, valores avulsos, redução de base IBS/CBS e chaves complementares. As notas disponíveis têm cobertura parcial de campos. SPED é uma ferramenta interna separada e não substitui estes layouts de importação Prosoft.</p><p v-else>TRC (cadastro de terceiros) e SLD (saldos) ainda não são gerados. Referências a terceiros nos lançamentos continuam disponíveis. O intercâmbio de plano completo CTBPLANO permanece em Plano de contas.</p></details>
    <p v-if="fiscal" class="message subtle">Itens, faturas, cadastros, ST/FCP/DIFAL, PIS/COFINS, IBS/CBS e ajustes não são exportados. Canceladas identificadas pelo livro validado e escrituradas são incluídas com valor zero e indicador próprio. Campos sem origem conhecida ficam em branco; confira como o importador de destino trata esses brancos.</p>
  <p>Os avisos, documentos não exportados, origens e conversões de texto aparecem na prévia do lote. Confira-os antes de confirmar a exportação.</p>
  <button class="button outline" @click="selectSection('export')">Voltar à exportação</button>
 </section>
 <div v-show="section==='export'" :id="`prosoft-${area}-panel-export`" role="tabpanel" :aria-labelledby="`prosoft-${area}-tab-export`" tabindex="0">
 <section class="panel report-controls">
  <div class="actions"><button class="button primary" v-if="can(routine,'export')" :disabled="disabled" @click="preview">{{s.busy?'Processando…':'Gerar prévia'}}</button><button class="button outline" @click="selectSection('settings')">Revisar mapeamentos</button><button class="button small" @click="selectSection('coverage')">Consultar cobertura</button></div>
  <p v-if="!s.preview" class="report-note">Gere a prévia para conferir totais, avisos e registros antes do download. Os mapeamentos desta empresa são reutilizados; não é necessário configurá-los novamente.</p>
 </section>
 <section v-if="s.preview" class="panel report-controls" aria-label="Prévia da exportação Prosoft">
  <h2>Conferência do lote</h2><p>{{s.preview.filename}} · competência {{competence}} · plano {{s.config.plan_code}}</p>
  <template v-if="fiscal">
   <div class="summary-strip"><div v-for="(total,direction) in summary.totals" :key="direction"><span>{{direction==='incoming'?'Entradas':'Saídas'}}</span><strong>{{total.documents}} notas · {{total.records}} registros · {{money(total.total_cents)}} · {{total.cancelled_documents||0}} canceladas</strong></div></div>
   <p>Selecionados: {{summary.selection_count}} documentos · {{money(summary.selected_total_cents)}}. Não exportados: {{summary.skipped.length}}. Avisos: {{summary.warnings.length}} linhas.</p>
   <details v-if="summary.warnings.length"><summary>Avisos informativos ({{summary.warnings.length}})</summary><p v-for="(w,i) in visibleWarnings" :key="i">Documento #{{w.document_id}}, linha {{w.line}}: {{w.codes.map(warningLabel).join('; ')}}.</p><p v-if="summary.warnings.length>100">Mostrando os primeiros 100 avisos. O manifesto do download contém todos.</p></details>
   <details v-if="summary.skipped.length" open><summary>Documentos não exportados ({{summary.skipped.length}})</summary><p v-for="(row,i) in visibleSkipped" :key="i">Documento #{{row.document_id}} · {{money(row.total_cents)}} · {{skipLabel(row.reason)}}</p><p v-if="summary.skipped.length>100">Mostrando os primeiros 100. A prévia e o manifesto preservam todos os motivos.</p></details>
  </template>
  <template v-else><p>{{summary.journals}} lançamentos · {{summary.records}} registros · CTA {{summary.record_counts?.CTA||0}}</p><p>Débitos {{money(summary.debit_cents)}} · créditos {{money(summary.credit_cents)}}</p></template>
  <p v-if="!fiscal&&hasShortReferences" class="report-note">Referências longas recebem forma curta somente neste arquivo. As originais permanecem nos lançamentos e no mapa de conferência.</p>
  <details><summary>Origem dos registros ({{summary.trace.length}})</summary><div class="table-scroll"><table><thead><tr><th>Registro</th><th>Origem</th><th v-if="fiscal">Situação</th><th v-else>Referência no arquivo / original</th><th v-if="fiscal">Escrituração / emissão</th><th>Total</th></tr></thead><tbody><tr v-for="(row,i) in visibleTrace" :key="i"><td>{{fiscal?`${row.file} · ${row.record}`:row.order}}</td><td>{{fiscal?`Documento #${row.document_id} · ${row.number}`:`Lançamento #${row.journal_id} · ${row.journal_number}`}}</td><td v-if="fiscal">{{row.cancelled?'Cancelada no livro':'Regular'}}</td><td v-else>{{row.document_reference?.exported||'Mantida'}}<small v-if="row.document_reference">{{row.document_reference.original}}</small></td><td v-if="fiscal">{{row.posting_date}} / {{row.issue_date}}</td><td>{{money(row.total_cents)}}</td></tr></tbody></table></div><p v-if="summary.trace.length>100">Mostrando os primeiros 100 registros. A exportação inclui todos os registros cobertos.</p></details>
  <details><summary>Conversões de texto para ASCII ({{summary.text_changes.length}})</summary><p v-for="(change,i) in summary.text_changes" :key="i">{{change.field}}: {{change.original}} → {{change.exported}}</p></details>
  <label v-if="summary.text_changes.length" class="inline-choice"><input v-model="s.ascii" type="checkbox" :disabled="disabled"/>Revisei e aceito as conversões de texto exibidas.</label>
  <label class="inline-choice"><input v-model="s.reviewed" type="checkbox" :disabled="disabled"/>Conferi a empresa, o plano e os mapeamentos no destino.</label>
  <button v-if="can(routine,'export')" class="button primary" :disabled="disabled||!s.reviewed||(summary.text_changes.length&&!s.ascii)||(fiscal&&!summary.trace.length)" @click="controller.run(true)">Confirmar exportação</button>
  <p v-if="s.result"><a class="button outline" :href="prosoftDownload(s.result)" download>Baixar {{s.result.filename}}</a> <a v-if="!fiscal&&hasShortReferences" class="button outline" :href="prosoftManifest(s.result)" download>Baixar mapa de referências</a></p>
  <small class="wrap-anywhere">SHA-256: {{s.preview.sha256}}</small>
  <p class="report-note">Repetir o download não cria outro lote no aplicativo. Reimportar o mesmo TXT no Prosoft pode duplicar movimentos; confira o histórico no destino.</p>
 </section>
 </div>
</div>
</template>
<style scoped>
.prosoft-scope{font-size:.85rem;color:var(--muted)}.prosoft-context{margin-bottom:.75rem;display:flex;flex-wrap:wrap;gap:.5rem 1rem;align-items:center}.prosoft-context span{color:var(--muted);font-size:.85rem}.prosoft-view [role=tabpanel]:focus-visible{outline:2px solid var(--accent);outline-offset:3px}.prosoft-fields{border:0;margin:0;padding:0;min-width:0;display:flex;flex-direction:column;gap:1rem}.prosoft-view td input:not([type=checkbox]),.prosoft-view td select{min-width:7rem;max-width:100%}.prosoft-view small{display:block}.prosoft-view details{margin:.5rem 0}.prosoft-view .actions{flex-wrap:wrap}.prosoft-view .actions label{min-width:12rem}.prosoft-view h2{font-size:1rem}
.prosoft-view{min-width:0;max-width:100%;overflow-wrap:anywhere}.prosoft-view .view-heading>div,.prosoft-view .panel{min-width:0;max-width:100%}.prosoft-view .button{white-space:normal}.prosoft-view .actions>*{min-width:0;max-width:100%}.prosoft-view .table-scroll{min-width:0;max-width:100%}
@media(max-width:600px){.prosoft-view .form-grid{grid-template-columns:minmax(0,1fr)}.prosoft-view .view-heading h1{white-space:normal;overflow-wrap:anywhere}.prosoft-view .actions{justify-content:flex-start}.prosoft-view .actions .button{flex-basis:100%}}
</style>
