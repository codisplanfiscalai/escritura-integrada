# Totalizadores da consulta de documentos fiscais

Os quatro cartões usavam todos os documentos carregados do exercício, enquanto a grade e a URL de exportação usavam competência, operação, situação e pesquisa. Assim, um mês sem documentos mostrava grade vazia com totais de outros meses. O mesmo comportamento foi reproduzido em 0.8.0 (`b5d97a354115310e278d3ce86308a48cc2824356`) e 0.9.0-dev.5 (`5da0393b39007fe992fa21763a9da8244ebb8f77`); não é uma regressão introduzida pela dev.5.

A correção calcula documentos, pendências de conferência, escriturados e total documental sobre `filtered`, antes da paginação. Preserva a semântica existente: um documento escriturado pode ainda ter revisão pendente. Não altera gravação, contabilização, tributos, API, competência operacional, conteúdo das exportações ou dados persistidos.

## Validação automatizada local

- `node --test frontend/tests/*.test.js`: 138 testes aprovados, incluindo cinco testes novos dos totalizadores e os fluxos existentes.
- Casos novos: agosto/setembro/outubro vazio; operação, situação, pesquisa combinadas; todas as páginas; navegação KeepAlive; outra empresa/exercício; respostas atrasadas; mudanças rápidas de filtros durante carregamento.
- `npm --prefix frontend run build`: aprovado, com aviso de bundle acima de 500 kB.
- `git diff --check`: aprovado.

## Homologação integrada sintética

`python scripts/browser_document_summary.py` inicia servidor loopback com banco SQLite temporário e modo demonstração, usa o frontend compilado e verifica a interface real. Executar após o build, com Playwright e Chromium instalados. `ESCRITURA_TEST_BROWSER` pode indicar um executável de teste; sem ele, usa o headless shell padrão do Playwright.

Execução local aprovada com Playwright 1.56.0 isolado e Chromium Headless Shell 141.0.7390.37. O Chromium do sistema falhou ao criar socket; o navegador compartilhado não alcançou o servidor loopback. O runtime isolado resolveu a execução automatizada, sem usar abas de produção.

Fixture: duas empresas fictícias, 52 documentos de setembro (51 pendentes de R$10 e um escriturado de R$20), um documento de agosto de R$10 e exercício seguinte vazio.

- Setembro: cartões 52 / 51 / 1 / R$530, inclusive na segunda página de duas linhas.
- Agosto: 1 / 1 / 0 / R$10. Outubro: todos zerados e exportação com contagem zero e mês correto na URL.
- Saída escriturada pesquisada: 1 / 0 / 1 / R$20; pesquisa sem correspondência: zero.
- Trocas rápidas de mês e retorno da Visão geral preservam a consulta correta.
- Empresa B e exercício seguinte: zero; retorno à empresa A/exercício original restaura setembro.
- Hashes das linhas de documents, journals, journal_lines, titles e audit idênticos antes/depois das consultas e navegação. Nenhum erro JavaScript de página.

Relatório e capturas: `artifacts/browser-document-summary/`. O CI executa esse script e publica essa pasta como artefato.

## Limites

Homologação integrada em ambiente de desenvolvimento com dados sintéticos; não é homologação de produção, PostgreSQL, desktop, outros navegadores ou dados reais. A verificação de exportação confere a URL e contagem da interface, não o arquivo XLSX baixado. Respostas fora de ordem são exercitadas nos testes de componente; a execução integrada usa o servidor real sem injetar atraso artificial.

Medição exploratória local de filtro e totalizadores Vue com 10.000 documentos: mediana 44,49 ms em dez amostras após aquecimento (37,58–59,17 ms), sem DOM/rede. Não demonstra desempenho de produção nem comparação estatística antes/depois. A correção é de escopo visual; não resolve nem atribui causa à lentidão geral.

Continuam apenas diagnosticados: dependência nova dos defaults no carregamento de lançamentos, perda de página ao salvar no gerenciador global, ordenação do rascunho e divergência preexistente entre mês sugerido e data do novo lançamento. Não integram esta correção. PRs 28–33 e Atlas não são alterados. Sem merge ou implantação.
