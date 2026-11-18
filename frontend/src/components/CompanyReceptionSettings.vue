<script setup>
import {ref,computed,watch,onUnmounted} from 'vue';
import {api,notify,changed} from '../lib/workspace';
import {services} from '../lib/reception.js';
const props=defineProps({companyId:{type:Number,required:true}});
const emit=defineEmits(['dirty','busy']);
const data=ref(null),preferences=ref(null),enabled=ref({}),allow=ref(false),file=ref(null),password=ref(''),input=ref(null),busy=ref(false),error=ref(''),baseline=ref('');
let generation=0;
const cursorValues=ref({}),cursorConfirmed=ref({});
const cursorKey=(provider,environment)=>provider+':'+environment;
const cursorDirty=(provider,environment)=>cursorValues.value[cursorKey(provider,environment)]!==data.value?.cursors?.[provider]?.[environment]?.cursor;
const cursorsDirty=computed(()=>Object.entries(data.value?.cursors||{}).some(([p,envs])=>Object.keys(envs).some(e=>cursorDirty(p,e))));
const model=()=>JSON.stringify({preferences:preferences.value,enabled:enabled.value,allow:allow.value});
const settingsDirty=computed(()=>!!data.value&&(model()!==baseline.value||!!file.value||!!password.value));
const dirty=computed(()=>settingsDirty.value||cursorsDirty.value);
const editable=computed(()=>data.value?.can_edit===true);
watch(dirty,v=>emit('dirty',v));watch(busy,v=>emit('busy',v));
function clear(){file.value=null;password.value='';if(input.value)input.value.value='';}
function accept(value,preserveCursors=false){data.value=value;if(!preserveCursors){cursorValues.value=Object.fromEntries(Object.entries(value.cursors||{}).flatMap(([p,envs])=>Object.entries(envs).map(([e,s])=>[cursorKey(p,e),s.cursor])));cursorConfirmed.value={};}preferences.value={...value.preferences};enabled.value={nfe_distribution:[],nfse_adn:[],...Object.fromEntries(Object.entries(value.credential.environments).map(([p,envs])=>[p,[...envs]]))};allow.value=value.credential.allow_adn_procuration;baseline.value=model();}
async function load(){const g=++generation,cid=props.companyId;clear();data.value=null;preferences.value=null;error.value='';busy.value=true;try{const r=await api('/companies/'+cid+'/reception-settings');if(g===generation)accept(r);}catch(e){if(g===generation)error.value=e.message;}finally{if(g===generation)busy.value=false;}}
watch(()=>props.companyId,load,{immediate:true});onUnmounted(()=>{generation++;clear();emit('busy',false);emit('dirty',false);});
function select(event){const value=event.target.files?.[0];error.value='';file.value=null;if(!value)return;if(!/\.(pfx|p12)$/i.test(value.name)||!value.size||value.size>5000000){error.value='Selecione PFX/P12 de até 5 MB.';event.target.value='';return;}file.value=value;}
async function save(){
 if(!data.value||busy.value||!editable.value)return;
 const g=generation,cid=props.companyId,options={version:data.value.credential.version,environments:Object.fromEntries(Object.entries(enabled.value).filter(([,values])=>values.length).map(([p,values])=>[p,[...values]])),allow_adn_procuration:allow.value};
 const certificateChanged=!!file.value||JSON.stringify({envs:options.environments,allow:allow.value})!==JSON.stringify({envs:data.value.credential.environments,allow:data.value.credential.allow_adn_procuration});
 if(!file.value&&!data.value.credential.configured&&(allow.value||Object.keys(options.environments).length)){error.value='Selecione o A1 para habilitar os ambientes.';return;}
 busy.value=true;error.value='';let form=null;
 try{
  let credential=data.value.credential;
  if(file.value){form=new FormData();form.append('certificate',file.value);form.append('password',password.value);form.append('options',JSON.stringify(options));clear();credential=await api('/companies/'+cid+'/reception-credential',{method:'POST',body:form});}
  else if(certificateChanged&&credential.configured)credential=await api('/companies/'+cid+'/reception-credential',{method:'PUT',body:options});
  if(g!==generation)return;data.value={...data.value,credential};
  const prefs=await api('/companies/'+cid+'/reception-settings',{method:'PUT',body:{...preferences.value}});
  if(g===generation){accept({...data.value,preferences:prefs,credential},true);changed();notify('Configuração salva. Nenhuma consulta fiscal foi executada.');}
 }catch(e){if(g===generation)error.value=e.message;}
 finally{form?.delete('certificate');form?.delete('password');if(g===generation){clear();busy.value=false;}}
}
async function saveCursor(provider,environment){
 const key=cursorKey(provider,environment),snapshot=data.value?.cursors?.[provider]?.[environment];
 if(!snapshot||busy.value||!editable.value||!cursorDirty(provider,environment)||!cursorConfirmed.value[key])return;
 const value=cursorValues.value[key],max=provider==='nfe_distribution'?15:19;
 if(!new RegExp('^[0-9]{1,'+max+'}$').test(value)||provider==='nfse_adn'&&BigInt(value)>9223372036854775807n){error.value='NSU inválido. Use somente dígitos dentro do limite do serviço.';return;}
 const g=generation,cid=props.companyId;busy.value=true;error.value='';
 try{
  const result=await api('/companies/'+cid+'/reception-settings/cursor',{method:'PUT',body:{provider,environment,cursor:value,expected_revision:snapshot.revision,confirmed:true}});
  if(g!==generation)return;
  data.value.cursors[provider][environment]=result;cursorValues.value[key]=result.cursor;cursorConfirmed.value[key]=false;
  changed();notify('NSU ajustado. Originais e intervalo de consulta preservados; o controle automático continua ativo.');
 }catch(e){if(g===generation)error.value=e.message;}
 finally{if(g===generation)busy.value=false;}
}
</script>
<template><section aria-label="Configuração de recepção fiscal" :aria-busy="busy">
<h3>DF-e e NFS-e Nacional · empresa deste cadastro</h3><p>As views usam a empresa selecionada no topo. Salvar parâmetros ou A1 não executa consulta fiscal.</p>
<p v-if="error" class="message error" role="alert">{{error}}</p><p v-if="busy" role="status">Atualizando configuração…</p>
<form v-if="data&&preferences" @submit.prevent="save">
<p class="message" :class="data.credential.configured?'success':'info'">{{data.credential.configured?'A1 protegido no cofre. Titular: '+data.credential.holder_cnpj:'Sem A1 cadastrado por esta tela. Perfis técnicos locais existentes são preservados.'}}</p>
<div class="form-grid"><label>Ambiente padrão DF-e<select v-model="preferences.nfe_environment" aria-label="Ambiente padrão DF-e" :disabled="busy||!editable"><option v-for="(label,key) in services.nfe_distribution.environments" :key="key" :value="key">{{label}}</option></select></label><label>Ambiente padrão NFS-e<select v-model="preferences.nfse_environment" aria-label="Ambiente padrão NFS-e" :disabled="busy||!editable"><option v-for="(label,key) in services.nfse_adn.environments" :key="key" :value="key">{{label}}</option></select></label></div>
<h4>Certificado A1 por empresa</h4><div class="form-grid"><label>{{data.credential.configured?'Substituir A1 (opcional)':'Arquivo A1'}}<input type="file" ref="input" accept=".pfx,.p12" :disabled="busy||!editable" @change="select"/></label><label>Senha de proteção do A1<input type="password" v-model="password" autocomplete="new-password" maxlength="4096" :disabled="busy||!editable||!file" placeholder="Não é a senha do portal"/></label></div>
<fieldset :disabled="busy||!editable"><legend>Ambientes habilitados para o A1</legend><div class="form-grid"><div v-for="(service,provider) in services" :key="provider"><strong>{{service.label}}</strong><label v-for="(label,key) in service.environments" :key="key" class="inline-choice"><input type="checkbox" v-model="enabled[provider]" :value="key"/>{{label}}</label></div></div><label class="inline-choice"><input type="checkbox" v-model="allow"/>Permitir tentativa ADN de outra raiz mediante procuração</label><small>Mesma raiz não exige esta opção; a inscrição completa da empresa mantém seu próprio cursor. Esta opção não concede procuração. A autorização é verificada pelo serviço oficial.</small></fieldset>
<p class="message warning">NF-e e NFS-e utilizam serviços, ambientes e sequências NSU independentes. A consulta usa o A1 e os parâmetros deste cadastro.</p>
<p class="message info">Usuário e senha do portal não são autenticação comprovada para estas APIs. Não são coletados nem armazenados. A consulta documentada usa certificado de cliente.</p>
<p class="field-help">A1 e senha ficam cifrados; a chave permanece separada da base e de seus backups. Preserve essa chave com segurança para recuperação da instalação. A API nunca devolve o certificado, a senha ou a chave. Validação local não comprova cadeia ICP-Brasil, procuração ou homologação externa.</p>
<div class="actions"><button type="button" class="button" :disabled="busy" @click="load">Recarregar configuração</button><button type="submit" class="button primary" :disabled="busy||!editable||!settingsDirty">Salvar recepção fiscal</button></div>
<p v-if="!editable" class="field-help">Alterar exige permissão de edição desta empresa.</p>
</form>
<section v-if="data?.cursors" aria-label="Ajuste manual de NSU">
<h4>Último NSU por serviço e ambiente</h4>
<p>Os campos refletem a mesma sequência atualizada automaticamente após cada lote salvo. Use o ajuste manual somente quando precisar corrigir essa sequência. Ele não desativa o controle automático.</p>
<p class="message warning">Avançar pode deixar documentos anteriores fora das próximas consultas. Voltar pode recebê-los novamente. Nenhum XML ou histórico será apagado, e a espera exigida pelo serviço será mantida.</p>
<fieldset v-for="(service,provider) in services" :key="provider" :disabled="busy||!editable"><legend>{{service.label}}</legend>
<div v-for="(label,environment) in service.environments" :key="environment" class="cursor-row">
<label>{{label}} · último NSU<input type="text" inputmode="numeric" :maxlength="provider==='nfe_distribution'?15:19" :aria-label="'NSU '+service.label+' '+label" v-model="cursorValues[cursorKey(provider,environment)]" @input="cursorConfirmed[cursorKey(provider,environment)]=false" :disabled="data.cursors[provider]?.[environment]?.busy"/></label>
<small>NSU salvo: {{data.cursors[provider]?.[environment]?.cursor}} <span v-if="data.cursors[provider]?.[environment]?.busy">· Consulta em andamento</span></small>
<label v-if="cursorDirty(provider,environment)" class="inline-choice"><input type="checkbox" v-model="cursorConfirmed[cursorKey(provider,environment)]"/>Confirmo o ajuste deste serviço e ambiente, sem apagar documentos.</label>
<button type="button" class="button" :disabled="!cursorDirty(provider,environment)||!cursorConfirmed[cursorKey(provider,environment)]||data.cursors[provider]?.[environment]?.busy" @click="saveCursor(provider,environment)">{{'Aplicar NSU '+service.label+' '+label}}</button>
</div></fieldset>
</section></section></template>
<style scoped>
h3,h4{margin:15px 0}p{line-height:1.6;margin:12px 0}.inline-choice{display:flex;flex-direction:row;align-items:center;gap:8px;margin:12px 0}.inline-choice input{width:auto}fieldset{border:1px solid var(--line);padding:16px;border-radius:8px;margin-top:20px}.actions{margin-top:18px}.cursor-row{padding:12px 0;border-bottom:1px solid var(--line)}.cursor-row>label{display:flex;flex-direction:column;gap:6px}.cursor-row>small{display:block;margin:8px 0}.cursor-row input[type="text"]{max-width:340px}
</style>
