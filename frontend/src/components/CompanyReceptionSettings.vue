<script setup>
import {ref,computed,watch,onUnmounted} from 'vue';
import {api,notify,changed} from '../lib/workspace';
import {services} from '../lib/reception.js';
const props=defineProps({companyId:{type:Number,required:true}});
const emit=defineEmits(['dirty','busy']);
const data=ref(null),preferences=ref(null),enabled=ref({}),allow=ref(false),file=ref(null),password=ref(''),input=ref(null),busy=ref(false),error=ref(''),baseline=ref('');
let generation=0;
const model=()=>JSON.stringify({preferences:preferences.value,enabled:enabled.value,allow:allow.value});
const dirty=computed(()=>!!data.value&&(model()!==baseline.value||!!file.value||!!password.value));
const editable=computed(()=>data.value?.can_edit===true);
watch(dirty,v=>emit('dirty',v));watch(busy,v=>emit('busy',v));
function clear(){file.value=null;password.value='';if(input.value)input.value.value='';}
function accept(value){data.value=value;preferences.value={...value.preferences};enabled.value={nfe_distribution:[],nfse_adn:[],...Object.fromEntries(Object.entries(value.credential.environments).map(([p,envs])=>[p,[...envs]]))};allow.value=value.credential.allow_adn_procuration;baseline.value=model();}
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
  if(g===generation){accept({...data.value,preferences:prefs,credential});changed();notify('Configuração salva. Nenhuma consulta fiscal foi executada.');}
 }catch(e){if(g===generation)error.value=e.message;}
 finally{form?.delete('certificate');form?.delete('password');if(g===generation){clear();busy.value=false;}}
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
<p class="message warning">Consulta externa NFS-e indisponível até confirmar as URLs oficiais no OpenAPI. CPF e A3 são documentados pelo serviço, mas ainda não estão implementados no adaptador atual.</p>
<p class="message info">Usuário e senha do portal não são autenticação comprovada para estas APIs. Não são coletados nem armazenados. A consulta documentada usa certificado de cliente.</p>
<p class="field-help">A1 e senha ficam cifrados; a chave permanece separada da base e de seus backups. Preserve essa chave com segurança para recuperação da instalação. A API nunca devolve o certificado, a senha ou a chave. Validação local não comprova cadeia ICP-Brasil, procuração ou homologação externa.</p>
<div class="actions"><button type="button" class="button" :disabled="busy" @click="load">Recarregar configuração</button><button type="submit" class="button primary" :disabled="busy||!editable||!dirty">Salvar recepção fiscal</button></div>
<p v-if="!editable" class="field-help">Alterar exige permissão de edição desta empresa.</p>
</form></section></template>
<style scoped>
h3,h4{margin:15px 0}p{line-height:1.6;margin:12px 0}.inline-choice{display:flex;flex-direction:row;align-items:center;gap:8px;margin:12px 0}.inline-choice input{width:auto}fieldset{border:1px solid var(--line);padding:16px;border-radius:8px;margin-top:20px}.actions{margin-top:18px}
</style>
