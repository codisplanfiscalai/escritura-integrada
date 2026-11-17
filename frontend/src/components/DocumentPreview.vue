<script setup>
import {ref,watch,onBeforeUnmount,onMounted,nextTick} from 'vue';
import BaseModal from './BaseModal.vue';
import {createPdfRequest} from '../lib/document-preview.js';
import {createPdfOutput} from '../lib/document-pdf-output.js';
import {Printer,Download,Maximize2,Minimize2,ChevronLeft,ChevronRight} from 'lucide-vue-next';
const props=defineProps({url:{type:String,required:true},title:String,subtitle:String,model:String});
const emit=defineEmits(['close']);
const canvas=ref(null),loading=ref(false),error=ref(''),page=ref(1),pages=ref(0),zoom=ref(1),rendering=ref(false);
const requests=createPdfRequest();
const expanded=ref(false),source=ref(''),printError=ref(''),printing=ref(false);
const output=createPdfOutput();
async function printPdf(){const current=sequence;printError.value='';printing.value=true;try{await output.print();}catch(e){if(current===sequence)printError.value=e.message;}finally{if(current===sequence)printing.value=false;}}
let sequence=0,documentTask=null,pdf=null,renderTask=null,renderSequence=0;
function dispose(){
 sequence++;renderSequence++;requests.cancel();output.dispose();source.value='';printError.value='';printing.value=false;renderTask?.cancel();renderTask=null;
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
  const base=sheet.getViewport({scale:1});
  const scale=zoom.value==='fit'?Math.max(0.1,(canvas.value.clientWidth-32)/base.width):zoom.value*1.25;
  const target=document.createElement('canvas'),view=sheet.getViewport({scale});
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
  source.value=output.set(data);
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
watch(()=>props.url,()=>{expanded.value=false;load();},{immediate:true});
watch([page,zoom],draw);
let resizeObserver;
onMounted(()=>{resizeObserver=new ResizeObserver(()=>{if(zoom.value==='fit')draw();});resizeObserver.observe(canvas.value);});
onBeforeUnmount(()=>{resizeObserver?.disconnect();dispose();});
</script>
<template>
<BaseModal :title="title" :subtitle="subtitle" wide @close="emit('close')">
 <div class="original-preview-shell" :class="{'is-expanded':expanded}">
  <div class="original-preview-toolbar" aria-label="Ações do documento original">
   <div class="original-preview-pages" aria-label="Navegação do PDF">
    <button class="button small" aria-label="Página anterior" :disabled="page<=1||rendering||!pages" @click="page--"><ChevronLeft :size="18" aria-hidden="true"/></button>
    <span role="status">{{pages ? `Página ${page} de ${pages}` : 'Documento original'}}</span>
    <button class="button small" aria-label="Próxima página" :disabled="page>=pages||rendering||!pages" @click="page++"><ChevronRight :size="18" aria-hidden="true"/></button>
   </div>
   <label class="original-preview-zoom">Zoom <select aria-label="Zoom" v-model.number="zoom" :disabled="rendering||!pages"><option value="fit">Ajustar largura</option><option :value="0.75">75%</option><option :value="1">100%</option><option :value="1.25">125%</option><option :value="1.5">150%</option></select></label>
   <div class="original-preview-tools">
    <button class="button small" :aria-pressed="expanded" @click="expanded=!expanded"><component :is="expanded?Minimize2:Maximize2" :size="16" aria-hidden="true"/>{{expanded?'Restaurar':'Ampliar'}}</button>
    <a v-if="source" class="button small" :href="source" :download="`${(title||'documento-original').replace(/[^a-zA-Z0-9_-]+/g,'-')}.pdf`"><Download :size="16" aria-hidden="true"/>Baixar PDF</a>
    <button class="button small primary" :disabled="!source||printing" @click="printPdf"><Printer :size="16" aria-hidden="true"/>{{printing?'Preparando…':'Imprimir PDF'}}</button>
   </div>
  </div>
  <p class="original-preview-note">XML original preservado · A visualização não altera a escrituração nem valida assinatura, autorização ou tratamento fiscal.</p>
  <p v-if="model==='57'" class="message warning">Prévia disponível para CT-e normal rodoviário em retrato, com emissão e serviço normais. Outros perfis exigem validação específica. A representação não comprova autorização fiscal.</p>
  <div v-if="error" class="message warning" role="alert">{{error}} <button class="button small" @click="load">Tentar novamente</button></div>
  <p v-if="printError" class="message warning" role="alert">{{printError}}</p>
  <p v-if="loading" class="original-preview-loading" role="status">Preparando documento original…</p>
  <div ref="canvas" class="document-pdf-pages" :aria-busy="loading||rendering"/>
 </div>
 <template #footer><span class="original-preview-footer">PDF original · proporções preservadas</span><button class="button" @click="emit('close')">Fechar prévia · Esc</button></template>
</BaseModal>
</template>
<style>
.modal-overlay .modal-dialog:has(.original-preview-shell){width:min(1180px,100%);height:calc(100dvh - 48px)}
.modal-overlay .modal-dialog:has(.original-preview-shell.is-expanded){width:calc(100vw - 16px);max-width:none;height:calc(100dvh - 16px);max-height:none}
.modal-overlay:has(.original-preview-shell.is-expanded){padding:8px}
.modal-dialog:has(.original-preview-shell) .modal-body{display:flex;flex:1;min-height:0;overflow:hidden;padding:16px 20px}
.modal-dialog:has(.original-preview-shell) .modal-header{padding:16px 20px}
.modal-dialog:has(.original-preview-shell) .modal-footer{padding:12px 20px}
.original-preview-shell{display:flex;flex-direction:column;min-height:0;width:100%;gap:12px}
.original-preview-toolbar{display:flex;align-items:center;gap:16px;flex-wrap:wrap;flex-shrink:0}
.original-preview-pages,.original-preview-tools{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.original-preview-pages>span{min-width:102px;text-align:center;font-size:12px;font-variant-numeric:tabular-nums}
.original-preview-tools{margin-left:auto}.original-preview-zoom{display:flex;align-items:center;gap:8px;margin:0;font-size:12px}.original-preview-zoom select{width:auto;min-height:34px}
.original-preview-note{font-size:12px;color:var(--muted);margin:0;line-height:1.5}.original-preview-footer{font-size:12px;color:var(--muted);margin-right:auto}
.original-preview-loading{padding:24px;text-align:center}.original-preview-shell>.message{margin:0;flex-shrink:0;max-height:24vh;overflow:auto}
.original-preview-shell .document-pdf-pages{flex:1;min-height:0;overflow:auto;background:#e7edf1;border:1px solid #d5dfe6;border-radius:8px;text-align:center;overscroll-behavior:contain}
.original-preview-shell .document-pdf-pages:empty{display:none}.original-preview-shell .document-pdf-pages canvas{display:block;margin:16px auto;background:white;box-shadow:0 2px 12px #142c4226;max-width:none}
@media(max-width:600px){.modal-overlay:has(.original-preview-shell){padding:6px}.modal-overlay .modal-dialog:has(.original-preview-shell){width:100%;height:calc(100dvh - 12px);max-height:calc(100dvh - 12px)}.modal-dialog:has(.original-preview-shell) .modal-header,.modal-dialog:has(.original-preview-shell) .modal-body,.modal-dialog:has(.original-preview-shell) .modal-footer{padding:12px}.original-preview-toolbar{gap:10px}.original-preview-tools{margin-left:0;width:100%}.original-preview-note,.original-preview-footer{font-size:11px}.original-preview-shell{gap:8px}.original-preview-shell .document-pdf-pages canvas{margin:10px auto}}
</style>
