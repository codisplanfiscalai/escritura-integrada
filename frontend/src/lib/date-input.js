// Datas civis: não usar Date/UTC para converter dia, mês e ano de escrituração.
export function isLeapYear(year) {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

export function validDateParts(year, month, day) {
  if (!Number.isInteger(year) || year < 1 || year > 9999 ||
      !Number.isInteger(month) || month < 1 || month > 12 ||
      !Number.isInteger(day) || day < 1) return false;
  const days = [31, isLeapYear(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day <= days[month - 1];
}

export function isISODate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value ?? ''));
  return !!match && validDateParts(Number(match[1]), Number(match[2]), Number(match[3]));
}

export function formatISODate(value) {
  if (!isISODate(value)) return '';
  const [year, month, day] = String(value).split('-');
  return `${day}/${month}/${year}`;
}

export function parseBrazilianDate(value) {
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(String(value ?? '').trim());
  if (!match || !validDateParts(Number(match[3]), Number(match[2]), Number(match[1]))) return '';
  return `${match[3]}-${match[2]}-${match[1]}`;
}

export function maskBrazilianDate(value) {
  const text = String(value ?? '');
  // Colar uma data ISO válida é inequívoco; a edição continua no formato BR.
  if (isISODate(text)) return formatISODate(text);
  const digits = text.replace(/\D/g, '').slice(0, 8);
  return digits.slice(0, 2) + (digits.length > 2 ? '/' + digits.slice(2, 4) : '') +
    (digits.length > 4 ? '/' + digits.slice(4) : '');
}

export function dateValidation(value, {required = false, min = '', max = '', invalidSource = false} = {}) {
  const text = String(value ?? '').trim();
  if (!text) {
    if (invalidSource) return {iso:'', valid:false, message:'A data recebida é inválida. Informe DD/MM/AAAA.'};
    return {iso:'', valid:!required, message:required ? 'Informe a data no formato DD/MM/AAAA.' : ''};
  }
  const iso = parseBrazilianDate(text);
  if (!iso) return {iso:'', valid:false, message:'Informe uma data válida no formato DD/MM/AAAA.'};
  if (isISODate(min) && iso < min)
    return {iso, valid:false, message:`A data deve ser igual ou posterior a ${formatISODate(min)}.`};
  if (isISODate(max) && iso > max)
    return {iso, valid:false, message:`A data deve ser igual ou anterior a ${formatISODate(max)}.`};
  return {iso, valid:true, message:''};
}
