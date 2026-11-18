import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../src/views/ReportsView.vue',import.meta.url),'utf8');
test('trial balance defaults to movement independently of account selection and preserves balances visibly',()=>{
 assert.match(source,/activity=ref\('active'\)/);
 assert.match(source,/activity:kind.value==='trial-balance'\?activity.value:'active'/);
 assert.match(source,/value="active">Com movimento/);
 assert.match(source,/value="all">Todas as contas/);
 assert.match(source,/Inclui contas com saldo anterior ou final, mesmo sem movimento no período/);
 assert.match(source,/activity.value='active'/);
 assert.match(source,/synthetic-account/);
});
