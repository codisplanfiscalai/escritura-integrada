import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {parse,compileScript} from '@vue/compiler-sfc';
import {createRenderer,reactive,nextTick} from 'vue';
const require=createRequire(import.meta.url),vueUrl=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
const tick=async()=>{await nextTick();await nextTick();};
const row=(overrides={})=>({version:0,enabled:false,interval_minutes:1440,status:'disabled',next_run_at:null,last_success_at:null,pages:0,downloaded:0,...overrides});
let setupId=0;
async function setup(){
 const id=++setupId;
 const calls=[],pending=[];
 globalThis["__automationTest"+id]={api:(url,options={})=>{calls.push({url,options});return new Promise((resolve,reject)=>pending.push({resolve,reject}));},notify:()=>{},changed:()=>{}};
 const mock=`data:text/javascript;base64,${Buffer.from('export const {api,notify,changed}=globalThis.__automationTest'+id+';').toString('base64')}`;
 const receptionUrl=new URL('../src/lib/reception.js',import.meta.url).href;
 const source=await readFile(new URL('../src/components/ReceptionAutomationSettings.vue',import.meta.url),'utf8');
 const code=compileScript(parse(source).descriptor,{id:'automation-test'}).content.replace(/from ['"]vue['"]/g,`from '${vueUrl}'`).replace(/from ['"]\.\.\/lib\/workspace['"]/g,`from '${mock}'`).replace(/from ['"]\.\.\/lib\/reception.js['"]/g,`from '${receptionUrl}'`);
 const component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;
 let v;const original=component.setup;component.setup=(props,context)=>{v=original(props,context);return()=>null;};
 const props=reactive({companyId:1,disabled:false});
 const renderer=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null});
 const app=renderer.createApp(component,props);app.mount({});
 return {get v(){return v;},props:app._instance.props,calls,pending,close:()=>app.unmount()};
}
test('independent services default to 24h and save only the selected service',async()=>{
 const f=await setup();try{
  assert.equal(f.calls[0].url,'/companies/1/reception-automation');
  f.pending.shift().resolve({can_edit:true,services:{nfe_distribution:row(),nfse_adn:row()}});await tick();
  assert.equal(f.v.forms.value.nfse_adn.interval_minutes,1440);
  assert.equal(f.v.units.value.nfse_adn,60);assert.equal(f.v.forms.value.nfse_adn.interval_minutes/f.v.units.value.nfse_adn,24);
  f.v.units.value.nfse_adn=1440;assert.equal(f.v.dirty.value,false);
  f.v.forms.value.nfse_adn.enabled=true;f.v.forms.value.nfse_adn.interval_minutes=2880;
  assert.equal(f.v.dirty.value,true);
  const saving=f.v.save('nfse_adn');assert.equal(f.calls.at(-1).url,'/companies/1/reception-automation/nfse_adn');
  assert.deepEqual(f.calls.at(-1).options.body,{version:0,enabled:true,interval_minutes:2880});
  f.pending.shift().resolve(row({version:1,enabled:true,interval_minutes:2880,status:'pending'}));await saving;
  assert.equal(f.v.dirty.value,false);assert.equal(f.v.forms.value.nfe_distribution.enabled,false);
 }finally{f.close();}
});
test('stale company response is discarded and read-only settings cannot dispatch',async()=>{
 const f=await setup();try{
  const old=f.pending.shift();f.props.companyId=2;await tick();
  old.resolve({can_edit:true,services:{nfse_adn:row({enabled:true})}});await tick();assert.equal(f.v.data.value,null);
  f.pending.shift().resolve({can_edit:false,services:{nfse_adn:row()}});await tick();
  f.v.forms.value.nfse_adn.enabled=true;await f.v.save('nfse_adn');assert.equal(f.calls.length,2);
 }finally{f.close();}
});
