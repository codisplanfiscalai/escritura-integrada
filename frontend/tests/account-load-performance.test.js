import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createRenderer,createSSRApp,reactive,ref,nextTick,h,KeepAlive} from 'vue';
import {renderToString} from '@vue/server-renderer';

const require=createRequire(import.meta.url);
const vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
const dataUrl=code=>`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`;
const libUrl=name=>new URL(`../src/lib/${name.replace(/\.js$/,'')}.js`,import.meta.url).href;
const flush=async()=>{await nextTick();await new Promise(resolve=>setTimeout(resolve,5));await nextTick();};
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let serial=0;

async function harness(file,props={},options={}){
 const key=`__accountLoad${++serial}`,requests=[];
 const state=reactive({companyId:1,period:'2026-11',module:props.area||'accounting',refresh:0,contextBusy:false,editor:null,contextPreferences:{month:''}});
 const company=ref({id:1,code:'SYN',name:'Empresa sintética'});
 const api=(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}));
 const can=routine=>!options.denied?.includes(routine);
 globalThis[key]={state,company,api,can,scope:(url,id=state.companyId)=>`/companies/${id}${url}`,rows:value=>Array.isArray(value)?value:value?.items||[],changed:()=>state.refresh++,notify:()=>{},ask:async()=>true,writable:()=>true,initialize:options.render||(()=>{})};
 // Use the real composable, rather than a fake that would hide its lifecycle/race behavior.
 const workspace=await readFile(new URL('../src/lib/workspace.js',import.meta.url),'utf8');
 const resource=workspace.slice(workspace.indexOf('export function useResource('),workspace.indexOf("if (typeof window !== 'undefined')"));
 const mock=dataUrl(`import {ref,watch,onActivated,onDeactivated,onUnmounted} from '${vueUrl}';\nexport const {state,company,api,can,scope,rows,changed,notify,ask,writable}=globalThis.${key};\nexport const allowedApi=(routine,path,empty=[])=>can(routine)?api(path):Promise.resolve(empty);\n${resource}`);
 let source=await readFile(new URL(`../src/views/${file}.vue`,import.meta.url),'utf8');
 if(options.render)source=source.replace('</script>',`globalThis.${key}.initialize({data,loading,page,pageSize,selectedIds,section});\n</script>`);
 const {descriptor}=parse(source);
 const code=compileScript(descriptor,{id:key,inlineTemplate:Boolean(options.render)}).content
  .replace(/from ['"]vue['"]/g,`from '${vueUrl}'`)
  .replace(/import (\w+) from ['"][^'"]+\.vue['"];?/g,'const $1={render:()=>null};')
  .replace(/from ['"]\.\.\/lib\/([^'"]+)['"]/g,(_,name)=>`from '${name==='workspace'?mock:libUrl(name)}'`);
 const component=(await import(dataUrl(code))).default;
 if(options.render){
  try{const app=createSSRApp(component,props);app.directive('allow',{getSSRProps:()=>({})});return await renderToString(app);}
  finally{delete globalThis[key];}
 }
 let view;const setup=component.setup;component.setup=(props,context)=>{view=setup(props,context);return()=>null;};
 const shown=ref(true),root=options.keepAlive?{setup:()=>()=>h(KeepAlive,null,{default:()=>shown.value?h(component,props):null})}:component;
 const app=createRenderer({createElement:()=>({}),createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null}).createApp(root,options.keepAlive?{}:props);
 app.mount({});await flush();
 let closed=false;
 return {view,state,requests,shown,close:()=>{if(!closed){closed=true;app.unmount();delete globalThis[key];}}};
}
const pageResult=(ids,total=ids.length)=>({items:ids.map(id=>({id,access_code:String(id),name:`Conta ${id}`,analytical:true})),total,page:1,per_page:50});
const params=request=>new URL(request.url,'https://fixture.invalid').searchParams;

test('plano de contas consulta somente página de contas, preserva linhas recebidas e usa total do servidor',async()=>{
 const h=await harness('JournalView',{initialSection:'accounts'}),v=h.view;
 try{
  assert.equal(h.requests.length,1);assert.equal(h.requests[0].url,'/companies/1/accounts?page=1&per_page=50&search=');
  h.requests[0].resolve(pageResult([1,2],120));await flush();assert.equal(v.total.value,120);assert.equal(v.pageCount.value,3);assert.deepEqual(v.visible.value.map(x=>x.id),[1,2]);
  v.page.value=2;await flush();assert.equal(h.requests.length,2);assert.equal(params(h.requests[1]).get('page'),'2');
  h.requests[1].resolve(pageResult([51,52],120));await flush();assert.deepEqual(v.visible.value.map(x=>x.id),[51,52],'server page must not be sliced again');
  v.pageSize.value=5000;await flush();assert.equal(h.requests.length,3);assert.equal(params(h.requests[2]).get('page'),'1');assert.equal(params(h.requests[2]).get('per_page'),'5000');
  h.requests[2].resolve(pageResult([1,2],120));await flush();assert.equal(v.pageCount.value,1);
 }finally{h.close();}
});

test('busca de contas normaliza e agrupa digitação em 180 ms sem carregar catálogos',async()=>{
 const h=await harness('JournalView',{initialSection:'accounts'}),v=h.view;
 try{
  h.requests[0].resolve(pageResult([1],400));await flush();v.page.value=3;await flush();h.requests[1].resolve(pageResult([101],400));await flush();
  v.q.value='Á';await nextTick();await wait(90);v.q.value='  ÁTIVO  ';await nextTick();await wait(120);
  assert.equal(h.requests.length,2,'latest input has not reached its debounce deadline');
  await wait(90);await flush();assert.equal(h.requests.length,3);assert.equal(params(h.requests[2]).get('search'),'ativo');assert.equal(params(h.requests[2]).get('page'),'1');
  h.requests[2].resolve(pageResult([9],1));await flush();assert.deepEqual(v.visible.value.map(x=>x.id),[9],'server results are not re-filtered with raw input');
  v.q.value='Ativo';await nextTick();await wait(200);assert.equal(h.requests.length,3,'equivalent normalized search does not reload');
 }finally{h.close();}
});

test('respostas antigas não vencem página, filtro ou empresa mais recentes; exclusão limita página',async()=>{
 const h=await harness('JournalView',{initialSection:'accounts'}),v=h.view;
 try{
  h.requests[0].resolve(pageResult([1],120));await flush();v.page.value=3;await flush();const old=h.requests.at(-1);
  v.page.value=2;await flush();h.requests.at(-1).resolve(pageResult([51],51));await flush();old.resolve(pageResult([101],120));await flush();assert.deepEqual(v.visible.value.map(x=>x.id),[51]);assert.equal(v.total.value,51);
  h.state.refresh++;await flush();h.requests.at(-1).resolve(pageResult([],50));await flush();assert.equal(v.page.value,1);assert.equal(params(h.requests.at(-1)).get('page'),'1');h.requests.at(-1).resolve(pageResult([1],50));await flush();
  v.page.value=2;await flush();const previousCompany=h.requests.at(-1);h.state.companyId=2;await flush();const current=h.requests.at(-1);assert.match(current.url,/^\/companies\/2\/accounts\?/);
  current.resolve(pageResult([200],1));await flush();previousCompany.resolve(pageResult([50],100));await flush();assert.deepEqual(v.visible.value.map(x=>x.id),[200]);
  v.q.value='passivo';await nextTick();await wait(200);const oldSearch=h.requests.at(-1);v.q.value='ativo';await nextTick();await wait(200);const newSearch=h.requests.at(-1);
  newSearch.resolve(pageResult([300],1));await flush();oldSearch.resolve(pageResult([400],1));await flush();assert.deepEqual(v.visible.value.map(x=>x.id),[300]);
 }finally{h.close();}
});

test('edição de conta mantém contexto e página; seleção contábil mantém proteção de operação em lote',async()=>{
 const h=await harness('JournalView',{initialSection:'accounts'}),v=h.view;
 try{
  h.requests[0].resolve(pageResult([1],100));await flush();v.page.value=2;await flush();h.requests[1].resolve(pageResult([51],100));await flush();
  v.open('account',v.visible.value[0]);v.form.value.name='Conta editada';const saving=v.save(),request=h.requests.at(-1);
  assert.equal(request.url,'/companies/1/accounts/51');assert.equal(request.options.method,'PUT');assert.equal(request.options.body.name,'Conta editada');request.resolve({});await saving;await flush();
  assert.equal(v.show.value,false);assert.equal(h.state.editor,null);assert.equal(v.page.value,2);assert.equal(params(h.requests.at(-1)).get('page'),'2');
  h.requests.at(-1).resolve(pageResult([51],100));await flush();v.open('account');assert.equal(v.form.value.id,undefined);assert.equal(v.form.value.analytical,true);
  v.toggleSelection(1,true);v.toggleSelection(1,true);assert.deepEqual(v.selectedIds.value,[1]);v.bulkBusy.value=true;v.toggleSelection(1,false);assert.deepEqual(v.selectedIds.value,[1]);v.bulkBusy.value=false;v.toggleSelection(1,false);assert.deepEqual(v.selectedIds.value,[]);
 }finally{h.close();}
});

test('centros não buscam contas/lançamentos; lançamentos mantêm catálogos completos para editar',async()=>{
 const centers=await harness('JournalView',{initialSection:'cost-centers'});
 try{assert.deepEqual(centers.requests.map(x=>x.url),['/companies/1/cost-centers']);centers.requests[0].resolve([{id:1,name:'Administração'}]);await flush();assert.equal(centers.view.visible.value.length,1);}finally{centers.close();}
 const journals=await harness('JournalView',{initialSection:'journals'});
 try{
  assert.deepEqual(journals.requests.map(x=>x.url),['/companies/1/journals?year=2026','/companies/1/accounts','/companies/1/cost-centers','/companies/1/masters/history','/companies/1/accounting-entry-defaults']);
  journals.requests.forEach((r,i)=>r.resolve(i===0?Array.from({length:60},(_,j)=>({id:j+1,history:'Teste'})):[{id:i,name:'Sintético'}]));await flush();
  assert.equal(journals.view.visible.value.length,50);journals.view.page.value=2;await flush();assert.equal(journals.requests.length,5);assert.equal(journals.view.visible.value.length,10);assert.equal(journals.view.data.value.accounts[0].id,1);
 }finally{journals.close();}
});

test('cadastros fiscais e históricos não leem contas; modelos contábeis mantêm listas completas',async()=>{
 const fiscal=await harness('MastersView',{area:'fiscal'});
 try{
  assert.deepEqual(fiscal.requests.map(x=>x.url),['/companies/1/masters/participant']);fiscal.requests[0].resolve([]);await flush();
  fiscal.view.kind.value='product';await flush();assert.equal(fiscal.requests.at(-1).url,'/companies/1/masters/product');assert.equal(fiscal.requests.length,2);
 }finally{fiscal.close();}
 const accounting=await harness('MastersView',{area:'accounting'});
 try{
  assert.deepEqual(accounting.requests.map(x=>x.url),['/companies/1/masters/history']);accounting.requests[0].resolve([]);await flush();
  accounting.view.kind.value='accounting_model';await flush();assert.deepEqual(accounting.requests.slice(1).map(x=>x.url),['/companies/1/masters/accounting_model','/companies/1/accounts','/companies/1/cost-centers']);
  accounting.requests.slice(1).forEach((r,i)=>r.resolve([{id:i+1}]));await flush();assert.equal(accounting.view.data.value.accounts[0].id,2);
  accounting.view.kind.value='history';await flush();assert.equal(accounting.requests.length,5);accounting.requests[4].resolve([]);await flush();assert.deepEqual(accounting.view.data.value.accounts,[]);
 }finally{accounting.close();}
});

test('relatórios fiscais e financeiros não leem catálogos contábeis; relatórios contábeis continuam completos',async()=>{
 for(const area of ['fiscal','financial','accounting']){
  const h=await harness('ReportsView',{area});
  try{
   assert.deepEqual(h.requests.map(x=>x.url),[`/companies/1/report-models?module=${area}`,...(area==='accounting'?['/companies/1/accounts','/companies/1/cost-centers']:[])]);
   h.requests.forEach(r=>r.resolve([]));await flush();assert.deepEqual(h.view.data.value,{accounts:[],centers:[]});
  }finally{h.close();}
 }
});

test('permissão negada de contas mantém paginação vazia sem consultar endpoint',async()=>{
 const h=await harness('JournalView',{initialSection:'accounts'},{denied:['accounting.accounts']});
 try{assert.equal(h.requests.length,0);assert.equal(h.view.total.value,0);assert.equal(h.view.pageCount.value,1);assert.deepEqual(h.view.visible.value,[]);}finally{h.close();}
});

test('KeepAlive cancela busca pendente e retoma o filtro atual sem consultar enquanto oculto',async()=>{
 const h=await harness('JournalView',{initialSection:'accounts'},{keepAlive:true}),v=h.view;
 try{
  h.requests[0].resolve(pageResult([1],100));await flush();v.q.value='Átivo';await nextTick();h.shown.value=false;await flush();await wait(200);assert.equal(h.requests.length,1);
  h.state.refresh++;await flush();assert.equal(h.requests.length,1);h.shown.value=true;await flush();
  assert.equal(params(h.requests.at(-1)).get('search'),'ativo');h.requests.at(-1).resolve(pageResult([2],1));await flush();assert.deepEqual(v.visible.value.map(x=>x.id),[2]);
 }finally{h.close();}
});

test('template preserva pesquisa acessível, total e opções de 50 a 5000; botões respeitam limites',async()=>{
 const render=({data,loading,page,pageSize})=>{data.value={journals:[],accounts:pageResult([51]).items,centers:[],histories:[],accountTotal:101};loading.value=false;page.value=2;pageSize.value=50;};
 const html=await harness('JournalView',{initialSection:'accounts'},{render});
 assert.match(html,/aria-label="Pesquisar contabilidade"/);assert.match(html,/aria-label="Registros por página"/);assert.match(html,/101 registros/);assert.match(html,/Página 2 de 3/);assert.match(html,/Conta 51/);
 for(const size of [50,100,250,500,1000,2500,5000])assert.match(html,new RegExp(`<option value="${size}"`));
 for(const label of ['Anterior','Próxima'])assert.doesNotMatch(html,new RegExp(`<button[^>]*disabled[^>]*>${label}</button>`));
 const edge=await harness('JournalView',{initialSection:'accounts'},{render:v=>{render(v);v.page.value=1;v.data.value.accountTotal=1;}});
 for(const label of ['Anterior','Próxima'])assert.match(edge,new RegExp(`<button[^>]*disabled[^>]*>${label}</button>`));
});

test('formatadores monetário e numérico reutilizam Intl.NumberFormat sem alterar saída',async()=>{
 const original=Intl.NumberFormat;let calls=0;
 Intl.NumberFormat=function(...args){calls++;return new original(...args);};
 try{
  const {money,number}=await import(`${libUrl('format')}?formatter-reuse=${serial++}`);assert.equal(calls,2);
  for(let i=0;i<500;i++){assert.equal(money(123456),new original('pt-BR',{style:'currency',currency:'BRL'}).format(1234.56));assert.equal(number(1234),new original('pt-BR').format(1234));}
  assert.equal(calls,2);assert.equal(money(null),money(0));assert.equal(number(),new original('pt-BR').format(0));
 }finally{Intl.NumberFormat=original;}
});


test('novo lançamento aguarda defaults e sugere valores sem substituir edição',async()=>{
 const h=await harness('JournalView',{initialSection:'journals'});
 try{
  h.view.open('journal');assert.equal(h.view.show.value,false);
  h.requests.forEach((r,i)=>r.resolve(i===4?{settings:{default_history:'Padrão da empresa',default_cost_center_id:7}}:i===2?[{id:7,name:'Centro'}]:[]));await flush();
  h.view.open('journal');assert.equal(h.view.form.value.history,'Padrão da empresa');assert.equal(h.view.form.value.lines[0].cost_center_id,7);
  h.view.form.value.history='Edição manual';assert.equal(h.view.data.value.defaults.default_history,'Padrão da empresa');
 }finally{h.close();}
});


test('salvar e novo cria outra chave mesmo se refresh estiver carregando',async()=>{
 const previousDocument=globalThis.document;globalThis.document={getElementById:()=>null};
 const h=await harness('JournalView',{initialSection:'journals'});
 try{
  h.requests.forEach((r,i)=>r.resolve(i===4?{settings:{default_history:'Padrão',default_cost_center_id:null}}:[]));await flush();
  h.view.open('journal');const old=h.view.form.value.idempotency_key;h.view.form.value.history='Manual';h.view.saveNext.value=true;
  const saving=h.view.save(),write=h.requests.at(-1);h.state.refresh++;await flush();assert.equal(h.view.loading.value,true);
  write.resolve({});await saving;assert.notEqual(h.view.form.value.idempotency_key,old);assert.equal(h.view.show.value,true);
 }finally{h.close();if(previousDocument===undefined)delete globalThis.document;else globalThis.document=previousDocument;}
});


test('subconta própria sugere hierarquia sem reutilizar identidade do pai',async()=>{
 const h=await harness('JournalView',{initialSection:'accounts'});try{
 h.requests[0].resolve(pageResult([1]));await flush();h.view.open('account',null,false,{id:99,access_code:'100',classifier:'1.1',nature:'debit',requires_cost_center:true,report_group:'asset'});
 assert.equal(h.view.form.value.access_code,'');assert.equal(h.view.form.value.classifier,'1.1.');assert.equal(h.view.form.value.analytical,true);assert.equal(h.view.form.value.id,undefined);assert.equal(h.view.form.value.requires_cost_center,true);
 }finally{h.close();}
});
