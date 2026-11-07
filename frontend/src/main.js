import { createApp } from 'vue';
import App from './App.vue';
import './style.css';
import {can} from './lib/workspace';
function access(el,{value}){el.hidden=Array.isArray(value)?!can(value[0],value[1]):!value;}
createApp(App).directive('allow',{mounted:access,updated:access}).mount('#app');
