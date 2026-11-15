<script setup>
import {computed,ref} from 'vue';
import {api,ask} from '../lib/workspace';
import {uid} from '../lib/format.js';
const props=defineProps({status:Object,disabled:Boolean});
const emit=defineEmits(['changed']);
const busy=ref(false),error=ref(''),intents=new Map();
const cuts=computed(()=>props.status?.cutovers||[]);
const pending=computed(()=>cuts.value.some(c=>!['completed','recovered_previous','blocked'].includes(c.state)));
const prepared=computed(()=>props.status?.jobs?.find(j=>j.state==='prepared'));
const labels={validating:'Conferindo contrato',quiescing:'Bloqueando escritas e encerrando',backup:'Criando backup consistente',recreating:'Recriando aplicação',healthcheck:'Confirmando saúde em manutenção',releasing:'Liberando escritas',completed:'Atualização confirmada',blocked:'Corte recusado antes da manutenção',recovery_required:'Recuperação administrativa necessária',recovering:'Verificando recuperação',recovered_previous:'Imagem anterior retomada · dados preservados',releasing_previous:'Liberando a imagem anterior'};
async function update(){
 if(busy.value||props.disabled||pending.value||!props.status?.cutover_supported||!prepared.value)return;
 const job=prepared.value;
 busy.value=true;
 let confirmed;
 try{confirmed=await ask({title:'Atualizar a aplicação Docker?',message:`${job.installed.version} → ${job.target.version}, canal ${job.channel}. Digest ${job.target.digest}. Confirme a janela exclusiva: nenhum outro operador ou processo pode gravar nos dados ou operar a stack. A aplicação ficará indisponível durante backup, recriação e verificações; a duração depende dos dados. Só haverá corte com contrato compatível e backup verificado.`,confirmLabel:'Confirmar janela e atualizar',danger:true});}finally{busy.value=false;}
 if(!confirmed||props.disabled||pending.value||!props.status?.cutover_supported||prepared.value?.id!==job.id)return;
 if(!intents.has(job.id))intents.set(job.id,{prepared_id:job.id,idempotency_key:uid().replaceAll('-','')});
 await perform('/docker-updates/cutover',intents.get(job.id));
}
async function recover(cut,mode){
 if(busy.value||props.disabled)return;
 if(!await ask({title:mode==='previous'?'Retomar a imagem anterior?':'Conferir e concluir o alvo?',message:mode==='previous'?'Só será permitido se as escritas não tiverem sido liberadas e os dados continuarem congelados e compatíveis. Nenhum backup será restaurado.':'O executor confere identidade/configuração e saúde. Se as escritas já foram liberadas, preserva todos os dados atuais e não retorna à imagem antiga.',confirmLabel:'Solicitar verificação',danger:true}))return;
 await perform(`/docker-updates/${mode==='previous'?'recover-previous':'reconcile-target'}`,{cutover_id:cut.id});
}
async function perform(path,body){busy.value=true;error.value='';try{await api(path,{method:'POST',body});}catch(e){error.value=e.message;}finally{busy.value=false;emit('changed');}}
</script>
<template>
 <section class="panel cutover-panel">
  <h2>Aplicar imagem preparada</h2>
  <p v-if="!status?.cutover_supported">Corte não autorizado no host. A preparação continua disponível; instalação e autoridade adicional dependem do administrador.</p>
  <template v-else><p>O alvo permanece sem escritas até confirmar contrato, backup, configuração, healthcheck e resposta HTTP. O período de reinício pode interromper a consulta desta tela; ela retomará o histórico.</p><button class="button primary" :disabled="busy||disabled||pending||!prepared" @click="update">Atualizar aplicação por digest</button></template>
  <p v-if="error" class="message error" role="alert">{{error}} Confira o estado antes de repetir; o executor pode continuar.</p>
  <ol><li v-for="cut in cuts" :key="cut.id"><strong>{{labels[cut.state]||cut.state}}</strong><p>{{cut.installed.version}} → {{cut.target.version}} · {{cut.channel}} · {{cut.id}}</p><p class="digest">{{cut.target.digest}}</p><p v-if="cut.backup">Backup verificado · {{cut.backup.files}} entradas · {{cut.backup.bytes}} bytes</p><p v-if="cut.error" role="alert">{{cut.error}}</p><template v-if="cut.state==='recovery_required'&&status?.cutover_supported"><button class="button outline" :disabled="busy||disabled" @click="recover(cut,'target')">Conferir/liberar alvo</button><button class="button outline" :disabled="busy||disabled" @click="recover(cut,'previous')">Solicitar imagem anterior</button></template></li></ol>
  <p>Não há restauração automática de backup. Após liberar escritas no alvo, retornar à imagem anterior é proibido por este executor. Se a interface não voltar, o administrador deve usar o canal local de recuperação documentado.</p>
 </section>
</template>
<style scoped>.cutover-panel{padding:1.25rem;margin-bottom:1rem}.cutover-panel p{margin:.6rem 0}.digest{overflow-wrap:anywhere}button{margin:.3rem .4rem .3rem 0}</style>
