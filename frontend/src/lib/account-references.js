// Keep a reviewed mapping attached to the immutable account identity when its
// virtual global alias acquires a company-owned operational ID.
export function reconcileAccountMappings(previous,identities,records){
 const mappings={},nextIdentities={};let idsChanged=false;
 for(const account of records){
  const identity=account.shared_entry_id?`global:${account.shared_entry_id}`:`local:${account.id}`;
  const oldId=identities[identity];
  mappings[account.id]=previous[account.id]??previous[oldId]??{code:account.prosoft_code||account.access_code,confirmed:false,third_mode:'none',third:'',third_type:'normal'};
  nextIdentities[identity]=account.id;
  if(oldId!==undefined&&oldId!==account.id)idsChanged=true;
 }
 return {mappings,identities:nextIdentities,idsChanged};
}
