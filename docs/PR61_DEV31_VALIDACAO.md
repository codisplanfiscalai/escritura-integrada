# Atualização posterior: develop dev.32 e PR52

Base de conteúdo atual: `d8ec384528c0dc39953d72760ee3568a472ed371`.
Após publicar a composição dev.31 no head remoto `609c520`, develop incorporou
PR52 (`82217bc`) e dev.32. Seu delta foi aplicado por cherry-pick com primeiro
pai e o commit de versão por cherry-pick simples: ambos geram commits lineares,
sem merge commit e sem force. A publicação seguinte preserva 609c520 como pai.
Arquivos de backups, permissões, API, dependências e PR60 são idênticos à base;
app/reports.py continua a única diferença de aplicação.

Validação repetida nesta composição: 162 testes backend executados, 161 passaram
e 1 skip previsto de Windows nativo; zero falhas/erros, 101,586 s. Inclui todos
os 120 testes abaixo e test_backups, test_backup_crypto, test_backup_reliability
e test_backup_space. Os 192 testes frontend e build passaram. Chromium repetiu
integração fiscal direta e backups: quatro provedores, agenda, cancelamento,
backup manual com uploader simulado, restauração isolada e repetição recusada,
mobile e ausência de erros JS. Não houve conta cloud nem dado real.

A primeira execução nesta base falhou por falta de Cryptodome no ambiente;
pycryptodomex 3.24.2, fixado em requirements.txt, foi instalado em diretório
isolado e os testes completos acima foram repetidos. Nenhum teste foi removido.
O navegador específico do Razão e suas medições abaixo foram executados na
composição dev.31; os testes backend do Razão foram repetidos na dev.32.
CI 43906863101 corresponde à composição anterior e não aprova este novo head.
Aguardar CI próprio do novo head antes da integração coordenada.

---

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
