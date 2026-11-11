import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
test('mês fechado só impede edição quando a empresa ativa essa regra; permissões continuam obrigatórias',async()=>{
 const require=createRequire(import.meta.url),vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
 let code=await readFile(new URL('../src/lib/workspace.js',import.meta.url),'utf8');code=code.replace(/from 'vue'/g,`from '${vueUrl}'`).replace("from './format'",`from '${new URL('../src/lib/format.js',import.meta.url).href}'`).replace("from './context-preferences.js'",`from '${new URL('../src/lib/context-preferences.js',import.meta.url).href}'`);
 const {state,writable,activate}=await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
 state.session={user:{role:'admin'},operational_settings:{enforce_period_locks:false}};state.yearLocks={fiscal:{'2026-11':{closed:true}}};
 assert.equal(writable('fiscal.documents','edit','2026-11'),true);
 state.session.operational_settings.enforce_period_locks=true;assert.equal(writable('fiscal.documents','edit','2026-11'),false);assert.equal(writable('fiscal.documents','edit','2026-10'),true);
 state.session={user:{role:'viewer'},permissions:{'fiscal.documents':['read']},operational_settings:{enforce_period_locks:false}};assert.equal(writable('fiscal.documents','edit','2026-11'),false);
 state.session.permissions['fiscal.documents'].push('edit');assert.equal(writable('fiscal.documents','edit','2026-11'),true);
 const originalFetch=globalThis.fetch;
 try{
  state.session={user:{role:'admin'},operational_settings:{enforce_period_locks:false}};state.period='2026-11';state.companyId=1;
  globalThis.fetch=async (url,options)=>({ok:true,status:200,json:async()=>url==='/api/context'?{active_company_id:JSON.parse(options.body).company_id,period:'2026-11',module:'fiscal',operational_settings:{enforce_period_locks:JSON.parse(options.body).company_id===2}}:url.includes('/exercises?')?{months:[{period:'2026-11',closed:true}]}:{}});
  await activate(2);assert.equal(state.companyId,2);assert.equal(writable('fiscal.documents','edit','2026-11'),false);
  await activate(1);assert.equal(state.companyId,1);assert.equal(writable('fiscal.documents','edit','2026-11'),true);
 }finally{globalThis.fetch=originalFetch;}

});
