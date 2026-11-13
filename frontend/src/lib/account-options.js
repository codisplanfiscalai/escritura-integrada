import {normalized} from './format.js';

export function accountOptions(accounts,query='',selected='',limit=200){
 const id=Number(selected),term=normalized(query).trim();
 const chosen=accounts.find(a=>a.id===id)||(id<0?accounts.find(a=>a.shared_entry_id===-id):null);
 const matching=accounts.filter(a=>!term||normalized(`${a.access_code} ${a.classifier} ${a.name}`).includes(term));
 const result=matching.slice(0,limit);
 if(chosen){
  const index=result.findIndex(a=>a.id===chosen.id);
  const selected=chosen.id===id?chosen:{...chosen,id};
  // Native keyboard selection changes the model on every ArrowDown. Never
  // move an option already in the window, or the next arrow targets another
  // account. A retained selection outside the window belongs at the end.
  if(index<0)result.push(selected);
  else if(chosen.id!==id)result[index]=selected;
 }
 return {rows:result,total:matching.length,limited:matching.length>limit};
}
