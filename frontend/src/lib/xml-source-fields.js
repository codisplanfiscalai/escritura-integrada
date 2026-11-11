// Preserve lexical XML values, including zeros, repeated groups and attributes.
export function sourceRows(value) {
  const rows = [];
  function visit(node, path) {
    if (node === undefined || node === null) return;
    if (Array.isArray(node)) { node.forEach((child, i) => visit(child, `${path}[${i + 1}]`)); return; }
    if (typeof node === 'object') {
      if (typeof node.tag === 'string') {
        const children = node.children || [];
        const base = path ? `${path}/${node.tag}` : node.tag;
        Object.entries(node.attributes || {}).forEach(([key, val]) => visit(val, `${base}/@${key}`));
        if (node.text !== undefined && node.text !== null) visit(node.text, base);
        else if (!children.length) visit('', base);
        const totals = {}, counts = {};
        children.forEach(child => { totals[child.tag] = (totals[child.tag] || 0) + 1; });
        children.forEach(child => {
          counts[child.tag] = (counts[child.tag] || 0) + 1;
          const tag = totals[child.tag] > 1 ? `${child.tag}[${counts[child.tag]}]` : child.tag;
          visit({ ...child, tag }, base);
        });
        return;
      }
      Object.entries(node).forEach(([key, val]) => visit(val, path ? `${path}/${key}` : key));
      return;
    }
    rows.push({ path: path || 'Valor', value: String(node) });
  }
  visit(value, '');
  return rows;
}
export const xmlFieldLabels = {
  cProd:'Código do produto',xProd:'Descrição',NCM:'NCM',CEST:'CEST',CFOP:'CFOP da origem',
  cEAN:'GTIN comercial',cEANTrib:'GTIN tributável',uCom:'Unidade comercial',qCom:'Quantidade comercial',vUnCom:'Valor unitário comercial',
  uTrib:'Unidade tributável',qTrib:'Quantidade tributável',vUnTrib:'Valor unitário tributável',vProd:'Valor dos produtos',vDesc:'Desconto',vFrete:'Frete',vSeg:'Seguro',vOutro:'Outras despesas',
  CST:'CST',CSOSN:'CSOSN',orig:'Origem da mercadoria',cClassTrib:'Classificação tributária',vBC:'Base de cálculo',vBCST:'Base ICMS ST',
  pICMS:'Alíquota ICMS',vICMS:'Valor ICMS',pICMSST:'Alíquota ICMS ST',vICMSST:'Valor ICMS ST',pIPI:'Alíquota IPI',vIPI:'Valor IPI',pPIS:'Alíquota PIS',vPIS:'Valor PIS',pCOFINS:'Alíquota Cofins',vCOFINS:'Valor Cofins',
  pIBSUF:'Alíquota IBS UF',pIBSMun:'Alíquota IBS municipal',vIBS:'Valor IBS',pCBS:'Alíquota CBS',vCBS:'Valor CBS',
  xNome:'Razão social / nome',xFant:'Nome fantasia',CNPJ:'CNPJ',CPF:'CPF',IE:'Inscrição estadual',IM:'Inscrição municipal',CRT:'Regime tributário declarado',CNAE:'CNAE',
  xLgr:'Logradouro',nro:'Número',xCpl:'Complemento',xBairro:'Bairro',cMun:'Código do município',xMun:'Município',UF:'UF',CEP:'CEP',cPais:'Código do país',xPais:'País',fone:'Telefone',
  name:'Nome',trade_name:'Nome fantasia',tax_id:'CNPJ / CPF',state_registration:'Inscrição estadual',municipal_registration:'Inscrição municipal',street:'Logradouro',number:'Número',complement:'Complemento',district:'Bairro',city:'Município',state:'UF',zip:'CEP',country:'País',phone:'Telefone',email:'E-mail',
  nProt:'Protocolo',cStat:'Código de situação',xMotivo:'Motivo da situação',dhRecbto:'Recebimento',natOp:'Natureza da operação',infCpl:'Informações complementares',infAdFisco:'Informações ao fisco',modFrete:'Modalidade do frete',nFat:'Número da fatura',nDup:'Número da duplicata',dVenc:'Vencimento',vDup:'Valor da duplicata'
};
export function sourceLabel(path) { return xmlFieldLabels[path.split('/').pop().replace(/\[\d+\]$/, '')] || ''; }
