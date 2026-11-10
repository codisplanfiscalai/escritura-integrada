import test from 'node:test';
import assert from 'node:assert/strict';
import {reconcileAccountMappings} from '../src/lib/account-references.js';

test('mapeamento Prosoft acompanha identidade global quando o alias ganha ID operacional',()=>{
 const reviewed={code:'00101',confirmed:true,third_mode:'required',third:'0005'};
 const first=reconcileAccountMappings({'-7':reviewed},{'global:7':-7},[{id:81,shared_entry_id:7,access_code:'00101'}]);
 assert.equal(first.idsChanged,true);assert.equal(first.mappings[81],reviewed);assert.equal(first.mappings[-7],undefined);
 const other=reconcileAccountMappings(first.mappings,first.identities,[{id:-8,shared_entry_id:8,access_code:'00101',prosoft_code:'00101'}]);
 assert.equal(other.mappings[-8].confirmed,false,'outra versão/identidade exige nova revisão mesmo com acesso igual');
});
