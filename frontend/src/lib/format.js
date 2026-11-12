const currencyFormatter = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const numberFormatter = new Intl.NumberFormat('pt-BR');
export const money = (cents = 0) => currencyFormatter.format(Number(cents || 0) / 100);
export const number = (n = 0) => numberFormatter.format(n);
export const date = value => value ? String(value).slice(0, 10).split('-').reverse().join('/') : '—';
export const dateTime = value => value ? new Date(value).toLocaleString('pt-BR') : '—';
export function amount(value) {
  let s = String(value ?? '').trim();
  if (!s) return '0.00';
  if (s.includes(',')) s = s.replaceAll('.', '').replace(',', '.');
  if (!/^-?\d+(\.\d{1,2})?$/.test(s)) throw new Error('Informe um valor com até duas casas decimais.');
  const [a, b = ''] = s.split('.');
  return `${a}.${b.padEnd(2, '0')}`;
}
export function cents(value) {
  try { const v = amount(value); const [a,b] = v.split('.'); return (a.startsWith('-') ? -1 : 1) * (Math.abs(Number(a)) * 100 + Number(b)); } catch { return null; }
}
export const inputMoney = c => (Number(c || 0) / 100).toFixed(2).replace('.', ',');
export const taxId = value => { const s = String(value || ''); return s.length === 14 ? `${s.slice(0,2)}.${s.slice(2,5)}.${s.slice(5,8)}/${s.slice(8,12)}-${s.slice(12)}` : s; };
export const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; };
export const periodDate = period => today().startsWith(period) ? today() : `${period}-01`;
export const normalized = s => String(s || '').normalize('NFD').replace(/\p{Diacritic}/gu,'').toLowerCase();
export function uid() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16); globalThis.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map(b => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
export const statusLabel = s => ({posted:'Escriturado',booked:'Escriturado',draft:'Rascunho',pending:'Pendente',reviewed:'Conferido',paid:'Baixado',settled:'Baixado',validated:'Validada',partial:'Parcial',open:'Em aberto',closed:'Fechado',reversed:'Estornado',matched:'Conciliado',unmatched:'A conciliar',approved:'Validada',active:'Ativa',cancelled:'Cancelado',incoming:'Entrada',outgoing:'Saída',service:'Serviço',payable:'A pagar',receivable:'A receber'}[s] || s || '—');
