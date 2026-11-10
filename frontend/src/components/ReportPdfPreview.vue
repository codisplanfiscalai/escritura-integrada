<script setup>
import {ref, watch, onBeforeUnmount} from 'vue';
import BaseModal from './BaseModal.vue';
import {supportsEmbeddedPdf} from '../lib/pdf-preview';
import {readFileResponse} from '../lib/files';
const props = defineProps({url:{type:String,required:true},title:{type:String,required:true}});
const emit = defineEmits(['close']);
const embedded = supportsEmbeddedPdf();
const maximized = ref(false), source = ref(''), busy = ref(false), error = ref('');
let controller, generation = 0;
function dispose() {
  generation++; controller?.abort();
  if(source.value) URL.revokeObjectURL(source.value);
  source.value=''; busy.value=false;
}
async function load() {
  dispose(); error.value='';
  if(!embedded) return;
  const token=generation; controller=new AbortController(); busy.value=true;
  try {
    const response=await fetch(props.url,{credentials:'same-origin',signal:controller.signal});
    const file=await readFileResponse(response);
    if(!file.blob.type.includes('application/pdf')) throw new Error('A resposta não é um PDF. Gere o relatório novamente.');
    if(token===generation) source.value=URL.createObjectURL(file.blob);
  } catch(e) { if(token===generation && e.name!=='AbortError') error.value=e.message; }
  finally { if(token===generation) busy.value=false; }
}
watch(()=>props.url,()=>{maximized.value=false;load();},{immediate:true});
onBeforeUnmount(dispose);
</script>
<template>
  <section class="report-pdf no-print" aria-label="Prévia do relatório">
    <div class="actions">
      <button v-if="embedded" type="button" class="button outline" :disabled="!source" @click="maximized=true">Maximizar prévia</button>
      <a class="button" :href="url" target="_blank" rel="noopener">Abrir PDF / imprimir</a>
      <button type="button" class="button outline" @click="emit('close')">Fechar prévia</button>
    </div>
    <p v-if="busy" role="status">Preparando prévia PDF…</p>
    <p v-else-if="error" class="message error" role="alert">{{error}} <button class="text-button" @click="load">Tentar novamente</button></p>
    <p v-else-if="!embedded" class="message subtle">Este ambiente utiliza o leitor externo. Abra o PDF para visualizar, maximizar e imprimir.</p>
    <iframe v-if="source&&!maximized" class="report-pdf-frame" :src="source" :title="title"/>
    <BaseModal v-if="maximized" :title="title" wide @close="maximized=false">
      <div class="report-pdf-maximized"><iframe class="report-pdf-frame" :src="source" :title="title"/></div>
      <template #footer><a class="button" :href="url" target="_blank" rel="noopener">Abrir PDF / imprimir</a><button class="button outline" @click="maximized=false">Restaurar prévia</button></template>
    </BaseModal>
  </section>
</template>
<style scoped>
.report-pdf{margin:16px 0}.report-pdf-frame{width:100%;height:65vh;min-height:320px;border:1px solid #d7e0e5;background:#eee}.report-pdf .actions{margin-bottom:12px;flex-wrap:wrap}
/* More specific than .modal-dialog.wide, regardless of production CSS order. */
:global(.modal-overlay:has(.report-pdf-maximized)){padding:16px}
:global(.modal-overlay .modal-dialog:has(.report-pdf-maximized)){width:calc(100vw - 32px);max-width:none;height:calc(100dvh - 32px);max-height:none}
:global(.modal-overlay .modal-dialog:has(.report-pdf-maximized) .modal-body){flex:1;min-height:0;display:flex}
.report-pdf-maximized{width:100%;height:100%}.report-pdf-maximized .report-pdf-frame{height:100%;min-height:0}
</style>
