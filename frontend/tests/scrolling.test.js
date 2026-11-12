import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
test('table scrolling chains vertically while sidebar keeps accessible thin scrollbar',async()=>{
 const base=await readFile(new URL('../src/styles/base.css',import.meta.url),'utf8');
 const workspace=await readFile(new URL('../src/styles/workspace.css',import.meta.url),'utf8');
 const app=await readFile(new URL('../src/App.vue',import.meta.url),'utf8');
 const rule=base.match(/\.table-scroll\{([^}]+)\}/)[1];
 assert.match(rule,/overscroll-behavior-y:auto/);assert.match(rule,/overscroll-behavior-x:contain/);
 assert.match(workspace,/scrollbar-width:thin/);assert.match(workspace,/forced-colors:active/);
 assert.match(app,/<nav aria-label="Navegação principal" tabindex="0">/);
});
