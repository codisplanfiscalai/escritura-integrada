# Competência dos indicadores e carregamento contábil

## Evidência e escopo

Comparação local em 15/11/2026 entre v0.8.0 (`b5d97a354115310e278d3ce86308a48cc2824356`) e develop 0.9.0-dev.8 (`f1aac9964f25c1c0ad3ce76496fb89eb231fd101`). A PR parte de develop dev.9 (`3a6ab4c58f5c48aa0ea383cc2beeff615172ce71`), que acrescentou a PR34 e a versão; não alterou os três arquivos de aplicação medidos aqui. Nenhuma base, informação de cliente ou serviço de produção foi acessado nesta tarefa.

Os dois defeitos corrigidos são **preexistentes em 0.8.0**, não regressões comprovadas da 0.9.0:

- `app/core.py: Core.journals` carregava cada lançamento com `_journal`, repetindo a expansão de `effective_accounts`. `app/api.py: journals` carregava todos os anos para depois filtrar o exercício em Python. Agora lê cabeçalhos e linhas em lote, na mesma snapshot, com empresa e período/exercício no SQL. Mantém todas as linhas e metadados, ordem decrescente de data/ID, ordem das partidas e status de estorno. Não altera lançamentos, contas, apuração, saldo, esquema ou regra fiscal.
- `frontend/src/views/DashboardView.vue` consultava o mês operacional, ignorando o mês sugerido pelo F8. Com novembro operacional e setembro sugerido, tanto v0.8.0 quanto dev.8 requisitavam novembro. Agora os indicadores fiscais, contábeis, lançamentos recentes e estado de fechamento seguem setembro, mantendo novembro operacional intacto. Trocas de mês limpam os indicadores; o mecanismo existente de sequência descarta respostas antigas. Empresa e exercício continuam isolados. Os saldos financeiros continuam sendo da empresa em todos os períodos, agora com legenda explícita.

Os cartões da consulta de documentos são uma correção separada da PR34, já integrada na base dev.9. Esta PR não altera `DocumentsView.vue`. Os filtros da lista de lançamentos e as datas de novos lançamentos permanecem com seu comportamento existente; não se afirma que toda navegação ou editor mudou para a competência sugerida.

## Medição reproduzível

SQLite temporário, HTTP em processo via TestClient, uma execução de aquecimento e três amostras sequenciais por rota, na mesma máquina. Base demonstrativa mais 300 lançamentos (100 em 09/2025, 08/2026 e 09/2026), 860 documentos (430 em cada mês de 2026, cinco itens cada) e plano com 22.597 contas. A base demonstrativa acrescenta dois lançamentos/documentos de novembro. Não são latências de rede, renderização ou produção; três amostras não caracterizam carga concorrente ou percentis operacionais.

| Consulta | v0.8.0 (ms) | dev.8 antes (ms) | correção (ms) |
|---|---:|---:|---:|
| Contas completas | 430,694 | 430,484 | 427,201 |
| Contas paginadas, 50 | 18,722 | 19,138 | 19,215 |
| Documentos do exercício | 228,031 | 214,095 | 212,675 |
| Documentos de setembro | 97,319 | 85,094 | 83,461 |
| Lançamentos do exercício | 7250,048 | 7207,413 | 43,300 |
| Lançamentos de setembro | 2390,583 | 2396,769 | 36,074 |
| Dashboard de setembro | 7,962 | 6,643 | 6,013 |

Medianas. Lançamentos anuais: 614 SELECTs de leitura por requisição passaram a 11 (incluindo middleware); mensais: 210 para 11. Na chamada direta ao core são três SELECTs. Respostas mantiveram 202 lançamentos/187.290 bytes no ano e 100/92.681 bytes no mês. A igualdade integral de campos também é testada contra `_journal`.

A consulta fiscal ainda carrega documentos anuais e contas completas na abertura da lista: nesta fixture são 1.718.789 bytes de documentos e 5.898.676 bytes de contas. É custo preexistente mensurável; não prova a causa da lentidão relatada em produção. Não foi feita refatoração dessa tela nem atribuição causal à rede, banco de produção ou versão. A nova dependência dos padrões contábeis no carregamento de JournalView pode atrasar/falhar a tela se o endpoint atrasar/falhar; não foi demonstrado que isso ocorre em produção e não foi alterada nesta correção.

Amostras e hashes exatos dos arquivos: [v0.8.0](benchmarks/movement-competence/v080.json), [dev.8 antes](benchmarks/movement-competence/develop-before.json), [correção](benchmarks/movement-competence/develop-after.json). No último JSON, `source_sha` identifica a base; `source_files_sha256` identifica os arquivos corrigidos ainda não commitados durante a medição.

Reprodução, com checkouts separados e dependências instaladas:

```sh
python scripts/benchmark_movement_queries.py --repo /caminho/v080 --source-sha b5d97a354115310e278d3ce86308a48cc2824356 --label v080 --repetitions 3 --output /tmp/v080.json
python scripts/benchmark_movement_queries.py --repo /caminho/dev8 --source-sha f1aac9964f25c1c0ad3ce76496fb89eb231fd101 --label before --repetitions 3 --output /tmp/before.json
python scripts/benchmark_movement_queries.py --label after --repetitions 3 --output /tmp/after.json
```

## Verificação e limites

Resultado local: **163 testes de backend, 141 testes de frontend, build Vite e os dois navegadores integrados passaram**. O navegador adicional `browser_document_summary.py` da PR34 confirmou setembro/agosto/outubro, filtros combinados, troca de empresa/exercício e hashes persistidos iguais sobre dev.9 com esta correção. O build manteve o aviso de bundle acima de 500 kB.

```sh
node --test frontend/tests/*.test.js
npm --prefix frontend run build
PYTHONPATH=tests:scripts:. python -m unittest test_journal_query_loading test_core test_business test_evolution test_accounting_report_models test_global_account_plans test_journal_participants test_bulk_operations test_bulk_security test_movement_exports test_report_models_api test_account_pagination test_workspace_context -q
python scripts/browser_workspace_context.py
python scripts/browser_document_summary.py
```

No ambiente local, os comandos de navegador usaram Playwright 1.56/Chromium 141 isolados em `/tmp` por `PYTHONPATH`, `PLAYWRIGHT_BROWSERS_PATH` e `ESCRITURA_TEST_BROWSER`; o backend usou a dependência DANFE isolada no `PYTHONPATH`.

- Testes novos de backend: isolamento empresa/mês/ano, detalhes completos, ordenação, estorno, quantidade limitada de consultas, restrição do exercício na API, ausência de escrita nas consultas e totais fiscais/contábeis por competência.
- Testes novos Vue: mês sugerido, mês operacional preservado, troca rápida 08/09, respostas fora de ordem, troca de empresa/exercício, retomada com KeepAlive e escopo financeiro explícito.
- Navegador integrado, Chromium 141 e SQLite sintético: novembro operacional com F8 setembro mostra 24 documentos e R$22 contábeis; agosto mostra um documento e R$11; outra empresa mostra zero; retorno restaura setembro. Exercita também filtros manuais, editor, navegação e atalhos F8/F9 existentes. Hashes de documentos, lançamentos, partidas, títulos e auditoria permanecem iguais; console sem erros. Relatório e screenshots em `artifacts/browser-workspace-context/`, produzidos pelo script já executado no CI.
- A suíte de backend inicialmente encontrou ausência local de BrazilFiscalReport; a dependência declarada foi instalada isoladamente em `/tmp` para repetir a suíte, sem alteração de dependências da aplicação.
- Não substitui homologação em produção. Não foram medidos PostgreSQL operacional, rede, concorrência, máquinas do usuário, instaladores ou bases reais. A lentidão fiscal relatada continua sem causa de produção comprovada. O CI remoto deve ser avaliado na PR; nenhum merge ou deploy é parte desta entrega.
