import test from 'node:test';
import assert from 'node:assert/strict';
import {accountOptions} from '../src/lib/account-options.js';

test('22596 contas permanecem pesquisáveis sem renderizar milhares de opções',()=>{
 const accounts=Array.from({length:22596},(_,i)=>({id:-(i+1),shared_entry_id:i+1,access_code:String(10000+i),classifier:'1.1.01.001',name:`Conta sintética ${i}`}));
 const first=accountOptions(accounts,'','');assert.equal(first.total,22596);assert.equal(first.rows.length,200);
 const last=accountOptions(accounts,'32595','');assert.equal(last.rows.length,1);assert.equal(last.rows[0].id,-22596);
 const selected=accountOptions(accounts,'32594',-22596);assert.equal(selected.rows.length,2);assert.equal(selected.rows.at(-1).id,-22596);
 const allocated=accountOptions([{...accounts.at(-1),id:91}],'',-22596);assert.equal(allocated.rows[0].id,-22596,'formulário aberto conserva alias e seleção após materialização');
});

test('Home e ArrowDown conservam a ordem nativa enquanto cada seleção atualiza o modelo',()=>{
 const accounts=Array.from({length:6},(_,i)=>({id:i+1,access_code:String(i+1),name:`Conta ${i+1}`,classifier:`1.${i+1}`}));
 for(const selected of ['',1,2,3,4,5,6])assert.deepEqual(accountOptions(accounts,'',selected).rows.map(a=>a.id),[1,2,3,4,5,6]);
 let selected='';
 // Empty native option is index zero. Each arrow fires change before the next
 // arrow, as in browser_evolution.py's unchanged Home/ArrowDown/Tab test.
 for(let index=1;index<=3;index++)selected=accountOptions(accounts,'',selected).rows[index-1].id;
 assert.equal(selected,3);
 const many=Array.from({length:500},(_,i)=>({...accounts[0],id:i+1,access_code:String(i+1)}));
 const window=accountOptions(many,'',500).rows;
 assert.deepEqual(window.slice(0,200).map(a=>a.id),Array.from({length:200},(_,i)=>i+1));
 assert.equal(window.at(-1).id,500);assert.equal(window.length,201);
});

test('AccountSelect compila com vModelSelect para sincronizar a seleção após atualizar options',async()=>{
 const {readFile}=await import('node:fs/promises');
 const {parse,compileScript,compileTemplate}=await import('@vue/compiler-sfc');
 const filename=new URL('../src/components/AccountSelect.vue',import.meta.url);
 const {descriptor}=parse(await readFile(filename,'utf8'));
 const script=compileScript(descriptor,{id:'account-select-keyboard'});
 const compiled=compileTemplate({source:descriptor.template.content,filename:filename.pathname,id:'account-select-keyboard',compilerOptions:{bindingMetadata:script.bindings}});
 assert.deepEqual(compiled.errors,[]);assert.match(compiled.code,/vModelSelect/);
 assert.match(script.content,/selectedValue=computed/);
});
