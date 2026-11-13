import test from 'node:test';
import assert from 'node:assert/strict';
import {matchingCompanies,locateCompany} from '../src/lib/company-selection.js';
const companies=[{id:1,code:'001',name:'Ótica'},{id:2,code:'1',name:'Outra'},{id:3,code:'AB20',name:'Alfa'},{id:4,code:'0020',name:'Beta'}];
test('company lookup prefers literal codes and supports padding, partial text and alphanumerics',()=>{
 assert.equal(locateCompany(companies,'001').id,1);assert.equal(locateCompany(companies,'1').id,2);
 assert.equal(locateCompany(companies,'0001'),null);assert.equal(locateCompany(companies,'20').id,4);
 assert.equal(locateCompany(companies,'ab20').id,3);assert.equal(locateCompany(companies,'ótica').id,1);
 assert.deepEqual(matchingCompanies(companies,'20').map(c=>c.id),[4,3]);assert.equal(locateCompany(companies,'missing'),null);
});
