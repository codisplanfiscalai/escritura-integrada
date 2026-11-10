import test from 'node:test';
import assert from 'node:assert/strict';
import {accountOptions} from '../src/lib/account-options.js';

test('22596 contas permanecem pesquisáveis sem renderizar milhares de opções',()=>{
 const accounts=Array.from({length:22596},(_,i)=>({id:-(i+1),shared_entry_id:i+1,access_code:String(10000+i),classifier:'1.1.01.001',name:`Conta sintética ${i}`}));
 const first=accountOptions(accounts,'','');assert.equal(first.total,22596);assert.equal(first.rows.length,200);
 const last=accountOptions(accounts,'32595','');assert.equal(last.rows.length,1);assert.equal(last.rows[0].id,-22596);
 const selected=accountOptions(accounts,'32594',-22596);assert.equal(selected.rows.length,2);assert.equal(selected.rows[0].id,-22596);
 const allocated=accountOptions([{...accounts.at(-1),id:91}],'',-22596);assert.equal(allocated.rows[0].id,-22596,'formulário aberto conserva alias e seleção após materialização');
});
