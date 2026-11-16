<script setup>
import {reactive,onActivated,onDeactivated,onUnmounted,computed} from 'vue';
import {api,ask} from '../lib/workspace';
import {createDockerUpdates} from '../lib/docker-updates.js';
const m=reactive({channel:'develop',busy:false,error:'',status:null,plan:null,intent:null,job:null});
const controller=createDockerUpdates(m,api);
let timer=null;
const jobs=computed(()=>m.status?.jobs||[]);
const states={queued:'Aguardando',pulling:'Baixando imagem',validating:'Verificando imagem',prepared:'Imagem preparada · aplicação ainda não atualizada',failed:'Preparação falhou',interrupted:'Interrompida · conferir cache'};
const currentJob=computed(()=>jobs.value.find(j=>j.id===m.job?.id)||m.job);
const active=computed(()=>jobs.value.some(j=>['queued','pulling','validating'].includes(j.state))||['queued','pulling','validating'].includes(currentJob.value?.state));
async function prepare(){
  if(m.busy||!m.plan)return;
  const plan=m.plan;
  if(!await ask({title:'Baixar esta imagem?',message:`Canal ${plan.channel}. Digest ${plan.target.digest}. Somente download: a aplicação continuará na imagem instalada e os dados não serão migrados.`,confirmLabel:'Baixar imagem'}))return;
  if(m.plan===plan)await controller.prepare();
  await controller.status();
}
function stop(){clearInterval(timer);timer=null;controller.pause();}
onActivated(()=>{controller.resume();controller.status();clearInterval(timer);timer=setInterval(()=>{if(active.value&&!m.busy)controller.status();},3000);});
onDeactivated(stop);onUnmounted(stop);
</script>
<template>
  <div class="view">
    <header class="view-heading"><div><div class="eyebrow">ADMINISTRAÇÃO DO AMBIENTE</div><h1>Atualização Docker</h1><p>Etapa disponível: consultar e baixar a imagem. A substituição da aplicação permanece pendente.</p></div><button class="button outline" :disabled="m.busy" @click="controller.status">Conferir estado</button></header>
    <p class="message warning">A substituição do container está indisponível: exige uma janela sem escritas, backup consistente e validação de esquema/dados. Não há rollback ou restauração automática.</p>
    <p v-if="m.error" class="message error" role="alert">{{m.error}} Após falha de comunicação, confira o histórico; a preparação pode continuar no executor.</p>
    <section class="panel panel-body">
      <h2>Imagem instalada</h2>
      <template v-if="m.status?.installed"><p>Versão: <strong>{{m.status.installed.version}}</strong> · UID/GID {{m.status.installed.uid_gid}}</p><p class="mono updater-digest">Digest: {{m.status.installed.digest||'Não registrado na imagem local'}}</p><p class="mono updater-digest">ID: {{m.status.installed.image_id}}</p></template>
      <p v-else>{{m.status?.installed_error||m.status?.limitation||'Consultando executor…'}}</p>
      <p v-if="!m.status?.configured">O administrador precisa instalar e autorizar o executor externo. A versão desta aplicação é {{m.status?.application_version||'—'}}; o digest Docker ainda não foi verificado.</p>
    </section>
    <section class="panel panel-body">
      <h2>Preparar imagem alvo</h2>
      <label>Canal<select :value="m.channel" :disabled="m.busy||active" @change="controller.channel($event.target.value)"><option value="develop">develop · pré-release</option><option value="latest">latest · main estável</option></select></label>
      <p class="field-help">A escolha consulta somente esse canal. Baixar não altera o canal configurado na stack.</p>
      <button class="button outline" :disabled="m.busy||active||!m.status?.configured" @click="controller.check">Consultar alvo</button>
      <div v-if="m.plan"><p>Alvo consultado: {{m.plan.channel}} · versão {{m.plan.target.version}}.</p><p class="mono updater-digest">{{m.plan.target.digest}}</p><p>Imagem anterior registrada: {{m.plan.installed.version}}.</p><button class="button primary" :disabled="m.busy||active" @click="prepare">Baixar imagem por digest</button></div>
      <p v-if="m.busy" role="status">Consultando ou registrando solicitação…</p>
      <p v-if="currentJob" role="status">{{states[currentJob.state]||currentJob.state}} · {{currentJob.error||''}}</p>
    </section>
    <section class="panel panel-body"><h2>Histórico de preparação</h2><p v-if="!jobs.length">Nenhuma preparação registrada pelo executor.</p><ol><li v-for="job in jobs" :key="job.id"><strong>{{states[job.state]||job.state}}</strong><p>{{job.channel}} · {{job.target.version||'Versão ainda não confirmada'}} · solicitação {{job.id}}</p><p class="mono updater-digest">{{job.target.digest}}</p><p v-if="job.error">{{job.error}}</p></li></ol><p>“Preparada” confirma apenas o download e a identidade da imagem. O estado de saúde da aplicação alvo só poderá ser comprovado no futuro corte.</p></section>
  </div>
</template>
<style scoped>.updater-digest{overflow-wrap:anywhere}.panel{margin-bottom:1rem;padding:1.25rem}.panel h2{margin-bottom:.75rem}.panel p{margin:.55rem 0}li{margin-bottom:1rem}</style>
