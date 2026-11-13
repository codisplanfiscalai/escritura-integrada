import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createRenderer,reactive,ref,nextTick} from 'vue';

async function mount(name,mock,props={}){
 globalThis.__masterEvidenceTest=mock;
 const mockUrl=`data:text/javascript;base64,${Buffer.from('export const {state,company,api,scope,useResource,notify,changed,ask,can,allowedApi,writable}=globalThis.__masterEvidenceTest; // '+name).toString('base64')}`;
 const source=await readFile(new URL(`../src/${name}.vue`,import.meta.url),'utf8');
 const {descriptor}=parse(source),require=createRequire(import.meta.url),vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
 let code=compileScript(descriptor,{id:`master-evidence-${name}`}).content.replace(/from ['"]vue['"]/g,`from '${vueUrl}'`).replace(/import (\w+) from ['"][^'"]+\.vue['"];?/g,'const $1={};').replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mockUrl}'`).replace(/from ['"]\.\.\/lib\/format['"]/g,`from '${new URL('../src/lib/format.js',import.meta.url).href}'`);
 const component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;
 let view;const setup=component.setup;component.setup=(props,ctx)=>{view=setup(props,ctx);return ()=>null;};
 const app=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null}).createApp(component,props);app.mount({});
 return {view,unmount:()=>app.unmount()};
}
const flush=async()=>{await nextTick();await new Promise(resolve=>setTimeout(resolve,0));};

test('source consultations ignore obsolete page, company and closed modal responses',async()=>{
 const requests=[],state=reactive({companyId:1,period:'2026-11',module:'fiscal'});
 const mock={state,can:()=>true,scope:(path,id)=>`/companies/${id}${path}`,api:(url)=>new Promise((resolve,reject)=>requests.push({url,resolve,reject}))};
 const {view,unmount}=await mount('components/MasterEvidence',mock,{master:{id:10,kind:'product'},companyId:1});
 try{
  assert.match(requests[0].url,/masters\/product\/10\/evidence\?offset=0/);
  view.offset.value=25;await flush();assert.equal(requests.length,2);
  requests[1].resolve({items:[{id:'new'}],total:30});await flush();
  requests[0].resolve({items:[{id:'old'}],total:1});await flush();assert.deepEqual(view.rows.value,[{id:'new'}]);assert.equal(view.total.value,30);
  const read=view.readXml({id:81});state.companyId=2;requests.at(-1).resolve({available:true,document:{secret:'old company'}});await read;assert.deepEqual(view.details.value,{});
  state.companyId=1;const closed=view.readXml({id:82});unmount();requests.at(-1).resolve({available:true,document:{id:82}});await closed;assert.deepEqual(view.details.value,{});
 }finally{unmount();delete globalThis.__masterEvidenceTest;}
});

test('master editing leaves unknown price absent and adds an IE only once with unknown activity',async()=>{
 const requests=[],state=reactive({companyId:1,period:'2026-11',module:'fiscal'});
 const mock={state,company:ref({name:'Empresa sintética'}),api:async(url,options)=>{requests.push({url,options});return {};},scope:(url,id=1)=>`/companies/${id}${url}`,useResource:()=>({data:ref({items:[],accounts:[],centers:[]}),error:ref(''),reload:()=>{}}),notify:()=>{},changed:()=>{},ask:async()=>true,can:()=>true,allowedApi:()=>{},writable:()=>true};
 const {view,unmount}=await mount('views/MastersView',mock,{area:'fiscal'});
 try{
  view.kind.value='product';view.open({id:2,kind:'product',code:'P2',name:'Produto',version:1,data:{unit:'UN',import_identity:{issuer:'123',code:'SKU'}}});
  assert.equal(view.form.value.price,'');await view.save();assert.equal(Object.hasOwn(requests.at(-1).options.body.data,'price'),false);assert.equal(requests.at(-1).options.body.data.import_identity.code,'SKU');
  view.kind.value='participant';view.open({id:3,kind:'participant',code:'T3',name:'Terceiro',version:1,data:{ie:'001234',state:'SP'}});view.addPrincipalIe();view.addPrincipalIe();
  assert.equal(view.form.value.profile.state_registrations.length,1);assert.equal(view.form.value.profile.state_registrations[0].active,null);assert.equal(view.form.value.profile.state_registrations[0].number,'001234');
 }finally{unmount();delete globalThis.__masterEvidenceTest;}
});
