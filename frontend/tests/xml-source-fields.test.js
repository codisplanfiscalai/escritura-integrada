import test from 'node:test';
import assert from 'node:assert/strict';
import { sourceRows, sourceLabel } from '../src/lib/xml-source-fields.js';

test('backend leaves without children retain tag path and lexical precision', () => {
  assert.deepEqual(sourceRows({ tag: 'prod', children: [
    { tag: 'cProd', text: '00007' }, { tag: 'vProd', text: '0.00' },
    { tag: 'qCom', text: '1.0000' }
  ] }), [
    { path: 'prod/cProd', value: '00007' },
    { path: 'prod/vProd', value: '0.00' },
    { path: 'prod/qCom', value: '1.0000' }
  ]);
});

test('explicit empty leaves and repeated empty tags remain visible', () => {
  assert.deepEqual(sourceRows({ tag: 'infAdic', children: [
    { tag: 'infCpl' }, { tag: 'infCpl', text: '' },
    { tag: 'obsCont', attributes: { xCampo: 'A' }, children: [] }
  ] }), [
    { path: 'infAdic/infCpl[1]', value: '' },
    { path: 'infAdic/infCpl[2]', value: '' },
    { path: 'infAdic/obsCont/@xCampo', value: 'A' },
    { path: 'infAdic/obsCont', value: '' }
  ]);
  assert.deepEqual(sourceRows({ tag: 'infCpl' }), [{ path: 'infCpl', value: '' }]);
});

test('repeated item groups retain attributes and tax paths without mutation', () => {
  const source = { tag: 'infNFe', children: [1, 2].map(n => ({ tag: 'det', attributes: { nItem: String(n) }, children: [
    { tag: 'IBSCBS', children: [{ tag: 'pCBS', text: '0.9000' }] }
  ] })) };
  const before = JSON.stringify(source), rows = sourceRows(source);
  assert.deepEqual(rows, [
    { path: 'infNFe/det[1]/@nItem', value: '1' },
    { path: 'infNFe/det[1]/IBSCBS/pCBS', value: '0.9000' },
    { path: 'infNFe/det[2]/@nItem', value: '2' },
    { path: 'infNFe/det[2]/IBSCBS/pCBS', value: '0.9000' }
  ]);
  assert.equal(JSON.stringify(source), before);
  assert.equal(sourceLabel(rows[1].path), 'Alíquota CBS');
});

test('ordinary objects and arrays preserve zero, false, blank and repeated fields', () => {
  assert.deepEqual(sourceRows({ a: [0, false, ''], tax: { vBC: '100.00' } }), [
    { path: 'a[1]', value: '0' }, { path: 'a[2]', value: 'false' },
    { path: 'a[3]', value: '' }, { path: 'tax/vBC', value: '100.00' }
  ]);
  assert.deepEqual(sourceRows(null), []);
  assert.deepEqual(sourceRows(undefined), []);
});
