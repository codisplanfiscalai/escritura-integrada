import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {computed,ref,reactive} from 'vue';
const job={id:'a'.repeat(32),state:'prepared',installed:{version:'0.9.0-dev.1'},target:{version:'0.9.0-dev.2',digest:'sha256:'+'b'.repeat(64)},channel:'develop'};
async function harness(answer=true){
 const source=await readFile(new URL('../src/components/DockerCutoverPanel.vue',import.meta.url),'utf8');
 const code=source.split('<script setup>')[1].split('</script>')[0].replace(/^import .*;\n/gm,'').replace("const props=defineProps({status:Object,disabled:Boolean});",'').replace("const emit=defineEmits(['changed']);",'');
 const props=reactive({status:{cutover_supported:true,cutovers:[],jobs:[job]},disabled:false}),calls=[],prompts=[];
 let fail=true;
 const api=async(path,options)=>{calls.push([path,options]);if(fail)throw Error('Resposta perdida');return {};};
 const ask=async prompt=>{prompts.push(prompt);return typeof answer==='function'?answer():answer;};
 const h=new Function('computed','ref','props','emit','api','ask','uid',code+';return {update,recover,busy,error};')(computed,ref,props,()=>{},api,ask,()=> 'c'.repeat(32));
 return {...h,props,calls,prompts,succeed:()=>{fail=false;}};
}
test('corte cancelado, host desabilitado e recuperação pendente não enviam mutação',async()=>{
 const h=await harness(false);await h.update();assert.equal(h.calls.length,0);assert.match(h.prompts[0].message,/janela exclusiva/);
 h.props.status.cutover_supported=false;await h.update();assert.equal(h.prompts.length,1);
 h.props.status.cutover_supported=true;h.props.status.cutovers=[{state:'recovery_required'}];await h.update();assert.equal(h.calls.length,0);
});
test('cliques durante confirmação são únicos; retry conserva intenção e só envia IDs',async()=>{
 let resolve;const h=await harness(()=>new Promise(yes=>{resolve=yes;}));
 const first=h.update();await h.update();assert.equal(h.prompts.length,1);resolve(true);await first;
 assert.match(h.error.value,/perdida/);assert.equal(h.calls.length,1);
 const again=h.update();resolve(true);await again;
 assert.deepEqual(h.calls[0],h.calls[1]);assert.deepEqual(Object.keys(h.calls[0][1].body).sort(),['idempotency_key','prepared_id']);
});
test('mudança de alvo durante confirmação cancela a intenção antiga',async()=>{
 let resolve;const h=await harness(()=>new Promise(yes=>{resolve=yes;}));const first=h.update();h.props.status.jobs=[{...job,id:'d'.repeat(32)}];resolve(true);await first;assert.equal(h.calls.length,0);
});
test('recuperação exige confirmação e envia somente job fixo sem imagem ou restore',async()=>{
 const h=await harness();await h.recover({id:'e'.repeat(32)},'previous');assert.match(h.prompts[0].message,/Nenhum backup será restaurado/);assert.deepEqual(h.calls[0],['/docker-updates/recover-previous',{method:'POST',body:{cutover_id:'e'.repeat(32)}}]);
});
