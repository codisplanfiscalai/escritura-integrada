import {uid} from './format.js';
export const updateStates={
 queued:'Download aguardando início.',pulling:'Baixando a versão solicitada…',validating:'Conferindo o download…',
 prepared:'Download concluído. A versão em uso ainda não foi alterada.',
 failed:'Não foi possível concluir o download. A versão em uso não foi alterada.',
 interrupted:'O download foi interrompido. Confira o andamento antes de tentar novamente. A versão em uso não foi alterada.',
};
export const updateState=state=>updateStates[state]||'Situação ainda não confirmada. Confira o andamento.';
export const downloadActive=job=>['queued','pulling','validating'].includes(job?.state);
export function updateAvailability(status){
 if(!status)return 'Aguardando a consulta do serviço de atualização.';
 if(!status.configured)return 'O serviço de atualização ainda não foi instalado e autorizado pelo administrador.';
 if(!status.installed)return 'Não foi possível conferir a versão em uso. Peça ao administrador para verificar a instalação.';
 if(status.preparation_supported!==true)return 'A busca de versões está indisponível: a configuração precisa ser conferida pelo administrador. Nenhuma alteração foi feita.';
 return '';
}
// No source/channel is chosen by the client. Intent survives uncertain replies.
export function createDockerUpdates(model, api, key = () => uid().replaceAll('-', '')) {
 let generation=0,alive=true;
 const valid=g=>alive&&g===generation;
 const permitted=()=>!updateAvailability(model.status)&&!model.statusError;
 const active=()=>model.status?.jobs?.some(downloadActive)||downloadActive(model.status?.jobs?.find(j=>j.id===model.job?.id)||model.job);
 async function perform(fn,apply,{status=false}={}){
  if(model.busy||model.confirming||!alive)return;
  const g=generation;model.busy=true;
  if(!status){model.error='';model.diagnostic='';}
  try{const result=await fn();if(valid(g)){apply(result);if(status){if(model.statusError){model.error='';model.diagnostic='';}model.statusError=false;}}}
  catch(e){if(valid(g)){
   model.diagnostic=e.message||'Resposta não confirmada.';
   model.error=e.status===401?'Sua sessão terminou. Entre novamente para continuar.':e.status===403?'Você precisa de acesso de administrador e de uma sessão válida para continuar.':status?'Não foi possível conferir o andamento agora. Um download já solicitado pode continuar. Tente conferir novamente.':'Não foi possível confirmar a solicitação. Confira o andamento antes de tentar novamente; a versão em uso não foi alterada.';
   if(status)model.statusError=true;
  }}finally{if(valid(g))model.busy=false;}
 }
 const controller={
  status:()=>perform(()=>api('/docker-updates'),result=>{
   model.status=result;
   if(model.plan&&['configuration_hash','container_id','image_id','configured_channel'].some(k=>result.installed?.[k]!==model.plan.installed?.[k])){model.plan=null;model.intent=null;}
  },{status:true}),
  check:()=>{
   if(!permitted()||active())return;
   return perform(()=>{model.plan=null;model.intent=null;return api('/docker-updates/check',{method:'POST',body:{}});},result=>{
    model.plan=result;model.intent={plan_id:result.id,idempotency_key:key()};
   });
  },
  prepare:()=>{
   if(!permitted()||active()||!model.intent)return;
   const intent={...model.intent};
   return perform(()=>api('/docker-updates/prepare',{method:'POST',body:intent}),result=>{model.job=result;});
  },
  confirmDownload:async ask=>{
   if(model.busy||model.confirming||!alive||!permitted()||active()||!model.plan||!model.intent)return;
   const plan=model.plan,g=generation;model.confirming=true;
   let confirmed=false;
   try{confirmed=await ask({title:'Baixar esta versão?',message:`Versão ${plan.target.version}. Será feito somente o download. A versão em uso e os dados não serão alterados. Aplicar a nova versão ainda depende de uma etapa administrativa que não está disponível nesta tela.`,confirmLabel:'Confirmar download'});}finally{if(valid(g))model.confirming=false;}
   if(confirmed&&valid(g)&&model.plan===plan&&permitted()){await controller.prepare();await controller.status();}
  },
  pause:()=>{alive=false;generation++;model.busy=false;model.confirming=false;},
  resume:()=>{alive=true;},
 };
 return controller;
}
