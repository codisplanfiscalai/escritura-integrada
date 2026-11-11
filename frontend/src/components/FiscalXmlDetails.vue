<script setup>
import { computed, ref } from 'vue';
import XmlSourceFields from './XmlSourceFields.vue';
const props = defineProps({ document: { type: Object, required: true }, itemsOnly: Boolean });
const itemQuery = ref('');
function sourceItemTree(item, index) {
 const root=props.document.declared_xml;
 if(!root)return item.declared_item_fields;
 const candidates=[];
 function walk(node){if(!node||typeof node!=='object')return;if(node.tag?.split('}').pop()==='det')candidates.push(node);else(node.children||[]).forEach(walk);}
 walk(root);
 return candidates.find(node=>String(node.attributes?.nItem)===String(item.number ?? index+1)) || candidates[index] || item.declared_item_fields;
}

const items = computed(() => (props.document.items || []).map((item, index) => ({ item, index })).filter(({item, index}) => `${item.number || index + 1} ${item.code || ''} ${item.description || ''} ${item.ncm || ''}`.toLocaleLowerCase('pt-BR').includes(itemQuery.value.trim().toLocaleLowerCase('pt-BR'))));
const groups = computed(() => [
 ['Emitente: identificação, inscrições e endereço', props.document.issuer],
 ['Destinatário: identificação, inscrições e endereço', props.document.recipient],
 ['Autorização e protocolo', props.document.declared_protocol || props.document.authorization],
 ['Transporte, transportador e volumes', props.document.transport],
 ['Cobrança, faturas e pagamentos', props.document.billing || props.document.invoices],
 ['Totalizadores e tributos declarados', props.document.taxes],
 ['Cabeçalho e demais campos do documento', props.document.declared_document_fields],
 ['Outros campos preservados', props.document.raw_fields]
]);
</script>
<template>
<div class="fiscal-xml-details">
  <p class="message subtle">Consulta dos dados disponíveis na origem preservada. Valores e alíquotas são exibidos sem cálculo, arredondamento ou presunção. Alterações operacionais não substituem estes campos.</p>
  <template v-if="!itemsOnly">
    <details v-for="[title, value] in groups" :key="title"><summary>{{ title }}</summary><XmlSourceFields :title="title" :value="value"/></details>
    <details><summary>Todos os campos XML, inclusive grupos repetidos</summary><XmlSourceFields title="Árvore completa do XML preservado" :value="document.declared_xml"/><p v-if="!document.declared_xml">Este registro não possui a árvore completa armazenada. Consulte os grupos disponíveis acima e os itens; não se presume informação ausente.</p></details>
  </template>
  <template v-else>
    <div class="section-label">Detalhamento dos itens da origem <span>{{ document.items?.length || 0 }} itens</span></div>
    <label>Localizar item<input v-model="itemQuery" type="search" placeholder="Número, código, descrição ou NCM" @keydown.enter.prevent/></label>
    <p v-if="!items.length">Nenhum item disponível para este filtro.</p>
    <details v-for="{item, index} in items" :key="index"><summary>Item {{ item.number || index + 1 }} · {{ item.code || 'Sem código' }} · {{ item.description || 'Sem descrição' }}</summary>
      <XmlSourceFields title="Produto: códigos, unidades, quantidades e valores" :value="item.declared_product_fields || {code:item.code,description:item.description,ncm:item.ncm,cest:item.cest,unit:item.unit,quantity:item.quantity,unit_price:item.unit_price,total:item.total,source_cfop:item.source_cfop}"/>
      <XmlSourceFields title="Tributos: CST / CSOSN, bases, alíquotas e valores, inclusive IBS / CBS" :value="item.taxes"/>
      <XmlSourceFields title="Demais grupos e informações do item" :value="sourceItemTree(item, index)"/>
    </details>
  </template>
</div>
</template>
<style scoped>
.fiscal-xml-details details { border: 1px solid var(--border, #d9dee8); border-radius: 8px; margin: 10px 0; padding: 12px; }
.fiscal-xml-details summary { cursor: pointer; font-weight: 600; overflow-wrap: anywhere; }
</style>
