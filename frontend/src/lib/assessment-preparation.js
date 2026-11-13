// Suggestions only: never infer an invoice total as taxable base or a credit entitlement.
export function compatibleRules(document, rules, tax, company={}) {
 return rules.filter(r=>String(r.tax).toLowerCase()===tax&&r.status==='validated'&&r.active&&!r.superseded_by&&r.valid_from<=document.posting_date&&(!r.valid_to||r.valid_to>=document.posting_date)&&['both',document.direction].includes(r.direction)&&
  (!r.cfop||(document.items?.length?document.items.every(i=>(i.cfop||document.cfop)===r.cfop):document.cfop===r.cfop))&&
  (!r.ncm||(document.items?.length&&document.items.every(i=>i.ncm===r.ncm)))&&
  ['regime','state'].every(k=>!r[k]||r[k]===company[k])&&(!r.municipality||r.municipality===company.ibge));
}
export function declaredBase(document,tax) {
 const paths={icms:['ICMSTot.vBC'],iss:['ISSQNtot.vBC','ISSQNtot.vBCISS']}[tax]||[];
 const values=paths.filter(k=>Object.hasOwn(document.taxes||{},k)).map(k=>String(document.taxes[k]).trim());
 if(!values.length)return '';
 if(Object.hasOwn(document.taxes||{},'vBC'))values.push(String(document.taxes.vBC).trim());
 if(values.some(v=>!/^\d+(\.\d{1,2})?$/.test(v)))return '';
 const normalized=values.map(v=>{const [a,b='']=v.split('.');return `${a.replace(/^0+(?=\d)/,'')}.${b.padEnd(2,'0')}`;});
 return new Set(normalized).size===1?normalized[0].replace('.',','):'';
}
export function prepareEntries(documents,rules,tax,company,period) {
 const docs=documents.filter(d=>d.status==='booked'&&!d.book_cancellation&&d.period===period);
 if(docs.length>1000)throw new Error('Mais de 1.000 documentos na competência. Selecione e confira as bases em grupos antes de registrar a memória.');
 return docs.map(d=>{const compatible=compatibleRules(d,rules,tax,company);return {document_id:d.id,rule_id:compatible.length===1?compatible[0].id:'',effect:'',base:declaredBase(d,tax),reason:'',item_indices:[],selected:true};});
}
export function entriesPayload(entries,amount) {
 return entries.filter(e=>e.selected!==false).map(e=>{
  if(!e.document_id||!e.rule_id||!['debit','credit'].includes(e.effect)||!String(e.base).trim()||!e.reason.trim())throw new Error('Confira documento, regra, natureza, base e fundamento de cada base selecionada.');
  return {document_id:e.document_id,rule_id:e.rule_id,effect:e.effect,base:amount(e.base),reason:e.reason.trim(),item_indices:e.item_indices||[]};
 });
}
