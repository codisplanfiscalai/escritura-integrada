import {reactive} from 'vue';
export const services={nfe_distribution:{label:'DF-e',environments:{homologation:'Homologação',production:'Produção'}},nfse_adn:{label:'NFS-e Nacional',environments:{restricted_production:'Produção restrita',production:'Produção'}}};
export const directions={issued:'Emitidas',received:'Recebidas',both:'Emitidas e recebidas',unknown:'A conferir'};
export const receiptStates={received:'Recebido para conferência',in_progress:'Tentativa em andamento',uncertain:'Resultado não confirmado',authorization_pending:'Procuração/autorização pendente',received_unparsed:'Retorno preservado, interpretação pendente',unparsed_rejection:'Recusa pendente de interpretação',remote_unavailable:'Serviço indisponível',rejected:'Consulta recusada',redirect_refused:'Redirecionamento recusado',environment_mismatch:'Ambiente divergente',nsu_mismatch:'Sequência divergente'};
export function createReception({state,api,can,scope,provider}){
 if(!services[provider])throw new Error('Serviço inválido.');
 const defaults=()=>Object.keys(services[provider].environments)[0];
 const m=reactive({provider,environment:defaults(),configuration:null,data:null,applied:'',receipt:null,history:null,historyLoading:false,document:null,documentLoading:false,query:'',direction:'',competence:'',error:'',check:null,loading:false,busy:false,intent:null});
 let active=false,version=0,reader=null,owner=null,receiptVersion=0,documentVersion=0,historyVersion=0;
 const context=()=>({companyId:state.companyId,period:state.period,year:state.period.slice(0,4),module:state.module,uid:state.session?.user?.id});
 const same=c=>c.companyId===state.companyId&&c.period===state.period&&c.module===state.module&&c.uid===state.session?.user?.id;
 const readable=()=>!!state.companyId&&state.module==='fiscal'&&!!state.session?.user&&can('fiscal.imports','read');
 const valid=(c,v)=>active&&version===v&&same(c)&&readable();
 function release(key){if(state.editor?.owner===key)state.editor=null;if(owner===key)owner=null;}
 function invalidate(clear){version++;receiptVersion++;documentVersion++;historyVersion++;reader?.abort();reader=null;if(owner)release(owner);Object.assign(m,{configuration:null,data:null,applied:'',receipt:null,history:null,historyLoading:false,document:null,documentLoading:false,check:null,error:'',loading:false,busy:false});if(clear){m.intent=null;m.environment=defaults();m.query='';m.direction='';m.competence='';}}
 function reset(){invalidate(true);if(active&&readable())load();}
 function activate(){if(active)return;active=true;if(readable())load();}
 function deactivate(){active=false;invalidate(false);}
 function params(offset=0){return new URLSearchParams({year:state.period.slice(0,4),query:m.query,direction:m.direction,competence:m.competence,offset:String(offset)});}
 async function load(offset=0){
  if(!active||!readable())return;
  reader?.abort();const abort=new AbortController();reader=abort;const c=context(),v=version,filters=params(offset).toString();m.loading=true;m.error='';
  try{
   const result=await api(scope('/reception/'+provider+'?'+filters,c.companyId),{signal:abort.signal});
   if(!valid(c,v)||abort.signal.aborted)return;
   const selected=result.configuration;
   if(!selected?.revision||!services[provider].environments[selected.environment]||result.environment!==selected.environment)throw new Error('Configuração da empresa indisponível. Atualize a tela.');
   if(m.configuration?.revision!==selected.revision){receiptVersion++;documentVersion++;m.check=null;m.receipt=null;m.document=null;m.documentLoading=false;}
   historyVersion++;m.history=null;m.historyLoading=false;m.configuration=selected;m.environment=selected.environment;m.data=result;m.applied=new URLSearchParams({...Object.fromEntries(new URLSearchParams(filters)),environment:selected.environment}).toString();
  }catch(e){if(valid(c,v)&&!abort.signal.aborted)m.error=e.message;}
  finally{if(valid(c,v)&&reader===abort){m.loading=false;reader=null;}}
 }
 async function write(action,body){
  if(m.busy||!readable()||!can('fiscal.imports','import')||state.editor)return;
  const c=context(),v=version,revision=m.configuration?.revision,key=Symbol('reception');owner=key;m.busy=true;m.error='';state.editor={owner:key,name:'Recepção fiscal',companyId:c.companyId};
  try{const result=await api(scope('/reception/'+provider+'/'+action,c.companyId),{method:'POST',body,context:{companyId:c.companyId,year:c.year,module:c.module}});return valid(c,v)&&(action!=='check'||revision===m.configuration?.revision)?result:undefined;}
  catch(e){if(valid(c,v)){m.error=e.message;throw e;}}
  finally{if(version===v&&same(c))m.busy=false;release(key);}
 }
 async function check(){if(!m.configuration)return;try{const r=await write('check',{configuration_revision:m.configuration.revision});if(r)m.check=r;}catch(e){if(['stale_reception_configuration','stale_credential'].includes(e.code))await load();}}
 async function capture(retry=false){
  if(!m.configuration||!m.data?.capabilities.remote_available||m.busy||state.editor||!can('fiscal.imports','import')||m.intent&&!retry)return;
  if(!m.intent){const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);m.intent={context:context(),body:{environment:m.configuration.environment,configuration_revision:m.configuration.revision,period:state.period,idempotency_key:'ui-'+Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('')}};}
  if(!same(m.intent.context))return;const intent=m.intent;
  try{const r=await write('query',{...intent.body});if(r){m.receipt=r;m.intent=null;await load();}}
  catch(e){if(m.intent===intent){if(['stale_reception_configuration','stale_credential'].includes(e.code)){m.intent=null;const message=e.message;await load();if(same(intent.context))m.error=message;}else if([400,422].includes(e.status))m.intent=null;else m.error='Tentativa sem confirmação. Confira o recibo ou repita explicitamente a mesma identificação. '+e.message;}}
 }
 async function receipt(key,recover=false){
  if(!active||!readable()||m.busy)return;const c=context(),v=version,env=m.environment,seq=++receiptVersion;
  try{const r=await api(scope('/imports/reception/receipts/'+encodeURIComponent(key),c.companyId));if(!valid(c,v)||seq!==receiptVersion||env!==m.environment)return;if(r.provider!==provider||r.environment&&r.environment!==env)throw new Error('Recibo de outro serviço ou ambiente.');m.receipt=r;if(recover&&r.state!=='in_progress')m.intent=null;}
  catch(e){if(valid(c,v)&&seq===receiptVersion)m.error=e.status===404?'Recibo ainda não localizado. Repetir usa a mesma identificação.':e.message;}
 }
 async function history(offset=0){
  if(!active||!readable())return;
  const c=context(),v=version,env=m.environment,seq=++historyVersion;
  m.historyLoading=true;m.error='';
  try{
   const filters=new URLSearchParams({environment:env,year:c.year,offset:String(offset)});
   const r=await api(scope('/reception/'+provider+'/receipts?'+filters,c.companyId));
   if(!valid(c,v)||seq!==historyVersion||env!==m.environment)return;
   if(r.provider!==provider||r.environment!==env)throw new Error('Histórico de outro serviço ou ambiente.');
   m.history=r;
  }catch(e){if(valid(c,v)&&seq===historyVersion)m.error=e.message;}
  finally{if(valid(c,v)&&seq===historyVersion)m.historyLoading=false;}
 }
 async function versions(id,offset=0){
  if(!active||!readable())return;const c=context(),v=version,env=m.environment,seq=++documentVersion;
  if(m.document?.record_id!==id)m.document=null;m.documentLoading=true;
  const filters=new URLSearchParams({environment:env,year:c.year,offset:String(offset)});
  try{const r=await api(scope('/reception/'+provider+'/documents/'+encodeURIComponent(id)+'?'+filters,c.companyId));if(!valid(c,v)||seq!==documentVersion||env!==m.environment)return;if(r.provider!==provider||r.environment!==env)throw new Error('Versões de outro serviço ou ambiente.');m.document=r;}
  catch(e){if(valid(c,v)&&seq===documentVersion&&env===m.environment)m.error=e.message;}
  finally{if(valid(c,v)&&seq===documentVersion&&env===m.environment)m.documentLoading=false;}
 }
 function download(row,original=false){if(!readable()||!can('fiscal.imports','export'))return '';return '/api'+scope('/imports/reception/receipts/'+encodeURIComponent(row.receipt_key)+(original?'/download':'/documents/'+encodeURIComponent(row.nsu)+'/download'));}
 function report(view='documents'){return readable()&&m.data&&can('fiscal.imports','export')?'/api'+scope('/reception/'+provider+'/report?'+m.applied+(view==='occurrences'?'&view=occurrences':'')):'';}
 return {m,readable,activate,deactivate,reset,load,check,capture,receipt,history,versions,download,report};
}
