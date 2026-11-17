<script setup>
import {watch,onMounted,onActivated,onDeactivated,onUnmounted} from 'vue';
import ReceptionPanel from '../components/ReceptionPanel.vue';
import {state,api,can,scope} from '../lib/workspace';
import {createReception} from '../lib/reception.js';
const controller=createReception({state,api,can,scope,provider:'nfse_adn'});
watch(()=>[state.companyId,state.period,state.module,state.session?.user?.id,JSON.stringify(state.session?.permissions||{})],controller.reset,{flush:'sync'});
onMounted(controller.activate);onActivated(controller.activate);onDeactivated(controller.deactivate);onUnmounted(controller.deactivate);
</script>
<template><ReceptionPanel :controller="controller" title="NFS-e Nacional"/></template>
