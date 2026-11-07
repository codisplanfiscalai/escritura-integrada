<script setup>
import Icon from './Icon.vue';
defineProps({title:String,text:String,icon:{type:String,default:'folder'}});
</script>
<template><div class="empty-state"><div class="empty-icon"><Icon :name="icon" :size="28"/></div><h3>{{title}}</h3><p>{{text}}</p><slot/></div></template>
