export const reusableFields = Object.freeze({name:'Nome / razão social',trade_name:'Nome fantasia',address:'Logradouro',number:'Número',district:'Bairro',city:'Município',state:'UF',postal_code:'CEP',ibge:'Código IBGE',im:'Inscrição municipal',cnae:'CNAE',state_registrations:'Inscrições estaduais'});
const normalizeTaxId=value=>String(value||'').replace(/[.\/\-\s]/g,'').toUpperCase();
export function matchingParties(items,target){const tax=normalizeTaxId(target?.tax_id);return tax?items.filter(r=>normalizeTaxId(r.tax_id)===tax):[];}
export function requestGuard(context,readContext){let generation=0,alive=true;return {begin:()=>++generation,invalidate:()=>{generation++;},dispose:()=>{alive=false;generation++;},current:n=>alive&&n===generation&&context===readContext()};}
export const contextKey=s=>`${s.companyId}:${s.period}:${s.module}`;

export function replacementParties(items,target){return items.filter(r=>r.id!==target?.id&&r.active&&r.kind===target?.kind&&r.identity&&!r.replacement_master_id&&normalizeTaxId(r.tax_id)!==normalizeTaxId(target?.tax_id));}
