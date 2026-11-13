# Catálogo importado não aparecia na auditoria

## Causa reproduzida

A referência histórica 1.2.2 é importada como rascunho. Tem 15.638 linhas,
7 erros impeditivos em 6 linhas e 2 avisos. O seletor mostrava somente versões
publicadas e não explicava por que o catálogo já importado não aparecia.
Os modos avulso e escrituração compartilham esse seletor e a mesma API.

## Correção

- Listagem opcional de metadados de rascunhos na API de seleção, sem enviar
  regras completas nem alterar o comportamento padrão dos consumidores.
- Ambos os modos exibem o rascunho desabilitado com seu motivo, quantidade
  de linhas/erros e acesso direto à revisão daquele catálogo.
- Falha de carregamento é mostrada separadamente de ausência de catálogos.
- Lista de catálogos destaca a ação Revisar e publicar e a tela explica
  a disponibilidade do rascunho.
- Não publica regras históricas automaticamente, não inventa CST/cClassTrib,
  não altera bases de clientes, XMLs, relatórios ou resultados anteriores.

## Validação

`npm run build` (frontend) e os três testes direcionados de catálogos/permissões
em `test_auditor_integration` passaram. A suíte completa executou 14 testes:
4 falhas no mesmo teste de documentos auxiliares por renderizador não instalado.
O novo `scripts/browser_catalog_discovery.py` cobre ambos os modos, navegação
para revisão e ausência de publicação automática. A execução Chromium deste
ambiente foi impedida por `socket() failed: Operation not permitted`, inclusive
na tentativa escalonada; precisa rodar no CI ou em ambiente com navegador.

## Pendência fiscal explícita

As seis linhas inconsistentes ainda exigem revisão da classificação de origem
antes da publicação. Este patch resolve a falsa impressão de catálogo ausente,
não declara a referência histórica fiscalmente homologada nem altera seus dados.

## Complemento: revisão funcional fundamentada (13/11/2026)

O diagnóstico inicial incluía três falsos bloqueios: cabeçalhos hierárquicos
12076, 12077 e 12079 (linhas 1317, 1320, 1323). O motor nunca os utiliza como
regras; a validação foi alinhada para não exigir classificação desses cabeçalhos.
O original passa a apresentar 4 erros impeditivos em 3 linhas, sem mudar seus dados.

A opção **Aplicar erratas verificadas** na importação/revisão cria outra versão:

| Linha | NCM | Ajuste pontual | Fundamento |
|---|---|---|---|
| 638 | 03099000 | CST 2000 → 200, cClass200038 mantido | SVRS vincula 200038 ao CST200, redução60%; AnexoIX item21/art138 |
| 1505 | 15132120 | Redução textual60% →100%, cClass200003 mantido | SVRS 200003 reduz100%; AnexoI item9/art125, babaçu para alimentação humana |
| 6024 | 34011190 | Preenche200035, redução60% | SVRS200035; AnexoVIII item1/art136, sabões de toucador |

Fontes: tabela oficial [SVRS](https://dfe-portal.svrs.rs.gov.br/DFE/ClassificacaoTributaria)
e [LC214 consolidada disponibilizada pela SEF/MG](https://www.fazenda.mg.gov.br/export/sites/fazenda/empresas/legislacao_tributaria/leis/2025/lc214_2025.pdf).
Metadados efetivamente obtidos e hashes em `AUDITOR_CATALOG_OFFICIAL_EVIDENCE.json`.
Os três códigos constavam no retorno oficial de 22/06/2026, sem fim de vigência.
Não se afirma que a base completa de 2025 ficou atualizada em 2026.

Os ajustes atingem apenas as linhas e os valores originais exatos do arquivo
com SHA conhecido; regras personalizadas são preservadas. Fonte comprimida,
catálogo original e histórico não são modificados. Antes/depois, fundamento,
URL e data ficam na nova versão. Ela continua rascunho, sem publicação automática.

As condições legais são explícitas: destinação à alimentação animal não doméstica;
babaçu apto ao consumo alimentar; produto efetivamente sabão de toucador. O motor
não considera só o NCM suficiente para confirmá-las: retorna
`CONDITION_REVIEW_REQUIRED`, com evidência das condições, e não `MATCH_EXACT`
nem divergência definitiva contra o XML. Não houve acesso ou mutação na produção.
