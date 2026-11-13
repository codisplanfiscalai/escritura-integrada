<script setup>
import { computed, ref, watch } from 'vue';
import { sourceRows, sourceLabel } from '../lib/xml-source-fields';
const props = defineProps({ value: { default: null }, title: { type: String, default: 'Campos da origem' } });
const query = ref(''), page = ref(1), size = 50;
const all = computed(() => sourceRows(props.value));
const filtered = computed(() => { const q = query.value.trim().toLocaleLowerCase('pt-BR'); return all.value.filter(row => `${row.path} ${sourceLabel(row.path)} ${row.value}`.toLocaleLowerCase('pt-BR').includes(q)); });
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / size)));
const visible = computed(() => filtered.value.slice((page.value - 1) * size, page.value * size));
watch([query, () => props.value], () => { page.value = 1; });
</script>
<template>
<section class="xml-source-fields">
  <div class="section-label">{{ title }} <span>{{ all.length }} campos disponíveis</span></div>
  <template v-if="all.length">
    <label>Filtrar campos e valores<input v-model="query" type="search" :aria-label="`Filtrar ${title}`" placeholder="Ex.: NCM, endereço, CST, vBC, pCBS ou valor" @keydown.enter.prevent/></label>
    <div class="table-scroll"><table><thead><tr><th>Campo / caminho na origem</th><th>Valor declarado</th></tr></thead><tbody><tr v-for="(row, i) in visible" :key="`${row.path}-${i}`"><td><strong v-if="sourceLabel(row.path)">{{ sourceLabel(row.path) }}</strong><span class="xml-path">{{ row.path }}</span></td><td class="xml-value">{{ row.value === '' ? '(vazio no arquivo)' : row.value }}</td></tr></tbody></table></div>
    <p v-if="!filtered.length">Nenhum campo corresponde ao filtro.</p>
    <div class="xml-pagination"><span>{{ filtered.length }} resultados · página {{ page }} de {{ pages }}</span><button type="button" class="button small" :disabled="page === 1" @click="page--">Anterior</button><button type="button" class="button small" :disabled="page === pages" @click="page++">Próxima</button></div>
  </template>
  <p v-else>Nenhum campo disponível neste registro. A ausência não significa valor zero nem isenção.</p>
</section>
</template>
<style scoped>
.xml-source-fields { margin: 16px 0; min-width: 0; }
.xml-source-fields table { width: 100%; table-layout: fixed; }
.xml-source-fields th:first-child { width: 55%; }
.xml-path { display: block; font-family: monospace; font-size: 12px; overflow-wrap: anywhere; white-space: normal; }
.xml-value { white-space: pre-wrap; overflow-wrap: anywhere; vertical-align: top; font-variant-numeric: tabular-nums; }
.xml-pagination { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
</style>
