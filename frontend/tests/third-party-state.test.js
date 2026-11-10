import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {matchingParties,replacementParties,reusableFields,requestGuard,contextKey} from '../src/lib/third-party-state.js';
test('reutilização filtra CPF/CNPJ completo, não raiz',()=>{
 const target={tax_id:'12.345.678/0001-90'};
 assert.deepEqual(matchingParties([{id:1,tax_id:'12345678000190'},{id:2,tax_id:'12345678000270'}],target).map(r=>r.id),[1]);
 assert.deepEqual(matchingParties([{tax_id:''}],{tax_id:''}),[]);
});
test('campos compartilháveis excluem dados privados e identidade',()=>{
 for(const key of ['email','phone','roles','notes','payment_terms','tax_id','id','company_id']) assert.equal(key in reusableFields,false);
 assert.equal(Object.keys(reusableFields).length,12);
});
test('respostas antigas e painéis encerrados não atualizam estado',()=>{
 const s={companyId:1,period:'2026-01',module:'fiscal'},key=contextKey(s),guard=requestGuard(key,()=>contextKey(s));
 const first=guard.begin(),second=guard.begin();assert.equal(guard.current(first),false);assert.equal(guard.current(second),true);
 guard.invalidate();assert.equal(guard.current(second),false);
 const third=guard.begin();s.period='2026-02';assert.equal(guard.current(third),false);
 s.period='2026-01';guard.dispose();assert.equal(guard.current(guard.begin()),false);
});
test('fluxo exige prévia, motivo, edição e destino capturado',async()=>{
 const s=await readFile(new URL('../src/components/ThirdPartyPanel.vue',import.meta.url),'utf8');
 assert.match(s,/scope\(`\/third-parties\/\$\{props.master.id\}`,context.companyId\)/);
 assert.match(s,/if\(busy.value\|\|!editable.value\|\|contextKey\(state\)!==initialContext\)return/);
 assert.match(s,/if\(!preview.value\|\|registrationsDirty.value\)return/);
 assert.match(s,/\.\.\.clone\(preview.value\),reason:reuseReason.value/);
 assert.match(s,/watch\(\[sourceMaster,fields\],invalidatePreview/);
 assert.match(s,/state.companyId,state.period,state.module/);
 assert.match(s,/:value="null"/);
 assert.match(s,/@click="invalidatePreview"/);
 assert.doesNotMatch(s,/structuredClone/);
});

test('CNPJ alfanumérico preserva letras e distingue raízes e estabelecimentos',()=>{
 assert.deepEqual(matchingParties([{id:1,tax_id:'SYNTH0010001xx'},{id:2,tax_id:'OTHER0010001xx'},{id:3,tax_id:'SYNTH0010002xx'}],{tax_id:'SYNTH0010001XX'}).map(r=>r.id),[1]);
});
test('edições de IEs exigem descarte e bloqueiam reuso; mutação bloqueia fechamento',async()=>{
 const s=await readFile(new URL('../src/components/ThirdPartyPanel.vue',import.meta.url),'utf8');
 assert.match(s,/async function close\(\)\{if\(busy.value\)return/);
 assert.match(s,/registrationsDirty.value&&!await ask/);
 assert.match(s,/:disabled="busy\|\|registrationsDirty"/);
 assert.match(s,/state.companyId,state.period,state.module\],forceClose/);
});

test('substituição exige sucessor local ativo do mesmo tipo, identidade diferente e não substituído',()=>{
 const target={id:10,kind:'participant',tax_id:'SYNTH0010001XX'};
 const good={id:20,kind:'participant',tax_id:'OTHER0010001XX',active:true,identity:{entity_type:'organization'}};
 assert.deepEqual(replacementParties([good,{...good,id:21,active:false},{...good,id:22,kind:'establishment'},{...good,id:23,identity:null},{...good,id:24,replacement_master_id:90},{...good,id:25,tax_id:target.tax_id},{...good,id:10}],target).map(r=>r.id),[20]);
});
test('correção é explícita, confirmada, versionada e protegida pelo contexto',async()=>{
 const s=await readFile(new URL('../src/components/ThirdPartyPanel.vue',import.meta.url),'utf8');
 assert.match(s,/@click="loadReplacements"/);
 assert.match(s,/scope\('\/third-parties',context.companyId\)/);
 assert.match(s,/replacement_master_id:successor.id,version:detail.value.version,reason:correctionReason.value/);
 assert.match(s,/const approved=await ask/);
 assert.match(s,/if\(!correctionGuard.current\(n\)\)return/);
 assert.match(s,/await mutate\('identity-correction','POST',payload/);
 assert.match(s,/correctionGuard.dispose\(\)/);
 assert.match(s,/state.editor=editor/);
});
