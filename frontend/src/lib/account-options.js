import {normalized} from './format.js';

export function accountOptions(accounts,query='',selected='',limit=200){
 const id=Number(selected),term=normalized(query).trim();
 const chosen=accounts.find(a=>a.id===id)||(id<0?accounts.find(a=>a.shared_entry_id===-id):null);
 const matching=accounts.filter(a=>!term||normalized(`${a.access_code} ${a.classifier} ${a.name}`).includes(term));
 const result=matching.filter(a=>a.id!==chosen?.id).slice(0,limit);
 if(chosen)result.unshift(chosen.id===id?chosen:{...chosen,id});
 return {rows:result,total:matching.length,limited:matching.length>limit};
}
