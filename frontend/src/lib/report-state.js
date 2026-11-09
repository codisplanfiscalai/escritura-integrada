// Uma consulta só pode alterar a tela enquanto ainda for a mais recente.
export function latestRequest() {
  let sequence = 0;
  return { begin: () => ++sequence, invalidate: () => ++sequence, current: token => token === sequence };
}
export function reportKindsForArea(kinds, area) {
  return Object.fromEntries(Object.entries(kinds).filter(([kind]) => area === 'fiscal'
    ? kind.startsWith('fiscal-') : area === 'financial'
      ? ['financial', 'cash-flow', 'partners'].includes(kind)
      : !kind.startsWith('fiscal-') && !['financial', 'cash-flow', 'partners'].includes(kind)));
}
export function reportFileUrl(url, format, print = false) {
  return `/api${url}&format=${format}${print ? '&purpose=print' : ''}`;
}
