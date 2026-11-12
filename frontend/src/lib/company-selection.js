const fold = value => String(value ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase().trim();
const canonical = value => /^\d+$/.test(value) ? value.replace(/^0+(?=\d)/, '') : value;
export function matchingCompanies(companies, query) {
  const q = fold(query);
  if (!q) return companies;
  return companies.filter(c => [c.code, c.name, c.trade_name, c.tax_id].some(v => fold(v).includes(q)) || canonical(fold(c.code)) === canonical(q))
    .map((c, index) => ({c, index, rank: fold(c.code) === q ? 0 : canonical(fold(c.code)) === canonical(q) ? 1 : 2}))
    .sort((a,b) => a.rank - b.rank || a.index - b.index).map(x => x.c);
}
export function locateCompany(companies, query) {
  const q = fold(query);
  if (!q) return null;
  const literal = companies.filter(c => fold(c.code) === q);
  if (literal.length === 1) return literal[0];
  if (literal.length > 1) return null;
  const numeric = companies.filter(c => canonical(fold(c.code)) === canonical(q));
  if (numeric.length === 1) return numeric[0];
  const matches = matchingCompanies(companies, query);
  return matches.length === 1 ? matches[0] : null;
}
