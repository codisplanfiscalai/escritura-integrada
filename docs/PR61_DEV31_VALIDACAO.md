# PR61: composição com develop dev.31

Base de conteúdo: `1cc358948b4447bd41bf77457f04a0837af37d1f`.
Head anterior preservado: `8ddf581ffdba5dfe689eadb3606f953dd383e0dc`.

A revisão automática recusou criar merge commit local. A alternativa indicada,
cherry-pick, incorporou linearmente `bdd827f` (PR60) e `1cc3589` (versão).
A árvore resultante contém develop dev.31 mais a PR61 e estes testes/documentação.
Não se declara develop como ancestral Git: é equivalência de conteúdo. O head
anterior permanece ancestral; publicação sem force e sem integrar a PR no develop.

A única diferença de aplicação para develop é `app/reports.py`; esse arquivo e
`test_ledger_query_loading.py` são idênticos ao head anterior. Preservadas PR60,
entradas/saídas, planos, backups e demais frentes. Otimização adicional de contas
sob demanda/XLSX não faz parte desta PR.

## Validação sintética desta composição

- 120 testes backend passaram em 87,004 s, incluindo dois testes novos que levam
  entradas diretas individuais e saídas diretas diárias até o Razão; conferem
  valores, contrapartidas, filtros de conta, período vazio, isolamento de empresa
  e leitura sem alteração. Plano global: IDs virtuais materializados e cópia
  das contas usadas preservam identidades e linhas do Razão.
- 189 testes frontend e build passaram; permanece aviso de bundle >500 kB.
- Chromium 141 / Playwright 1.56: integração direta sem modelos, modelo opcional,
  entradas individuais, saídas diárias, três empresas, resposta perdida/repetição,
  fechamento/reabertura e origem/balanceamento/FK passaram, sem erros JS.
- Navegador do Razão: 500 linhas, 50 por página, próxima página, CSV integral,
  pesquisa e contrapartidas; hashes de movimentos/auditoria intactos. Cinco
  amostras locais de renderização: 195,022 / 186,535 / 206,554 / 187,178 / 189,433 ms.
  São loopback e dados sintéticos, não VPS/produção. Não se repetiu comparação
  completa com v0.8.0; as medições históricas permanecem no diagnóstico original.

Comandos executados:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:. python -m unittest test_ledger_query_loading test_ledger_direct_composition test_direct_fiscal_accounting test_fiscal_sales_accounting test_fiscal_incoming_accounting test_fiscal_accounting_dev29_composition test_fiscal_accounting_prosoft_composition test_global_account_plans test_plan_manager test_business test_accounting_report_models test_report_models_api -q
node --test frontend/tests/*.test.js
npm run build --prefix frontend
python scripts/browser_fiscal_sales_accounting.py
python scripts/browser_report_loading.py --output artifacts/ledger-dev31/browser-ledger.json
```

Navegadores usaram runtime isolado, com PYTHONPATH, PLAYWRIGHT_BROWSERS_PATH e
ESCRITURA_TEST_BROWSER configurados. Evidências completas locais em artifacts.
Suíte integral, PostgreSQL operacional, Windows/Qt e produção não executados.
Novo CI remoto deve ser conferido no head publicado; o sucesso anterior
43896904370 validava somente 8ddf581. Sem merge da PR, release ou implantação.
