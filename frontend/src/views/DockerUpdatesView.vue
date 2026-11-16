<script setup>
import {reactive,onActivated,onDeactivated,onUnmounted,computed} from 'vue';
import {api,ask} from '../lib/workspace';
import {createDockerUpdates,updateState,downloadActive,updateAvailability} from '../lib/docker-updates.js';
const m=reactive({busy:false,confirming:false,error:'',diagnostic:'',statusError:false,status:null,plan:null,intent:null,job:null});
const controller=createDockerUpdates(m,api);
let timer=null;
const jobs=computed(()=>m.status?.jobs||[]);
const currentJob=computed(()=>jobs.value.find(j=>j.id===m.job?.id)||m.job);
const active=computed(()=>jobs.value.some(downloadActive)||downloadActive(currentJob.value));
const unavailable=computed(()=>updateAvailability(m.status));
const occupied=computed(()=>m.busy||m.confirming);
const currentVersion=computed(()=>m.status?.installed?.version||m.status?.application_version);
function stop(){clearInterval(timer);timer=null;controller.pause();}
onActivated(()=>{controller.resume();controller.status();clearInterval(timer);timer=setInterval(()=>{if(active.value&&!occupied.value)controller.status();},3000);});
onDeactivated(stop);onUnmounted(stop);
</script>
<template>
 <div class="view">
  <header class="view-heading"><div><div class="eyebrow">ADMINISTRAÇÃO</div><h1>Atualização da aplicação</h1><p>Confira a versão em uso e consulte a disponibilidade de download.</p></div><button class="button outline" :disabled="occupied" @click="controller.status">Conferir andamento</button></header>
  <p class="message warning">Nesta tela é possível apenas consultar e baixar uma versão. Aplicar a nova versão ainda não está disponível: exige uma pausa nas operações, cópia de segurança dos dados e conferência pelo administrador. Não há retorno automático à versão anterior nem restauração automática dos dados.</p>
  <p v-if="m.error" class="message error" role="alert">{{m.error}}</p>
  <section class="panel panel-body">
   <h2>Versão em uso</h2><p v-if="currentVersion"><strong>{{currentVersion}}</strong></p><p v-else>A versão em uso ainda não pôde ser conferida.</p>
   <p v-if="unavailable" role="status">{{unavailable}}</p>
  </section>
  <section class="panel panel-body">
   <h2>Versão disponível</h2>
   <p>A busca segue a configuração existente da aplicação. Consultar ou baixar não altera essa configuração nem a versão em uso.</p>
   <button class="button outline" :disabled="occupied||active||!!unavailable||m.statusError" @click="controller.check">Buscar versão disponível</button>
   <template v-if="m.plan"><p>Versão encontrada: <strong>{{m.plan.target.version}}</strong>.</p><p v-if="m.plan.target.image_id===m.plan.installed.image_id">A versão encontrada já está em uso.</p><button class="button primary" :disabled="occupied||active||!!unavailable||m.statusError" @click="controller.confirmDownload(ask)">Baixar versão</button></template>
   <p v-else>Ainda não há uma versão disponível confirmada nesta consulta.</p>
   <p v-if="occupied" role="status">{{m.confirming?'Aguardando sua confirmação…':'Conferindo informações…'}}</p>
   <p v-if="currentJob" role="status">{{updateState(currentJob.state)}}</p>
  </section>
  <section class="panel panel-body"><h2>Histórico de downloads</h2><p v-if="!jobs.length">Nenhum download solicitado.</p><ol><li v-for="job in jobs" :key="job.id"><strong>{{job.target.version||'Versão ainda não confirmada'}}</strong><p>{{updateState(job.state)}}</p><p v-if="job.error">O administrador pode consultar o motivo no diagnóstico abaixo.</p></li></ol></section>
  <details class="panel panel-body update-diagnostics"><summary>Diagnóstico administrativo</summary>
   <p>Informações técnicas para conferir a instalação. Nenhum dado de acesso é exibido.</p>
   <p v-if="m.status?.application_version">Versão desta interface: {{m.status.application_version}}</p>
   <p v-if="m.status?.configured&&!m.status?.preparation_supported">O executor precisa identificar o canal pela referência configurada do serviço: somente develop/latest do repositório fixo são reconhecidos. Referência por digest ou versão específica não identifica um canal; não há inferência nem troca automática. Um executor anterior pode precisar de atualização administrativa.</p>
   <p v-if="m.status?.installed_error">{{m.status.installed_error}}</p><p v-if="m.diagnostic" role="alert">{{m.diagnostic}}</p><p v-if="m.status?.limitation">{{m.status.limitation}}</p>
   <template v-if="m.status?.installed"><p>Versão instalada: {{m.status.installed.version}} · UID/GID {{m.status.installed.uid_gid}}</p><p class="technical">Imagem: {{m.status.installed.image_id}}</p><p class="technical">Digest instalado: {{m.status.installed.digest||'Não registrado'}}</p><p>Canal identificado: {{m.status.installed.configured_channel||'Não comprovado'}}</p></template>
   <template v-if="m.plan"><p>Canal consultado: {{m.plan.channel}}</p><p class="technical">Digest consultado: {{m.plan.target.digest}}</p></template>
   <ol><li v-for="job in jobs" :key="job.id"><p>Solicitação {{job.id}} · {{job.channel}} · {{job.state}}</p><p class="technical">{{job.target.digest}}</p><p v-if="job.error">{{job.error}}</p></li></ol>
  </details>
 </div>
</template>
<style scoped>.technical{overflow-wrap:anywhere}.panel{margin-bottom:1rem;padding:1.25rem}.panel h2{margin-bottom:.75rem}.panel p{margin:.55rem 0}li{margin-bottom:1rem}summary{cursor:pointer;font-weight:600}</style>
