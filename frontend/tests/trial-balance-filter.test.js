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
test('account union is explicit and retained independently of movement',()=>{
 assert.match(source,/account=ref\(\[\]\)/);
 assert.match(source,/p.set\('account_ids',account.value.join\(','\)\)/);
 assert.match(source,/AccountMultiSelect v-model="account"/);
 const component=readFileSync(new URL('../src/components/AccountMultiSelect.vue',import.meta.url),'utf8');
 assert.match(component,/new Set\(props.modelValue\)/);
 assert.match(component,/@keydown.esc="close"/);
 assert.match(component,/type="checkbox"/);
 assert.match(component,/As seleções anteriores são mantidas/);
 assert.match(component,/role="group" aria-label="Contas do relatório"/);
});
