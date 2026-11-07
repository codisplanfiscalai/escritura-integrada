<script setup>
import { computed, nextTick, onMounted, ref, useAttrs, useId, watch } from 'vue';
import { dateValidation, formatISODate, isISODate, maskBrazilianDate, parseBrazilianDate } from '../lib/date-input.js';

defineOptions({inheritAttrs:false});
const props = defineProps({
  modelValue: {type:String, default:''},
  required: Boolean,
  disabled: Boolean,
  readonly: Boolean,
  min: {type:String, default:''},
  max: {type:String, default:''},
  calendar: {type:Boolean, default:true},
});
const emit = defineEmits(['update:modelValue', 'change', 'input', 'blur', 'focus']);
const attrs = useAttrs(), visibleInput = ref(null), nativePicker = ref(null);
const display = ref(formatISODate(props.modelValue));
const touched = ref(false), pickerAvailable = ref(false);
const formatId = `date-format-${useId()}`;
let lastEmission;
const invalidSource = ref(!!props.modelValue && !isISODate(props.modelValue));
const validation = computed(() => dateValidation(display.value, {
  required:props.required, min:props.min, max:props.max, invalidSource:invalidSource.value,
}));
function inputAttrs() {
  const {name, ...rest} = attrs;
  return {
    ...rest,
    'aria-describedby':[attrs['aria-describedby'], formatId].filter(Boolean).join(' '),
    'aria-invalid':touched.value && !validation.value.valid ? 'true' : attrs['aria-invalid'],
  };
}
const isoValue = computed(() => parseBrazilianDate(display.value));

function applyValidity() {
  visibleInput.value?.setCustomValidity(props.disabled || props.readonly ? '' : validation.value.message);
}
function publish() {
  // Um texto incompleto/inválido nunca conserva silenciosamente a data anterior.
  const value = parseBrazilianDate(display.value);
  lastEmission = value;
  emit('update:modelValue', value);
  applyValidity();
}
function onInput(event) {
  const input = event.target, raw = input.value, position = input.selectionStart ?? raw.length;
  const digitOffset = raw.slice(0, position).replace(/\D/g, '').length;
  const wasISO = isISODate(raw);
  display.value = maskBrazilianDate(raw);
  invalidSource.value = false;
  input.value = display.value;
  let cursor = display.value.length;
  if (!wasISO && position < raw.length) {
    let digits = 0; cursor = 0;
    while (cursor < display.value.length && digits < digitOffset) {
      if (/\d/.test(display.value[cursor])) digits++;
      cursor++;
    }
  }
  input.setSelectionRange(cursor, cursor);
  publish();
  emit('input', event);
}
function onBlur(event) {
  touched.value = true;
  applyValidity();
  emit('blur', event);
}
function onChange(event) { emit('change', event); }
function chooseNative(event) {
  const value = event.target.value;
  if (value && !isISODate(value)) return;
  display.value = formatISODate(value);
  invalidSource.value = false;
  touched.value = true;
  publish();
  emit('change', event);
  nextTick(() => visibleInput.value?.focus());
}
function openCalendar() {
  if (props.disabled || props.readonly || visibleInput.value?.matches(':disabled')) return;
  try {
    nativePicker.value.value = isoValue.value;
    nativePicker.value.showPicker();
  } catch (_) {
    // Hosts que não permitem o popup mantêm a edição BR acessível pelo teclado.
    visibleInput.value?.focus();
  }
}
watch(() => props.modelValue, value => {
  if (value === lastEmission) { lastEmission = undefined; return; }
  lastEmission = undefined;
  display.value = formatISODate(value);
  invalidSource.value = !!value && !isISODate(value);
  touched.value = false;
}, {flush:'sync'});
watch(() => [validation.value.message, props.disabled, props.readonly], applyValidity, {flush:'post'});
onMounted(() => { pickerAvailable.value = typeof nativePicker.value?.showPicker === 'function'; applyValidity(); });
defineExpose({
  focus:() => visibleInput.value?.focus(),
  checkValidity:() => { applyValidity(); return visibleInput.value?.checkValidity() ?? validation.value.valid; },
  reportValidity:() => { touched.value = true; applyValidity(); return visibleInput.value?.reportValidity() ?? validation.value.valid; },
});
</script>

<template>
  <span class="date-input" :class="{'has-calendar':calendar&&pickerAvailable}">
    <input ref="visibleInput" v-bind="inputAttrs()" class="date-input-field" type="text"
      :value="display" :required="required" :disabled="disabled" :readonly="readonly"
      inputmode="numeric" maxlength="10" pattern="[0-9]{2}/[0-9]{2}/[0-9]{4}"
      placeholder="DD/MM/AAAA" autocomplete="off" :spellcheck="false" lang="pt-BR"
      :data-unsaved="display&&!validation.valid?'true':undefined"
      @input="onInput" @blur="onBlur" @change="onChange" @focus="emit('focus',$event)"
      @invalid="touched=true"/>
    <input v-if="attrs.name" type="hidden" :name="attrs.name" :form="attrs.form" :value="isoValue" :disabled="disabled"/>
    <input v-if="calendar" ref="nativePicker" class="date-input-native" type="date"
      :value="isoValue" :min="min||undefined" :max="max||undefined" :disabled="disabled||readonly"
      tabindex="-1" aria-hidden="true" lang="pt-BR" @change="chooseNative"/>
    <button v-if="calendar&&pickerAvailable" type="button" class="date-input-calendar"
      :disabled="disabled||readonly" :aria-label="attrs['aria-label']?`Abrir calendário: ${attrs['aria-label']}`:'Abrir calendário'"
      title="Escolher data no calendário" @click.prevent.stop="openCalendar">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18M8 15h2M14 15h2"/></svg>
    </button>
    <span :id="formatId" class="date-input-hint">Formato: dia, mês e ano — DD/MM/AAAA.</span>
  </span>
</template>

<style scoped>
.date-input{position:relative;display:block;width:100%;min-width:0;color:inherit}
.date-input .date-input-field{display:block;width:100%;min-width:0;font-variant-numeric:tabular-nums}
.date-input.has-calendar .date-input-field{padding-right:38px}
.date-input .date-input-field[aria-invalid="true"]{border-color:#b84741}
.date-input .date-input-native{position:absolute;right:10px;bottom:3px;width:1px;height:1px;min-width:0;min-height:0;padding:0;border:0;opacity:0;pointer-events:none}
.date-input .date-input-calendar{position:absolute;right:1px;top:1px;bottom:1px;display:grid;place-items:center;width:34px;padding:0;border:0;border-radius:0 7px 7px 0;background:transparent;color:#526c73;cursor:pointer}
.date-input .date-input-calendar:hover:not(:disabled){background:#edf3f4;color:#214f58}
.date-input .date-input-calendar:focus-visible{outline:2px solid #2b7778;outline-offset:-3px}
.date-input .date-input-calendar:disabled{cursor:default;opacity:.45}
.date-input .date-input-hint{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;border:0}
</style>
