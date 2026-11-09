import test from 'node:test';
import assert from 'node:assert/strict';
import {fileName,readFileResponse} from '../src/lib/files.js';

test('nome de arquivo conserva acentos e elimina caminhos',()=>{
  assert.equal(fileName('attachment; filename="relatorio.pdf"'),'relatorio.pdf');
  assert.equal(fileName("attachment; filename*=UTF-8''Apura%C3%A7%C3%A3o.xlsx"),'Apuração.xlsx');
  assert.equal(fileName('attachment; filename="../dados\\arquivo.csv"'),'arquivo.csv');
});
test('recusa falta de permissão, sessão encerrada e erros de relatório sem baixar JSON',async()=>{
  for (const status of [401,403,409,500]) await assert.rejects(readFileResponse(new Response(JSON.stringify({detail:'Confira a operação'}),{status,headers:{'content-type':'application/json'}})),{message:'Confira a operação',status});
  await assert.rejects(readFileResponse(new Response('<html>Erro</html>',{headers:{'content-type':'text/html'}})));
});
test('preserva PDF, arquivos originais JSON anexos e recusa arquivo vazio',async()=>{
  const file=await readFileResponse(new Response('%PDF-content',{headers:{'content-type':'application/pdf','content-disposition':'attachment; filename="teste.pdf"'}}));
  assert.equal(file.name,'teste.pdf');assert.equal(await file.blob.text(),'%PDF-content');
  assert.equal((await readFileResponse(new Response('{}',{headers:{'content-type':'application/json','content-disposition':'attachment; filename="origem.json"'}}))).name,'origem.json');
  await assert.rejects(readFileResponse(new Response('')),{message:/vazio/});
});
