import {reactive,computed,watch} from 'vue';
const copy=value=>JSON.parse(JSON.stringify(value));
export const prosoftDefaults=(area,companyCode='')=>({company_code:companyCode,plan_code:'0050',record_types:area==='fiscal'?['incoming_notes','outgoing_notes']:['LC1','LC2'],...(area==='accounting'?{batch:'1',accounts:{},centers:{},participants:{}}:{species:{55:{code:'',confirmed:false},65:{code:'',confirmed:false}},cfop_accounts:{}})});
export function accountingProfile(types){return types.includes('CTA')?(types.includes('TRC')?'journals_cta_trc':'journals_cta'):(types.includes('TRC')?'journals_trc':'journals');}
export function accountingTypes(profile){return {journals:['LC1','LC2'],journals_cta:['LC1','LC2','CTA'],journals_trc:['LC1','LC2','TRC'],journals_cta_trc:['LC1','LC2','CTA','TRC']}[profile]?.slice()||['LC1','LC2'];}
const contextKey=c=>JSON.stringify([c.cid,c.year,c.module,c.period,c.area]);

// One owner for saved versions, local drafts and asynchronous responses. Injected
// requests make the same state transitions testable without a browser or server.
export function createProsoftExport({context,request,references=async()=>({accounts:[],centers:[],parties:[]})}){
 const s=reactive({config:prosoftDefaults(context().area),version:0,loaded:false,loading:false,busy:false,error:'',message:'',
  records:{accounts:[],centers:[],parties:[]},unavailable:{},preview:null,result:null,reviewed:false,ascii:false});
 let identities={},sequence=0,silent=false,baseline=JSON.stringify(s.config);
 const dirty=computed(()=>JSON.stringify(s.config)!==baseline);
 function invalidate(){sequence++;s.preview=null;s.result=null;s.reviewed=false;s.ascii=false;s.busy=false;s.loading=false;}
 const stop=watch(()=>s.config,()=>{if(!silent){invalidate();s.message='';}},{deep:true,flush:'sync'});
 function replace(value){silent=true;try{s.config=copy(value);baseline=JSON.stringify(s.config);}finally{silent=false;}}
 function reset(companyCode=''){invalidate();replace(prosoftDefaults(context().area,companyCode));s.loaded=false;s.version=0;s.error='';s.message='';s.records={accounts:[],centers:[],parties:[]};s.unavailable={};identities={};}
 function current(token,c){return token===sequence&&contextKey(c)===contextKey(context());}
 function path(c){return c.area==='fiscal'?'/prosoft-fiscal':'/prosoft';}
 function accountDefault(a){const code=a.prosoft_code||a.access_code||'';return {code:/^[0-9]{1,5}$/.test(code)?code:'',confirmed:false,third_mode:'none',third:'',third_type:'normal'};}
 function ensureAccounts(records){for(const account of records)s.config.accounts[account.id]??=accountDefault(account);}
 function withDefaults(config,records,c){
  const value=copy(config);
  if(c.area==='accounting'){
   const next={},used=new Set(records.used||[]);
   for(const a of records.accounts||[]){if(!a.analytical)continue;
    const identity=a.shared_entry_id?`global:${a.shared_entry_id}`:`local:${a.id}`,oldId=identities[identity];next[identity]=a.id;
    if(oldId!==undefined&&oldId!==a.id&&value.accounts[oldId]&&!value.accounts[a.id]){value.accounts[a.id]=value.accounts[oldId];delete value.accounts[oldId];}
    if(used.has(a.id))value.accounts[a.id]??=accountDefault(a);
   }
   identities=next;
   for(const center of records.centers||[])value.centers[center.id]??={code:/^[0-9]{1,5}$/.test(center.prosoft_code||'')?center.prosoft_code:'',confirmed:false};
   for(const party of records.parties||[])value.participants[party.id]??={code:'',third_type:'normal',confirmed:false};
  }
  return value;
 }
 async function load(force=false){
  const c=copy(context());if(!c.cid||!c.period)return;invalidate();const token=++sequence;s.loading=true;s.error='';
  try{
   const [saved,records]=await Promise.all([request(c,'GET',path(c)+'/settings'),references(c)]);
   if(!current(token,c))return;
   s.records=records;s.unavailable=saved.unavailable_accounts||{};
   if(force||!s.loaded||!dirty.value){replace(withDefaults(saved.settings,records,c));s.version=saved.version;s.loaded=true;s.message=force?'Mapeamentos salvos recarregados.':'';}
   else {silent=true;try{s.config=withDefaults(s.config,records,c);}finally{silent=false;}
    if(saved.version!==s.version)s.error='Os mapeamentos salvos mudaram. Recarregue os salvos antes de salvar ou exportar.';}
  }catch(e){if(current(token,c))s.error=e.message;}
  finally{if(current(token,c))s.loading=false;}
 }
 async function save(){
  if(!s.loaded||s.loading||s.busy)return;const c=copy(context()),token=++sequence,settings=copy(s.config);s.busy=true;s.error='';
  try{
   const saved=await request(c,'PUT',path(c)+'/settings',{version:s.version,settings});
   if(!current(token,c))return;replace(withDefaults(saved.settings,s.records,c));s.version=saved.version;s.unavailable=saved.unavailable_accounts||{};
   s.preview=null;s.result=null;s.reviewed=false;s.ascii=false;s.message='Mapeamentos salvos nesta empresa.';
  }catch(e){if(current(token,c))s.error=e.message;}
  finally{if(current(token,c))s.busy=false;}
 }
 async function run(confirm=false){
  if(!s.loaded||s.loading||s.busy||confirm&&!s.preview)return;const c=copy(context()),token=++sequence;
  const payload={...copy(s.config),period:c.period,settings_version:s.version,preview_hash:s.preview?.preview_hash,allow_ascii:s.ascii,destination_reviewed:s.reviewed};
  s.busy=true;s.error='';s.message='';
  try{
   const value=await request(c,'POST',path(c)+(confirm?'/confirm':'/preview'),payload);
   if(!current(token,c))return;
   if(confirm){s.result={...value,cid:c.cid,area:c.area,period:c.period};s.message='Lote preparado para download. A importação no Prosoft precisa ser feita e conferida no destino.';}
   else{s.preview=value;s.result=null;s.reviewed=false;s.ascii=false;}
  }catch(e){if(current(token,c))s.error=e.message;}
  finally{if(current(token,c))s.busy=false;}
 }
 return {s,dirty,load,save,run,reset,invalidate,ensureAccounts,dispose:()=>{invalidate();stop();}};
}
export const prosoftDownload=result=>`/api/companies/${result.cid}${result.area==='fiscal'?'/prosoft-fiscal':''}/exports/${result.id}/download`;

export const prosoftManifest=result=>result.area==='accounting'?`/api/companies/${result.cid}/prosoft/exports/${result.id}/manifest?download=1`:'';
