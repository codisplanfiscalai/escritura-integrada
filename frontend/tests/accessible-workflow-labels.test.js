import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {parse} from '@vue/compiler-sfc';

test('workflow selects expose stable accessible labels independent of option text',async()=>{
 for(const [file,labels] of [
  ['components/WorkspaceContext.vue',['Empresa','Competência a fixar (opcional)']],
  ['views/AssessmentsView.vue',['Natureza comum','Regra comum']],
 ]){
  const {descriptor}=parse(await readFile(new URL('../src/'+file,import.meta.url),'utf8'));
  for(const label of labels)assert.ok(descriptor.template.content.includes(`<select aria-label="${label}"`),`${file}: ${label}`);
 }
});
