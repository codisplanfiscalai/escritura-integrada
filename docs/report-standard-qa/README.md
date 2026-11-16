# Padronização de relatórios — cobertura e limites

Base verificada: develop dev.30, `2bc2051486afeba3612b31fb112c32f213328cc9` (16/11/2026). Checkout isolado `escritura-report-standard-20261116`. Não encontrados AGENTS.md ou .agents/skills no checkout/ancestrais consultados. Referências lidas: RELATORIOS_E_MODELOS.md, RELATORIOS_REFERENCIA_E_CONFERENCIA.md e RELATORIOS_PROSOFT_REFERENCIAS.md. Nenhum dado operacional foi usado.

## Inventário e decisão visual

O catálogo tinha 17 modelos específicos. Os quatro relatórios financeiros/auxiliar sem modelo usavam uma exportação verde genérica. Reutilizamos a estrutura contábil existente (Vera incorporada, corpo 8, títulos 12, seções 10, cinza #e8e8e8/#f4f4f4, cabeçalho e folhas), inclusive para campos extras em anexo rastreável. Os modelos fiscais operacionais usam a mesma fonte e cinza, mantendo suas seções. Razão e P1/A/P2/A preservam suas geometrias de referência. Não há declaração de equivalência integral Prosoft.

| Relatório | Caminho de apresentação | PDF vazio / 45 registros (páginas) |
|---|---|---|
| Razão Analítico Individual (`ledger`) | Referência preservada | 1 / 2 |
| Registro de entradas P1/A — quadro ICMS (`fiscal-entries`) | Referência preservada | 1 / 3 |
| Registro de saídas P2/A — quadro ICMS (`fiscal-outputs`) | Referência preservada | 1 / 2 |
| Títulos por vencimento (`financial`) | Modelo contábil comum | 1 / 40 |
| Caixa realizado (`cash-flow`) | Modelo contábil comum | 1 / 39 |
| Conciliação de clientes e fornecedores (`partners`) | Modelo contábil comum | 1 / 38 |
| Livro auxiliar fiscal (`fiscal-book`) | Modelo contábil comum | 1 / 39 |
| Movimentação bancária (`bank-movements`) | Modelo contábil comum | 1 / 38 |
| Diário Geral (`diary`) | Modelo contábil comum | 1 / 24 |
| Diário Consolidado (`consolidated-diary`) | Modelo contábil comum | 1 / 27 |
| Balancete (`trial-balance`) | Modelo contábil comum | 1 / 27 |
| Balanço patrimonial (`balance-sheet`) | Modelo contábil comum | 1 / 29 |
| Demonstração do resultado (`income-statement`) | Modelo contábil comum | 1 / 32 |
| Centro de custo (`cost-centers`) | Modelo contábil comum | 1 / 32 |
| Documentos fiscais (`fiscal-documents`) | Fiscal operacional padronizado | 1 / 3 |
| Itens escriturados (`fiscal-items`) | Fiscal operacional padronizado | 1 / 5 |
| Operações por CFOP (`fiscal-operations`) | Fiscal operacional padronizado | 1 / 3 |
| Operações por participante (`fiscal-participants`) | Fiscal operacional padronizado | 1 / 3 |
| Itens por NCM e CFOP (`fiscal-classifications`) | Fiscal operacional padronizado | 1 / 3 |
| Bases e tributos declarados (`fiscal-taxes`) | Fiscal operacional padronizado | 1 / 18 |
| Pendências de conferência (`fiscal-inconsistencies`) | Fiscal operacional padronizado | 1 / 3 |
| Livro auxiliar de apuração (`fiscal-assessments`) | Fiscal operacional padronizado | 1 / 5 |

Também inventariados: memória individual de apuração (`assessment-memory`, exportação genérica agora no mesmo layout); Auditor analítico/sintético (PDF e XLSX em cinza, fonte já incorporada; versão visual de cache incrementada, históricos preservados); endpoints legados de diário/razão/balancete (dados, sem novo renderizador). CSV e dados brutos não recebem estilo. DANFE/DANFC-e/DACTE/DAMDFE e espelho CT-e OS são representações documentais e ficam fora desta alteração, preservando PR50.

## Movimentação bancária

Novo relatório no Contábil: empresa ativa, identificação exata da conta bancária (vazio = todas) e intervalo inclusivo. Não duplica Caixa realizado, que usa baixas/estornos de títulos. Lê bank_transactions em snapshot, ordena conta/data/id e preserva ID, referência, identificador e hash de origem. Filtros contábeis incompatíveis são rejeitados. Sem schema/migração, sem gravação de transações.

**Pendência funcional explícita:** bank_transactions não possui saldos de extrato nem uma origem validada de abertura. Abertura, saldo corrente e fechamento ficam `null`/não informados; o movimento líquido é identificado separadamente. Não se inferiu saldo a partir da soma do histórico parcial. Portanto o requisito de saldo de abertura real ainda não está entregue; depende de origem persistida e validada. Não homologar como extrato completo.

## Verificação

- `python scripts/qa_report_standard.py`: 44 PDFs, resultado de entrada imutável; primeiros e últimos renders por modelo em artifacts/report-standard; matriz neste diretório. Fixtures contábeis incluem campos extras de propósito para estressar anexo e paginação, não são dados de negócio reais.
- `PYTHONPATH=tests:. python -m unittest test_bank_report test_accounting_report_models test_fiscal_report_models test_fiscal_book_models test_report_models_api -v`: 38 testes aprovados.
- Validação final adicional: `PYTHONPATH=tests:. python -m unittest test_bank_report test_accounting_report_models test_fiscal_report_models test_report_models_api test_auditor_integration.AuditorIntegrationTests.test_full_reports_open_with_numeric_cells_and_evidence test_auditor_integration.AuditorIntegrationTests.test_prepared_reports_are_reused_on_first_download_and_preview test_auditor_integration.AuditorIntegrationTests.test_report_revisions_persist_and_treatments_do_not_replace_original_artifact -v`: 28 aprovados.
- `npm --prefix frontend ci` e `npm --prefix frontend run build`: aprovados; aviso de tamanho do bundle existente.
- `node --test frontend/tests/report*.test.js`: 16 aprovados.
- `python scripts/browser_report_standard.py`: script salvo, execução bloqueada antes de abrir navegador: Chromium `socket() failed: Operation not permitted`. Sem evidência de pixels da prévia ou impressão browser nesta execução. Não maximiza a prévia. QA Qt/Windows/macOS e impressora física não executados.
- `python -m unittest discover -s tests -v`: execução ampla com dependências ausentes `py7zr` e `brazilfiscalreport`; não deve ser descrita como suíte verde.

Inspeção visual: primeiras páginas da matriz, documentos fiscais após ajuste de CPF/CNPJ, página final do anexo bancário, Auditor e memória sintética. Não foi feita inspeção manual de cada página de todos os PDFs; não há certificação de paridade pixel a pixel. A numeração inicial e limite de folhas continuam testados. O ajuste de fonte e quebras pode mudar a quantidade física de páginas, sem omitir linhas.

## Integração

Escopo isolado de desempenho e PR50. Nenhuma alteração de workflows, GHCR, matrizes Windows/macOS, merge, deploy ou transmissão. Arquivos tocados estão no diff da PR; atenção a ReportsView.vue, reports.py, business_api.py, report_exports.py e módulos de apresentação caso a tarefa concorrente de desempenho também os edite.
