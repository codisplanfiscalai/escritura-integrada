<script setup>
import {computed} from 'vue';
import {money,cents} from '../lib/format';
const props=defineProps({document:Object});
const snapshot=computed(()=>props.document?.service_bookkeeping);
const labels={accounting:'Valor contábil',base:'Base ISS',iss:'ISS',iss_withheld:'ISS retido'};
const fields=computed(()=>Object.entries(snapshot.value?.values||{}).filter(([,v])=>v!==null&&v!==undefined));
</script>
<template><div v-if="document?.model==='NFSE'" class="service-values"><div v-for="[key,value] in fields" :key="key">{{labels[key]}}: {{money(cents(value))}}</div><small v-if="snapshot?.profile">Perfil de serviços · versão {{snapshot.profile.version}}</small><small v-else>Perfil de serviços pendente de conferência.</small></div></template>
<style scoped>.service-values{font-size:.8rem;line-height:1.5;min-width:170px;margin-top:6px;white-space:normal}.service-values small{display:block;color:var(--muted)}</style>
