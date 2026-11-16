<script setup>
import {reactive,computed,watch,onActivated,onDeactivated,onUnmounted} from 'vue';
import {api,ask} from '../lib/workspace';
import {createBackups} from '../lib/backups.js';
const m=reactive({config:{provider:'dropbox',credential_ref:'ESCRITURA_BACKUP_PRIMARY',encryption_key_id:'primary',folder:'/backups',bucket:'',prefix:'escritura',region:'us-east-1',endpoint:'',interval_hours:24,enabled:false},busy:false,error:'',loaded:false,status:null,intent:null,job:null,restored:''});
const c=createBackups(m,api);
watch(()=>m.config.provider,provider=>{if(provider!=='minio')m.config.endpoint='';});
const jobs=computed(()=>m.status?.jobs||[]);
const active=computed(()=>jobs.value.some(j=>['queued','snapshot','uploading'].includes(j.state))||['queued','snapshot','uploading'].includes(m.job?.state)&&!jobs.value.some(j=>j.id===m.job.id));
const labels={queued:'Na fila',snapshot:'Preparando e verificando',uploading:'Enviando',completed:'Enviado e verificado',failed:'Falha local',uncertain:'Envio incerto · conferir destino',interrupted:'Interrompido · conferir destino',cancelled:'Cancelado'};
let timer;
async function run(){if(m.busy||active.value)return;if(!await ask({title:'Enviar backup?',message:'O pacote contém os dados de todas as empresas. Confirme o destino configurado antes do envio.',confirmLabel:'Executar backup'}))return;await c.run();await c.status();}
async function restore(id){if(!await ask({title:'Extrair cópia isolada?',message:'Validar e extrair em backup-control/restores. Nenhum dado operacional será substituído e a cópia não será ativada.',confirmLabel:'Validar e extrair'}))return;await c.restore(id);}
function stop(){clearInterval(timer);c.pause();}
onActivated(()=>{c.resume();c.status();timer=setInterval(()=>c.status(),5000);});onDeactivated(stop);onUnmounted(stop);
const date=value=>value?new Date(value*1000).toLocaleString():'—';
</script>
<template>
<div class="view">
 <header class="view-heading"><div><div class="eyebrow">ADMINISTRAÇÃO DO AMBIENTE</div><h1>Backups remotos</h1><p>Cópia consistente do SQLite e dos originais armazenados no banco, para todas as empresas.</p></div><button class="button outline" :disabled="m.busy" @click="c.status">Atualizar histórico</button></header>
 <p v-if="m.status?.worker_error" class="message error" role="alert">{{m.status.worker_error}}</p>
 <p v-if="m.error" class="message error" role="alert">{{m.error}} Confira o histórico antes de repetir.</p>
 <p class="message warning">Novos pacotes usam AES-256-GCM e contêm dados fiscais e hashes de senha; proteja o acesso ao destino. Sessões, credenciais externas e certificados em pastas não são incluídos. Limite: {{m.status?.max_archive_mib||512}} MiB compactados / 2 GiB de banco. Não há exclusão automática nem ativação da cópia restaurada.</p>
 <form class="panel panel-body" @submit.prevent="c.save">
  <h2>Destino e agendamento</h2>
  <fieldset :disabled="m.busy||active"><div class="backup-grid">
   <label>Provedor<select v-model="m.config.provider" aria-label="Provedor"><option value="dropbox">Dropbox</option><option value="drive">Google Drive</option><option value="s3">Amazon S3</option><option value="minio">MinIO</option></select></label>
   <label>Referência da credencial<input v-model="m.config.credential_ref" required pattern="ESCRITURA_BACKUP_[A-Z0-9_]+" autocomplete="off"></label>
   <label>Identificador da chave de criptografia<input v-model="m.config.encryption_key_id" required pattern="[A-Za-z0-9_-]{1,64}" autocomplete="off"></label>
   <label v-if="['dropbox','drive'].includes(m.config.provider)">{{m.config.provider==='drive'?'ID da pasta Drive':'Caminho da pasta Dropbox'}}<input v-model="m.config.folder" required></label>
   <template v-else><label>Bucket<input v-model="m.config.bucket" required></label><label>Região<input v-model="m.config.region" required></label><label>Prefixo<input v-model="m.config.prefix"></label><label v-if="m.config.provider==='minio'">Endpoint HTTPS<input v-model="m.config.endpoint" type="url" required></label></template>
   <label>Intervalo em horas<input v-model.number="m.config.interval_hours" type="number" min="1" max="8760" required></label>
   <label><input v-model="m.config.enabled" type="checkbox"> Agendamento ativo</label>
  </div></fieldset>
  <p>Informe apenas referências, nunca token, chave ou senha. O chaveiro externo deve ser preservado separadamente; sem a chave correta não há recuperação. A autorização OAuth e o provisionamento das credenciais são externos. Alterar a configuração recalcula o próximo horário; o agendador exige a aplicação em execução.</p>
  <button class="button primary" :disabled="m.busy||active||!!m.intent">Salvar configuração</button>
  <p>Próxima execução: {{m.status?.config?.enabled?date(m.status.next_due):'Agendamento desativado'}}. Horários apresentados no fuso deste navegador.</p>
 </form>
 <section class="panel panel-body"><h2>Backup manual</h2><button class="button primary" :disabled="m.busy||active||!m.status?.config" @click="run">{{m.intent?'Consultar/repetir mesma solicitação':'Executar backup agora'}}</button><p>Falhas de envio não são repetidas automaticamente. Cancelamento disponível antes do início do envio.</p><p v-if="m.restored" role="status">Cópia validada em {{m.restored}}. Não ativada; permissões do usuário do processo preservadas.</p></section>
 <section class="panel panel-body"><h2>Histórico de backups</h2><p v-if="!jobs.length">Nenhum backup registrado.</p><ol><li v-for="job in jobs" :key="job.id"><strong>{{labels[job.state]||job.state}}</strong> · {{date(job.created)}}<p>Solicitação {{job.id}} · {{job.encryption_key_id?'AES-256-GCM · chave '+job.encryption_key_id:'ZIP legado sem criptografia'}} · responsável {{job.actor}} · {{job.destination?.provider}} {{job.destination?.bucket||job.destination?.folder}}</p><p v-if="job.error">{{job.error}}</p><p v-if="job.checksum" class="checksum">SHA-256: {{job.checksum}}</p><button v-if="['queued','snapshot'].includes(job.state)" class="button outline" :disabled="m.busy||!!job.cancel" @click="c.cancel(job.id)">{{job.cancel?'Cancelamento solicitado':'Cancelar backup'}}</button><button v-if="job.checksum&&['completed','uncertain','interrupted'].includes(job.state)" class="button outline" :disabled="m.busy" @click="restore(job.id)">Validar e extrair cópia isolada</button></li></ol></section>
</div>
</template>
<style scoped>.panel{padding:1.25rem;margin-bottom:1rem}.backup-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:1rem}fieldset{border:0;padding:0}label{display:grid;gap:.4rem}.checksum{overflow-wrap:anywhere}li{margin:1rem 0}.panel p{margin:.75rem 0}</style>
