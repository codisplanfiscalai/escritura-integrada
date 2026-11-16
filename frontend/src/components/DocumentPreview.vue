<script setup>
import {ref,watch,onBeforeUnmount,nextTick} from 'vue';
import BaseModal from './BaseModal.vue';
import {createPdfRequest} from '../lib/document-preview.js';
const props=defineProps({url:{type:String,required:true},title:String,subtitle:String,model:String});
const emit=defineEmits(['close']);
const canvas=ref(null),loading=ref(false),error=ref(''),page=ref(1),pages=ref(0),zoom=ref(1),rendering=ref(false);
const requests=createPdfRequest();
let sequence=0,documentTask=null,pdf=null,renderTask=null,renderSequence=0;
function dispose(){
 sequence++;renderSequence++;requests.cancel();renderTask?.cancel();renderTask=null;
 documentTask?.destroy()?.catch(()=>{});documentTask=null;pdf=null;
 pages.value=0;loading.value=false;rendering.value=false;
}
async function draw(){
 if(!pdf||!canvas.value)return;
 const current=++renderSequence,source=pdf;
 renderTask?.cancel();renderTask=null;rendering.value=true;
 try{
  const sheet=await source.getPage(page.value);
  if(current!==renderSequence||source!==pdf)return;
  // Allocate a fresh canvas per render so an old cancelled task cannot paint
  // the current document. One page at a time bounds memory for long DANFEs.
  const target=document.createElement('canvas'),view=sheet.getViewport({scale:zoom.value*1.25});
  const density=2; // Keep narrow bars and small fiscal fields sharp on 1x displays.
  target.width=Math.ceil(view.width*density);target.height=Math.ceil(view.height*density);
  target.style.width=`${view.width}px`;target.style.height=`${view.height}px`;
  target.setAttribute('role','img');target.setAttribute('aria-label',`${props.title} · página ${page.value} de ${pages.value}`);
  renderTask=sheet.render({canvasContext:target.getContext('2d'),viewport:view,transform:density!==1?[density,0,0,density,0,0]:null});
  await renderTask.promise;
  if(current===renderSequence&&source===pdf)canvas.value?.replaceChildren(target);
 }catch(e){if(current===renderSequence&&e.name!=='RenderingCancelledException')error.value='Não foi possível exibir esta página do PDF.';}
 finally{if(current===renderSequence)rendering.value=false;}
}
async function load(){
 dispose();const current=sequence;error.value='';loading.value=true;page.value=1;zoom.value=1;
 canvas.value?.replaceChildren();
 try{
  const data=await requests.load(props.url);
  if(!data||current!==sequence)return;
  const [engine,worker]=await Promise.all([import('pdfjs-dist/legacy/build/pdf.mjs'),import('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url')]);
  if(current!==sequence)return;
  engine.GlobalWorkerOptions.workerSrc=worker.default;
  documentTask=engine.getDocument({data,isEvalSupported:false,useSystemFonts:true,useWasm:false,wasmUrl:`${window.location.origin}/pdfjs-codecs/${engine.version}/`});
  const result=await documentTask.promise;
  if(current!==sequence)return;
  pdf=result;pages.value=result.numPages;
  await nextTick();await draw();
 }catch(e){if(current===sequence)error.value=e.message||'Não foi possível abrir a prévia.';}
 finally{if(current===sequence)loading.value=false;}
}
watch(()=>props.url,load,{immediate:true});
watch([page,zoom],draw);
onBeforeUnmount(dispose);
</script>
<template>
<BaseModal :title="title" :subtitle="subtitle" wide @close="emit('close')">
 <p class="field-help">Representação do XML original preservado. Não altera a escrituração nem valida assinatura, autorização ou tratamento fiscal.</p>
 <p v-if="model==='57'" class="message warning">Prévia DACTE: há limitações conhecidas de sobreposição e corte de textos longos no renderizador. O QR tem área protegida, mas a fidelidade completa não foi validada. Confira a legibilidade; este layout ainda exige revisão.</p>
 <div v-if="error" class="message warning" role="alert">{{error}} <button class="button small" @click="load">Tentar novamente</button></div>
 <p v-if="loading" role="status">Preparando documento original…</p>
 <div v-if="pages" class="actions preview-navigation" aria-label="Navegação do PDF">
  <button class="button small" :disabled="page<=1||rendering" @click="page--">Página anterior</button>
  <span role="status">Página {{page}} de {{pages}}</span>
  <button class="button small" :disabled="page>=pages||rendering" @click="page++">Próxima página</button>
  <label>Zoom <select aria-label="Zoom" v-model.number="zoom" :disabled="rendering"><option :value="0.75">75%</option><option :value="1">100%</option><option :value="1.25">125%</option><option :value="1.5">150%</option></select></label>
 </div>
 <div ref="canvas" class="document-pdf-pages" :aria-busy="loading||rendering"/>
 <template #footer><button class="button" @click="emit('close')">Fechar prévia · Esc</button></template>
</BaseModal>
</template>
<style scoped>
.preview-navigation{flex-wrap:wrap;margin-bottom:12px}.preview-navigation label{display:flex;align-items:center;gap:8px;margin-left:auto}.preview-navigation select{width:auto}
.document-pdf-pages{overflow:auto;max-height:65vh;background:#e7eaee;text-align:center;border-radius:4px}.document-pdf-pages:empty{display:none}.document-pdf-pages :deep(canvas){display:block;margin:12px auto;background:white;box-shadow:0 2px 10px #0002}
</style>
