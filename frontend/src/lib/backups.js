import {uid} from './format.js';
export function createBackups(m,api,key=()=>uid().replaceAll('-','')) {
 let generation=0,paused=false;
 async function perform(action){
  if(m.busy||paused)return;
  const current=generation;m.busy=true;m.error='';
  try{await action(()=>current===generation&&!paused);}catch(e){if(current===generation&&!paused)m.error=e.message;}
  finally{if(current===generation)m.busy=false;}
 }
 return {
  pause(){paused=true;generation++;m.busy=false;}, resume(){paused=false;},
  status(){return perform(async alive=>{const result=await api('/backups');if(alive()){m.status=result;if(!m.loaded&&result.config){Object.assign(m.config,result.config);m.loaded=true;}}});},
  save(){return perform(async alive=>{const result=await api('/backups/config',{method:'PUT',body:{...m.config}});if(alive()){m.status=result;m.loaded=true;}});},
  run(){return perform(async alive=>{
   m.intent ||= key();
   const result=await api('/backups',{method:'POST',body:{idempotency_key:m.intent}});
   if(alive()){m.job=result;m.intent=null;}
  });},
  cancel(id){return perform(async alive=>{const result=await api(`/backups/${id}/cancel`,{method:'POST',body:{}});if(alive())m.status=result;});},
  restore(id){return perform(async alive=>{const result=await api(`/backups/${id}/restore`,{method:'POST',body:{}});if(alive())m.restored=result.directory;});}
 };
}
