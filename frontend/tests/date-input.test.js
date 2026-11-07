import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {createSSRApp} from 'vue';
import {renderToString} from '@vue/server-renderer';
import {parse, compileScript} from '@vue/compiler-sfc';
import {
  dateValidation, formatISODate, isISODate, maskBrazilianDate,
  parseBrazilianDate, validDateParts,
} from '../src/lib/date-input.js';

test('a data ambígua de novembro permanece inequívoca no formato brasileiro', () => {
  assert.equal(formatISODate('2026-11-06'), '06/11/2026');
  assert.equal(parseBrazilianDate('06/11/2026'), '2026-11-06');
  assert.equal(parseBrazilianDate('11/06/2026'), '2026-06-11');
  assert.equal(maskBrazilianDate('06112026'), '06/11/2026');
  assert.equal(maskBrazilianDate('2026-11-06'), '06/11/2026');
});

test('calendário gregoriano rejeita dias impossíveis e trata anos bissextos', () => {
  for (const value of ['29/02/2023','29/02/1900','31/04/2026','00/11/2026','06/13/2026','06/11/0000','6/11/2026'])
    assert.equal(parseBrazilianDate(value), '', value);
  assert.equal(parseBrazilianDate('29/02/2024'), '2024-02-29');
  assert.equal(parseBrazilianDate('29/02/2000'), '2000-02-29');
  assert.equal(parseBrazilianDate('01/01/0001'), '0001-01-01');
  assert.equal(isISODate('2026-02-30'), false);
  assert.equal(isISODate('2026-11-06T00:00:00Z'), false);
});

test('todos os dias válidos voltam ao mesmo ISO sem depender de fuso horário', () => {
  for (const year of [1900,2000,2024,2026]) {
    for (let month=1; month<=12; month++) {
      for (let day=1; day<=31; day++) {
        if (!validDateParts(year,month,day)) continue;
        const iso=`${year}-${String(month).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
        assert.equal(parseBrazilianDate(formatISODate(iso)),iso);
      }
    }
  }
});

test('required, limites inclusivos e edição incompleta geram validade explícita', () => {
  assert.equal(dateValidation('').valid,true);
  assert.equal(dateValidation('',{required:true}).valid,false);
  assert.equal(dateValidation('06/11/20').valid,false);
  assert.equal(dateValidation('31/02/2026').iso,'');
  assert.equal(dateValidation('06/11/2026',{min:'2026-11-06',max:'2026-11-06'}).valid,true);
  const early=dateValidation('05/11/2026',{min:'2026-11-06'});
  assert.equal(early.valid,false); assert.match(early.message,/06\/11\/2026/);
  const late=dateValidation('07/11/2026',{max:'2026-11-06'});
  assert.equal(late.valid,false); assert.match(late.message,/06\/11\/2026/);
  assert.equal(dateValidation('',{invalidSource:true}).valid,false);
});

test('campo visível encaminha rótulo/required e o valor nomeado do formulário é ISO', async () => {
  const filename=new URL('../src/components/DateInput.vue',import.meta.url);
  const source=await readFile(filename,'utf8');
  const {descriptor,errors}=parse(source,{filename:filename.pathname});
  assert.deepEqual(errors,[]);
  const compiled=compileScript(descriptor,{id:'date-input-test',inlineTemplate:true});
  const require=createRequire(import.meta.url);
  const vue=pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href;
  const helper=new URL('../src/lib/date-input.js',import.meta.url).href;
  const code=compiled.content.replace(/from ['"]vue['"]/g,`from ${JSON.stringify(vue)}`)
    .replace(/from ['"]\.\.\/lib\/date-input\.js['"]/g,`from ${JSON.stringify(helper)}`);
  const component=(await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default;
  const html=await renderToString(createSSRApp(component,{
    modelValue:'2026-11-06',required:true,min:'2026-11-01',max:'2026-11-30',
    'aria-label':'Data do lançamento',id:'posting-date',name:'posting_date',
  }));
  const inputs=html.match(/<input\b[^>]*>/g) || [];
  const visible=inputs.find(tag=>tag.includes('type="text"'));
  assert.ok(visible,'Deve existir um input de texto visível');
  assert.match(visible,/aria-label="Data do lançamento"/);
  assert.match(visible,/id="posting-date"/);
  assert.match(visible,/value="06\/11\/2026"/);
  assert.match(visible,/\brequired(?:[\s>]|="")/);
  assert.match(visible,/aria-describedby="date-format-/);
  assert.doesNotMatch(visible,/name="posting_date"/);
  const named=inputs.filter(tag=>tag.includes('name="posting_date"'));
  assert.equal(named.length,1);
  assert.match(named[0],/type="hidden"/);
  assert.match(named[0],/value="2026-11-06"/);
  const picker=inputs.find(tag=>tag.includes('type="date"'));
  assert.match(picker,/aria-hidden="true"/);
  assert.match(picker,/tabindex="-1"/);
  assert.match(picker,/min="2026-11-01"/);
  assert.match(picker,/max="2026-11-30"/);
});
