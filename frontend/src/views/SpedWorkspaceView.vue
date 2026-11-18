<script setup>
import {ref,computed,watch,onActivated,onDeactivated} from 'vue';
import {state,api,scope,can} from '../lib/workspace';
import SpedGeneratorView from './SpedGeneratorView.vue';
const props=defineProps({area:{type:String,default:'fiscal'}});
const accounting=computed(()=>props.area==='accounting');
const choices=computed(()=>accounting.value?[['ecd','ECD'],['ecf','ECF']]:[['efd_icms_ipi','EFD ICMS/IPI'],['efd_contribuicoes','PIS/Cofins']]);
const selected=ref(choices.value[0][0]),catalog=ref(null),error=ref(''),busy=ref(false),nativeImport=ref(''),imports=ref([]);let generation=0,active=true;
const entry=computed(()=>catalog.value?.obligations?.find(x=>x.id===selected.value));
const current=()=>JSON.stringify([state.companyId,state.period,state.session?.user?.id,state.module,props.area]);
function reset(){generation++;error.value='';imports.value=[];nativeImport.value='';busy.value=false;}
watch(current,()=>{reset();load();},{immediate:true});
watch(()=>props.area,()=>{selected.value=choices.value[0][0];});
async function load(){const g=generation,c=current();try{const result=await api('/sped/obligations');if(g===generation&&active&&c===current())catalog.value=result;
 if(!accounting.value&&state.companyId&&can('fiscal.imports','read')){const rows=await api(scope('/imports'));if(g===generation&&active&&c===current())imports.value=rows.filter(x=>x.period===state.period&&/\.(txt|sped|efd)$/i.test(x.filename));}
 }catch(e){if(g===generation)error.value=e.message;}}
function download(result){const binary=atob(result.content_base64),bytes=Uint8Array.from(binary,c=>c.charCodeAt(0));const url=URL.createObjectURL(new Blob([bytes],{type:'text/plain'}));const a=document.createElement('a');a.href=url;a.download=result.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function native(){if(busy.value||!nativeImport.value||!can('fiscal.documents','export')||!can('fiscal.imports','export'))return;const g=generation,c=current();busy.value=true;error.value='';
 try{const r=await api(scope('/sped-generator/consolidation-export'),{method:'POST',body:{period:state.period,import_id:Number(nativeImport.value),consolidate_nfce:false,segment_on_gap:true}});if(g===generation&&active&&c===current()&&can('fiscal.documents','export')&&can('fiscal.imports','export'))download(r);}catch(e){if(g===generation)error.value=e.message;}finally{if(g===generation)busy.value=false;}}
const evidenceUrl=computed(()=>selected.value==='ecd'?'/api'+scope('/sped-generator/accounting-snapshot?start='+state.period.slice(0,4)+'-01-01&end='+state.period.slice(0,4)+'-12-31'):selected.value==='efd_contribuicoes'?'/api'+scope('/sped-generator/contributions-snapshot?period='+state.period):'');
const exportAllowed=computed(()=>can(accounting.value?'accounting.journals':'fiscal.documents','export'));
onActivated(()=>{active=true;load();});onDeactivated(()=>{active=false;reset();});
</script>
<template><div class="view sped-workspace"><header class="view-heading"><div><h1>SPED</h1><p>{{accounting?'Escriturações contábeis':'Escriturações fiscais'}} da empresa e exercício ativos.</p></div></header>
<div class="tabs" role="tablist" aria-label="Escriturações SPED"><button v-for="[id,label] in choices" :key="id" role="tab" :aria-selected="selected===id" :class="{active:selected===id}" @click="selected=id">{{label}}</button></div>
<p v-if="error" role="alert" class="message error">{{error}}</p>
<template v-if="selected==='efd_icms_ipi'"><section class="panel"><h2>EFD ICMS/IPI importada</h2><p>Exportação integral do arquivo EFD 020 previamente importado, preservando os registros originais. NFS-e municipal não é inserida como NF-e ou CT-e neste arquivo.</p><label>Arquivo da competência<select v-model="nativeImport"><option value="">Selecione uma EFD importada</option><option v-for="item in imports" :key="item.id" :value="item.id">{{item.filename}}</option></select></label><button class="button" @click="native" :disabled="busy||!nativeImport||!exportAllowed||!can('fiscal.imports','export')">Exportar EFD original</button></section><SpedGeneratorView embedded/></template>
<section v-else class="panel"><h2>{{entry?.name||selected.toUpperCase()}}</h2><p>{{entry?.import_coverage}}</p><p class="message warning">Gerador integral ainda não disponível. Os arquivos preparatórios reúnem dados para revisão; não são arquivos ECD, ECF ou EFD-Contribuições para entrega.</p><a v-if="evidenceUrl&&exportAllowed" class="button" :href="evidenceUrl">Exportar dados preparatórios</a><p v-if="selected==='efd_contribuicoes'">Serviços possuem tratamento próprio no bloco A, conforme o regime e a operação. Não são incluídos no bloco C da EFD ICMS/IPI.</p><p v-if="selected==='ecf'">A ECF depende do regime, recuperação contábil, plano referencial e apuração IRPJ/CSLL. O sistema não substitui esses dados por zeros.</p><h3>Etapas necessárias para geração integral</h3><ul><li v-for="pending in entry?.pending||[]" :key="pending">{{pending}}</li></ul><p>Referência: {{entry?.reference?.manual_revision}} · {{entry?.reference?.period_scope}}</p></section>
</div></template>
<style scoped>.sped-workspace>.panel{padding:20px;margin:16px 0}.sped-workspace p{margin:12px 0;line-height:1.6}.tabs{display:flex;gap:8px;margin-bottom:16px}.tabs button{padding:10px;border:1px solid var(--line);background:var(--panel);border-radius:6px}.tabs .active{font-weight:700}.sped-workspace label{display:flex;gap:12px;margin:12px 0}.sped-workspace li{margin:8px 0}</style>
