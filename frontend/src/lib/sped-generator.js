import {reactive} from 'vue';
export function createSpedGenerator({state,api,can,scope}) {
 const m=reactive({profile:'',activity:'',purpose:'',consolidate:false,segment:true,result:null,error:'',busy:false});
 let active=true,sequence=0,controller,acceptedContext,acceptedOptions;
 const context=()=>JSON.stringify([state.companyId,state.period,state.session?.user?.id,state.session?.permissions]);
 const options=()=>({period:state.period,profile:m.profile,activity:m.activity,purpose:m.purpose,consolidate_nfce:m.consolidate,segment_on_gap:m.segment});
 const permitted=()=>Boolean(state.companyId&&state.module==='fiscal'&&can('fiscal.documents','read')&&can('fiscal.documents','export'));
 function cancel(){sequence++;controller?.abort();m.busy=false;}
 function invalidate(){cancel();m.result=null;m.error='';}
 function reset(){invalidate();m.profile='';m.activity='';m.purpose='';m.consolidate=false;m.segment=true;}
 async function generate(){
  if(!active||m.busy||!permitted())return;
  const c=context(),body=options(),key=JSON.stringify(body),seq=++sequence;
  if(!['A','B','C'].includes(body.profile)||!['0','1'].includes(body.activity)||!['0','1'].includes(body.purpose)){m.error='Informe perfil, atividade e finalidade para gerar o recorte.';return;}
  controller=new AbortController();m.busy=true;m.error='';m.result=null;
  const current=()=>active&&seq===sequence&&c===context()&&key===JSON.stringify(options())&&permitted();
  try{
   const result=await api(scope('/sped-generator/bookkeeping-block-c'),{method:'POST',body,signal:controller.signal});
   if(!current())return;
   if(result.company_id!==state.companyId||result.period!==body.period||typeof result.content_base64!=='string')throw new Error('Resultado não corresponde à empresa e competência selecionadas.');
   m.result=result;acceptedContext=c;acceptedOptions=key;
  }catch(e){if(current()&&e.name!=='AbortError')m.error=e.message;}
  finally{if(seq===sequence)m.busy=false;}
 }
 function downloadable(){return active&&permitted()&&acceptedContext===context()&&acceptedOptions===JSON.stringify(options())&&m.result?.company_id===state.companyId&&m.result?.period===state.period;}
 function file(){if(!downloadable())return null;const raw=atob(m.result.content_base64);return {bytes:Uint8Array.from(raw,c=>c.charCodeAt(0)),name:m.result.filename};}
 function activate(){active=true;}
 function deactivate(){active=false;cancel();}
 return {m,generate,invalidate,reset,cancel,activate,deactivate,permitted,downloadable,file};
}
